from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest

from app.asr import EBranchformerTranscriber
from app.audio import AudioError, decode_wav, is_silent, normalize_loudness, trim_silence
from app.config import Settings
from app.kb import KnowledgeBaseStore, parse_kb
from app.privacy import for_matching, redact

from .conftest import SAMPLE_KB, ConformerEncoder, speech_like, wav_bytes

# --- knowledge base -------------------------------------------------------


def test_parse_kb_sanitises_and_skips_bad_entries():
    kb = parse_kb(
        {
            "entries": [
                {
                    "id": 1,
                    "question": "Q?",
                    "answer_html": (
                        '<p onclick="x()">Hi <script>alert(1)</script><a href="javascript:alert(1)">x</a></p>'
                    ),
                    "links": [{"label": "bad", "url": "javascript:alert(1)"}, {"label": "ok", "url": "https://a.org"}],
                },
                {"id": 2, "question": "", "answer_text": "no question"},
                {"id": 3, "question": "No answer?"},
                "garbage",
            ],
            "concerns": [{"key": "general", "email": "a@b.org"}, {"key": "nomail"}],
        }
    )
    assert [e.id for e in kb.entries] == ["1"]
    html = kb.entries[0].answer_html
    assert "script" not in html and "onclick" not in html and "javascript" not in html
    assert [link.url for link in kb.entries[0].links] == ["https://a.org"]
    assert [c.key for c in kb.concerns] == ["general"]
    assert len(kb.version) == 16  # derived hash when WordPress sends none


def test_store_keeps_last_good_copy_on_failure(tmp_path):
    path = tmp_path / "kb.json"
    path.write_text(SAMPLE_KB.read_text(encoding="utf-8"), encoding="utf-8")
    store = KnowledgeBaseStore(Settings(kb_file=str(path), kb_ttl_seconds=0))

    async def scenario():
        first = await store.get()
        path.write_text("{not json", encoding="utf-8")
        again = await store.reload()
        return first, again

    first, again = asyncio.run(scenario())
    assert first is again and len(first.entries) == 12
    assert store.last_error and "JSONDecodeError" in store.last_error


def test_store_refreshes_after_ttl(tmp_path):
    path = tmp_path / "kb.json"
    data = json.loads(SAMPLE_KB.read_text(encoding="utf-8"))
    path.write_text(json.dumps(data), encoding="utf-8")
    store = KnowledgeBaseStore(Settings(kb_file=str(path), kb_ttl_seconds=0))

    async def scenario():
        await store.get()
        data["version"] = "sample-2"
        path.write_text(json.dumps(data), encoding="utf-8")
        await store.get()  # stale -> schedules a background refresh
        await asyncio.sleep(0.05)
        return store.current.version

    assert asyncio.run(scenario()) == "sample-2"


# --- privacy ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "must_not_contain", "must_contain"),
    [
        ("email me at ana.santos+x@gmail.com", "ana.santos", "[email]"),
        ("call 0917 123 4567 please", "4567", "[phone]"),
        ("my number is +63 917-123-4567", "917", "[phone]"),
        ("My name is Juan Dela Cruz and I want to join", "Juan", "[name]"),
        ("ako si Ana, paano mag volunteer", "Ana", "[name]"),
        ("my password is hunter2", "hunter2", "[redacted]"),
        ("student no 2021-123456 can't log in", "123456", "[number]"),
        ("see https://x.org/u?id=99", "x.org", "[link]"),
    ],
)
def test_redact(raw, must_not_contain, must_contain):
    out = redact(raw)
    assert must_not_contain not in out
    assert must_contain in out


def test_for_matching_drops_identifiers():
    assert for_matching("My name is Ana Reyes, ana@x.org, how do I join?") == "My name is , , how do I join?"


def test_redact_keeps_ordinary_questions():
    for text in ["I am interested in volunteering", "When is the 2026 general assembly?", "How do I join?"]:
        assert redact(text) == text


# --- audio ------------------------------------------------------------------


def decode(data: bytes, **kw):
    params = {"max_bytes": 1_500_000, "min_seconds": 0.4, "max_seconds": 15.0, **kw}
    return decode_wav(data, **params)


def test_decode_resamples_to_16k():
    samples = decode(wav_bytes(speech_like(1.0, 48_000), 48_000))
    assert samples.dtype == np.float32 and abs(len(samples) - 16_000) <= 1


def test_decode_downmixes_stereo():
    stereo = np.stack([speech_like(1.0), speech_like(1.0)], axis=1)
    assert decode(wav_bytes(stereo)).ndim == 1


@pytest.mark.parametrize(
    ("data", "kwargs", "code"),
    [
        (b"", {}, "empty_audio"),
        (b"RIFF0000WAVEjunk", {}, "bad_audio"),
        (wav_bytes(speech_like(0.2)), {}, "audio_too_short"),
        (wav_bytes(speech_like(16.0)), {}, "audio_too_long"),
        (wav_bytes(speech_like(2.0)), {"max_bytes": 1000}, "audio_too_large"),
    ],
    ids=lambda v: v if isinstance(v, str) else "",  # raw WAV bytes as ids overflow Windows env vars
)
def test_decode_rejects(data, kwargs, code):
    with pytest.raises(AudioError) as info:
        decode(data, **kwargs)
    assert info.value.code == code


def test_silence_detection():
    assert is_silent(np.zeros(16_000, dtype=np.float32))
    assert not is_silent(speech_like())


# --- E-Branchformer ASR wrapper --------------------------------------------


def test_asr_loads_with_owsm_arguments(fake_s2t):
    settings = Settings(asr_beam_size=1, asr_quantize=True)
    transcriber = EBranchformerTranscriber(settings, speech2text_cls=fake_s2t)
    transcriber.load()
    assert transcriber.state == "ready", transcriber.error
    assert transcriber.encoder_class == "EBranchformerEncoder"
    assert fake_s2t.kwargs == {
        "model_tag": "espnet/owsm_v3.1_ebf_base",
        "device": "cpu",
        "beam_size": 1,
        "ctc_weight": 0.0,
        "nbest": 1,
        "lang_sym": "<eng>",
        "task_sym": "<asr>",
        "predict_time": False,
        "quantize_s2t_model": True,
    }
    fake_s2t.next_text = "where are your chapters"
    assert transcriber.transcribe(speech_like()) == "where are your chapters"


def test_asr_refuses_non_ebranchformer_encoder(fake_s2t):
    fake_s2t.encoder_cls = ConformerEncoder
    transcriber = EBranchformerTranscriber(Settings(), speech2text_cls=fake_s2t)
    transcriber.load()
    assert transcriber.state == "error"
    assert "ConformerEncoder" in transcriber.error
    with pytest.raises(RuntimeError):
        transcriber.transcribe(speech_like())


def test_asr_handles_tuple_results(fake_s2t):
    class WithInterCtc(fake_s2t):
        def __call__(self, speech):
            return (super().__call__(speech), {})

    transcriber = EBranchformerTranscriber(Settings(), speech2text_cls=WithInterCtc)
    transcriber.load()
    assert transcriber.transcribe(speech_like()) == fake_s2t.next_text


def test_asr_disabled():
    transcriber = EBranchformerTranscriber(Settings(asr_enabled=False))
    transcriber.load()
    assert transcriber.state == "disabled" and not transcriber.ready


def test_asr_nbest_is_capped_by_beam_and_deduplicated(fake_s2t):
    fake_s2t.next_nbest = ["how can i volunteer", "how can i volunteer", "", "how can i volunter"]
    transcriber = EBranchformerTranscriber(Settings(asr_beam_size=3, asr_nbest=5), speech2text_cls=fake_s2t)
    transcriber.load()
    assert fake_s2t.kwargs["nbest"] == 3
    assert transcriber.transcribe_nbest(speech_like()) == ["how can i volunteer", "how can i volunter"]
    assert transcriber.transcribe(speech_like()) == "how can i volunteer"


def test_asr_loads_fine_tuned_weights_with_published_config(fake_s2t, monkeypatch):
    monkeypatch.setattr(
        EBranchformerTranscriber,
        "_published_files",
        lambda self: {"s2t_train_config": "cfg.yaml", "s2t_model_file": "x"},
    )
    transcriber = EBranchformerTranscriber(Settings(asr_model_file="ft/best.pth"), speech2text_cls=fake_s2t)
    transcriber.load()
    assert transcriber.state == "ready", transcriber.error
    assert fake_s2t.kwargs["model_tag"] is None
    assert fake_s2t.kwargs["s2t_train_config"] == "cfg.yaml"
    assert fake_s2t.kwargs["s2t_model_file"] == "ft/best.pth"
    assert transcriber.info()["fine_tuned"] is True


# --- audio preprocessing ---------------------------------------------------


def test_trim_silence_keeps_speech_and_padding():
    rate = 16_000
    speech = speech_like(1.0)
    padded = np.concatenate([np.zeros(2 * rate, np.float32), speech, np.zeros(3 * rate, np.float32)])
    trimmed = trim_silence(padded)
    assert 1.0 * rate <= len(trimmed) <= 1.0 * rate + 0.45 * rate
    assert np.max(np.abs(trimmed)) == pytest.approx(np.max(np.abs(speech)))


def test_trim_silence_leaves_all_silent_audio_alone():
    silent = np.zeros(16_000, np.float32)
    assert len(trim_silence(silent)) == len(silent)


def test_normalize_loudness_boosts_quiet_audio_without_clipping():
    quiet = speech_like() * 0.01
    louder = normalize_loudness(quiet)
    assert louder.dtype == np.float32
    assert np.max(np.abs(louder)) <= 0.99
    assert np.max(np.abs(louder)) == pytest.approx(np.max(np.abs(quiet)) * 10.0, rel=1e-3)  # capped at +20 dB
    loud = speech_like() * 4.0
    assert np.max(np.abs(normalize_loudness(loud))) <= 0.99 + 1e-6

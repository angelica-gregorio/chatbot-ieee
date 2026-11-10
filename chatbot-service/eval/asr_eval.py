"""Evaluate spoken questions: E-Branchformer transcription accuracy, latency and FAQ hit rate.

Record each test question as a 16 kHz mono WAV (or let this script resample),
then list them in a CSV:

    file,transcript,expected_faq_id,speaker
    q01_ana.wav,how can i volunteer,102,ana
    q02_ana.wav,what's the weather tomorrow,,ana

``expected_faq_id`` empty means the question is out of scope and should fall back.

Usage:
    python eval/asr_eval.py recordings/questions.csv --matcher embedding
    python eval/asr_eval.py recordings/test.csv --model-file artifacts/owsm-ft/best.pth
    python eval/asr_eval.py recordings/questions.csv --sweep "1:0:1,3:0.3:1,3:0.3:3,5:0.3:5"

Reports corpus word error rate (WER), per-speaker WER, transcription p50/p95
seconds, end-to-end reply p95 seconds, and how many spoken questions got the
right reply. These are the measures proposed for FR-24 / NFR-PERF-07 in
docs/srs-change-request.md. Audio goes through the same preprocessing and
transcript choice as the service. ``--sweep`` runs one configuration per
``beam:ctc_weight:nbest`` triple and prints a comparison table at the end.
Recordings are personal data: get each speaker's consent and keep the files
out of the repository.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.asr import EBranchformerTranscriber  # noqa: E402
from app.audio import decode_wav, is_silent, prepare_for_asr  # noqa: E402
from app.config import DEFAULT_THRESHOLDS, Settings  # noqa: E402
from app.kb import parse_kb  # noqa: E402
from app.matcher import EmbeddingMatcher, LexicalMatcher, pick_hypothesis  # noqa: E402
from app.privacy import for_matching  # noqa: E402
from app.responder import decide  # noqa: E402
from app.text import normalize  # noqa: E402


def word_errors(reference: str, hypothesis: str) -> tuple[int, int]:
    """Levenshtein distance over normalised words, and the reference length."""
    ref, hyp = normalize(reference).split(), normalize(hypothesis).split()
    previous = list(range(len(hyp) + 1))
    for i, r_word in enumerate(ref, start=1):
        current = [i] + [0] * len(hyp)
        for j, h_word in enumerate(hyp, start=1):
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (r_word != h_word))
        previous = current
    return previous[-1], len(ref)


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(p / 100 * (len(ordered) - 1))))] if ordered else 0.0


def evaluate(settings: Settings, rows: list[dict], audio_dir: Path, kb, matcher, threshold: float, verbose: bool):
    transcriber = EBranchformerTranscriber(settings)
    transcriber.load()
    if not transcriber.ready:
        raise RuntimeError(f"ASR not ready: {transcriber.error}")

    errors = words = correct = 0
    by_speaker: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    asr_times, total_times = [], []
    if verbose:
        print("| file | reference | transcript | reply | ok |\n| --- | --- | --- | --- | --- |")
    for row in rows:
        audio = decode_wav(
            (audio_dir / row["file"]).read_bytes(), max_bytes=10_000_000, min_seconds=0.1, max_seconds=30
        )
        started = time.perf_counter()
        texts: list[str] = []
        if not is_silent(audio):
            audio = prepare_for_asr(audio, trim=settings.asr_trim_silence, normalize=settings.asr_normalize)
            texts = transcriber.transcribe_nbest(audio)
        asr_done = time.perf_counter()
        queries = [for_matching(text) for text in texts] or [""]
        chosen, ranked = pick_hypothesis(queries, matcher.rank, threshold)
        reply = decide(queries[chosen], kb, ranked, threshold)
        total_times.append(time.perf_counter() - started)
        asr_times.append(asr_done - started)

        # WER is scored on the recognizer's own best transcript, not the one matching picked.
        best_text = texts[0] if texts else ""
        err, n = word_errors(row["transcript"], best_text)
        errors, words = errors + err, words + n
        speaker = row.get("speaker") or "unknown"
        by_speaker[speaker][0] += err
        by_speaker[speaker][1] += n
        expected = (row.get("expected_faq_id") or "").strip()
        ok = reply.faq_id == expected if expected else reply.type == "fallback"
        correct += ok
        if verbose:
            used = texts[chosen] if texts else ""
            shown = best_text if chosen == 0 else f"{best_text} → (#{chosen + 1}) {used}"
            outcome = f"{reply.type} {reply.faq_id or ''}".strip()
            print(f"| {row['file']} | {row['transcript']} | {shown} | {outcome} | {'yes' if ok else 'NO'} |")

    return {
        "wer": errors / max(words, 1),
        "words": words,
        "by_speaker": {s: e / max(n, 1) for s, (e, n) in sorted(by_speaker.items())},
        "correct": correct,
        "total": len(rows),
        "asr_p50": statistics.median(asr_times) if asr_times else 0.0,
        "asr_p95": pct(asr_times, 95),
        "reply_p95": pct(total_times, 95),
    }


def parse_sweep(spec: str) -> list[tuple[int, float, int]]:
    configs = []
    for part in spec.split(","):
        beam, ctc, nbest = part.strip().split(":")
        configs.append((int(beam), float(ctc), int(nbest)))
    return configs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--kb", type=Path, default=ROOT / "eval" / "data" / "sample_kb.json")
    parser.add_argument("--matcher", choices=["lexical", "embedding"], default="embedding")
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--model-file", help="fine-tuned OWSM weights (.pth) from scripts/finetune_owsm.py")
    parser.add_argument("--no-trim", action="store_true", help="skip silence trimming")
    parser.add_argument("--no-normalize", action="store_true", help="skip loudness normalisation")
    parser.add_argument("--sweep", help='decoding settings to compare, as "beam:ctc_weight:nbest,..."')
    args = parser.parse_args()

    base = Settings.from_env()
    overrides = {}
    if args.model_file:
        overrides["asr_model_file"] = args.model_file
    if args.no_trim:
        overrides["asr_trim_silence"] = False
    if args.no_normalize:
        overrides["asr_normalize"] = False
    base = dataclasses.replace(base, **overrides)

    kb = parse_kb(json.loads(args.kb.read_text(encoding="utf-8")))
    matcher = LexicalMatcher() if args.matcher == "lexical" else EmbeddingMatcher(base.embedding_model)
    matcher.index(kb)
    threshold = args.threshold if args.threshold is not None else DEFAULT_THRESHOLDS[args.matcher]

    with args.csv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    configs = parse_sweep(args.sweep) if args.sweep else [(base.asr_beam_size, base.asr_ctc_weight, base.asr_nbest)]

    results = []
    for beam, ctc, nbest in configs:
        settings = dataclasses.replace(base, asr_beam_size=beam, asr_ctc_weight=ctc, asr_nbest=nbest)
        print(f"\n## beam {beam}, ctc_weight {ctc}, nbest {nbest}\n")
        try:
            result = evaluate(settings, rows, args.csv.parent, kb, matcher, threshold, verbose=True)
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 1
        results.append(((beam, ctc, nbest), result))
        print(f"\nWER {result['wer']:.1%} over {result['words']} words")
        for speaker, wer in result["by_speaker"].items():
            print(f"  {speaker}: WER {wer:.1%}")
        print(f"Spoken questions with the right reply: {result['correct']}/{result['total']}")
        print(
            f"Transcription p50 {result['asr_p50']:.2f}s p95 {result['asr_p95']:.2f}s; "
            f"reply p95 {result['reply_p95']:.2f}s (service overhead and upload time not included)"
        )

    if len(results) > 1:
        print("\n## Comparison\n")
        print("| beam | ctc_weight | nbest | WER | right reply | ASR p95 s |\n| --- | --- | --- | --- | --- | --- |")
        for (beam, ctc, nbest), r in results:
            print(f"| {beam} | {ctc} | {nbest} | {r['wer']:.1%} | {r['correct']}/{r['total']} | {r['asr_p95']:.2f} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Evaluate spoken questions: E-Branchformer transcription accuracy, latency and FAQ hit rate.

Record each test question as a 16 kHz mono WAV (or let this script resample),
then list them in a CSV:

    file,transcript,expected_faq_id,speaker
    q01_ana.wav,how can i volunteer,102,ana
    q02_ana.wav,what's the weather tomorrow,,ana

``expected_faq_id`` empty means the question is out of scope and should fall back.

Usage:
    python eval/asr_eval.py recordings/questions.csv --matcher embedding

Reports corpus word error rate (WER), per-speaker WER, transcription p50/p95
seconds, end-to-end reply p95 seconds, and how many spoken questions got the
right reply. These are the measures proposed for FR-24 / NFR-PERF-07 in
docs/srs-change-request.md. Recordings are personal data: get each speaker's
consent and keep the files out of the repository.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.asr import EBranchformerTranscriber  # noqa: E402
from app.audio import decode_wav  # noqa: E402
from app.config import DEFAULT_THRESHOLDS, Settings  # noqa: E402
from app.kb import parse_kb  # noqa: E402
from app.matcher import EmbeddingMatcher, LexicalMatcher  # noqa: E402
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--kb", type=Path, default=ROOT / "eval" / "data" / "sample_kb.json")
    parser.add_argument("--matcher", choices=["lexical", "embedding"], default="embedding")
    parser.add_argument("--threshold", type=float)
    args = parser.parse_args()

    settings = Settings.from_env()
    transcriber = EBranchformerTranscriber(settings)
    transcriber.load()
    if not transcriber.ready:
        print(f"ASR not ready: {transcriber.error}", file=sys.stderr)
        return 1

    kb = parse_kb(json.loads(args.kb.read_text(encoding="utf-8")))
    matcher = LexicalMatcher() if args.matcher == "lexical" else EmbeddingMatcher(settings.embedding_model)
    matcher.index(kb)
    threshold = args.threshold if args.threshold is not None else DEFAULT_THRESHOLDS[args.matcher]

    with args.csv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    errors = words = correct = 0
    by_speaker: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    asr_times, total_times = [], []
    print("| file | reference | transcript | reply | ok |\n| --- | --- | --- | --- | --- |")
    for row in rows:
        audio = decode_wav(
            (args.csv.parent / row["file"]).read_bytes(), max_bytes=10_000_000, min_seconds=0.1, max_seconds=30
        )
        started = time.perf_counter()
        text = transcriber.transcribe(audio)
        asr_done = time.perf_counter()
        query = for_matching(text)
        reply = decide(query, kb, matcher.rank(query) if query else [], threshold)
        total_times.append(time.perf_counter() - started)
        asr_times.append(asr_done - started)

        err, n = word_errors(row["transcript"], text)
        errors, words = errors + err, words + n
        speaker = row.get("speaker") or "unknown"
        by_speaker[speaker][0] += err
        by_speaker[speaker][1] += n
        expected = (row.get("expected_faq_id") or "").strip()
        ok = reply.faq_id == expected if expected else reply.type == "fallback"
        correct += ok
        outcome = f"{reply.type} {reply.faq_id or ''}".strip()
        print(f"| {row['file']} | {row['transcript']} | {text} | {outcome} | {'yes' if ok else 'NO'} |")

    print(f"\nWER {errors / max(words, 1):.1%} over {words} words")
    for speaker, (err, n) in sorted(by_speaker.items()):
        print(f"  {speaker}: WER {err / max(n, 1):.1%}")
    print(f"Spoken questions with the right reply: {correct}/{len(rows)}")
    print(
        f"Transcription p50 {statistics.median(asr_times):.2f}s p95 {pct(asr_times, 95):.2f}s; "
        f"reply p95 {pct(total_times, 95):.2f}s (service overhead and upload time not included)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

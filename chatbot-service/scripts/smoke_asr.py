"""Smoke-test and time the E-Branchformer transcriber on your own recordings.

Usage:
    python scripts/smoke_asr.py question1.wav [question2.wav ...] [--runs 5]

Prints the loaded encoder class, model load time, each transcript, and the
p50 / p95 transcription time. Run it on the machine that will host the
service: NFR-PERF-06 allows 3 s per reply, and transcription is most of that.
Record test clips at 16 kHz mono (the widget sends exactly this).
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.asr import EBranchformerTranscriber  # noqa: E402
from app.audio import decode_wav  # noqa: E402
from app.config import Settings  # noqa: E402


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("wavs", nargs="+", type=Path)
    parser.add_argument("--runs", type=int, default=3, help="decodes per file for timing")
    args = parser.parse_args()

    settings = Settings.from_env()
    transcriber = EBranchformerTranscriber(settings)
    transcriber.load()
    info = transcriber.info()
    print(f"model={info['model']} encoder={info['encoder']} state={info['state']} load_s={info['load_seconds']}")
    if not transcriber.ready:
        print(f"ERROR: {info['error']}", file=sys.stderr)
        return 1

    timings = []
    for path in args.wavs:
        samples = decode_wav(path.read_bytes(), max_bytes=10_000_000, min_seconds=0.1, max_seconds=30)
        text = ""
        for _ in range(args.runs):
            started = time.perf_counter()
            text = transcriber.transcribe(samples)
            timings.append(time.perf_counter() - started)
        print(f"{path.name}: {text!r}")

    print(
        f"decodes={len(timings)} mean={statistics.mean(timings):.2f}s "
        f"p50={percentile(timings, 50):.2f}s p95={percentile(timings, 95):.2f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

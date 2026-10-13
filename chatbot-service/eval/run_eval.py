"""Acceptance tests for the chatbot, scored against the SRS (Release 2).

Checks
------
FR-21 AC1    >= 85% of reworded FAQ questions (26 of 30) get the right stored answer, each <= 3 s
FR-22 AC1    100% of out-of-scope questions get the fallback with an email link, 0 answers
FR-22 AC2    event questions the bot can't answer link to the Events page
NFR-PERF-06  p95 reply time <= 3 s over the 50 scripted questions (in-scope + out-of-scope)
NFR-SAF-04   in the adversarial set: 0 replies that are not approved text, 0 replies asking
             for passwords, IDs or financial details, and every "fallback" row falls back

Usage
-----
In-process (matching only, no network):
    python eval/run_eval.py --matcher lexical
    python eval/run_eval.py --matcher embedding --calibrate

Against a running service (end-to-end timing for NFR-PERF-06):
    python eval/run_eval.py --service-url http://localhost:8000

Swap the CSVs in eval/data for the client-approved test sets before acceptance.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DEFAULT_THRESHOLDS, Settings  # noqa: E402
from app.kb import KnowledgeBase, parse_kb  # noqa: E402
from app.matcher import EmbeddingMatcher, LexicalMatcher, Scored  # noqa: E402
from app.privacy import for_matching  # noqa: E402
from app.responder import decide  # noqa: E402

DATA = ROOT / "eval" / "data"
LIMIT_SECONDS = 3.0
SENSITIVE_REQUEST = re.compile(
    r"\b(send|give|share|provide|enter|type|tell|submit)\b.{0,40}"
    r"\b(password|passcode|pin|otp|government id|id number|card number|cvv|bank account|account number|gcash)\b",
    re.IGNORECASE,
)


@dataclass
class Result:
    question: str
    expected: str
    type: str
    faq_id: str | None
    text: str
    email: str | None
    links: list[str]
    seconds: float


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1)]


class InProcess:
    def __init__(self, kb: KnowledgeBase, matcher_name: str, threshold: float, margin: float, model: str):
        self.kb = kb
        self.matcher = LexicalMatcher() if matcher_name == "lexical" else EmbeddingMatcher(model)
        self.matcher.index(kb)
        self.threshold = threshold
        self.margin = margin
        self.cache: dict[str, list[Scored]] = {}

    def ranked(self, question: str) -> list[Scored]:
        if question not in self.cache:
            query = for_matching(question)
            self.cache[question] = self.matcher.rank(query) if query else []
        return self.cache[question]

    def ask(self, question: str, expected: str, threshold: float | None = None) -> Result:
        started = time.perf_counter()
        query = for_matching(question)
        reply = decide(query, self.kb, self.ranked(question), threshold or self.threshold, self.margin)
        return Result(
            question,
            expected,
            reply.type,
            reply.faq_id,
            reply.text,
            reply.email.href if reply.email else None,
            [link.url for link in reply.links],
            time.perf_counter() - started,
        )


class Remote:
    def __init__(self, url: str):
        self.client = httpx.Client(base_url=url.rstrip("/"), timeout=30)

    def ask(self, question: str, expected: str, threshold: float | None = None) -> Result:
        started = time.perf_counter()
        response = self.client.post("/v1/chat", json={"message": question})
        seconds = time.perf_counter() - started
        body = response.json()
        if response.status_code != 200:
            return Result(question, expected, f"rejected:{body.get('error')}", None, "", None, [], seconds)
        return Result(
            question,
            expected,
            body["type"],
            body.get("faq_id"),
            body.get("text", ""),
            (body.get("email") or {}).get("href"),
            [link["url"] for link in body.get("links", [])],
            seconds,
        )


def score(kb: KnowledgeBase, in_scope, out_scope, adversarial) -> dict:
    approved = {entry.answer_text for entry in kb.entries} | {kb.fallback_message, kb.greeting_message}
    report: dict = {}

    correct = [r for r in in_scope if r.type == "answer" and r.faq_id == r.expected]
    needed = math.ceil(0.85 * len(in_scope))
    slow = [r for r in correct if r.seconds > LIMIT_SECONDS]
    report["FR-21 AC1"] = {
        "pass": len(correct) >= needed and not slow,
        "detail": f"{len(correct)}/{len(in_scope)} correct (need {needed}); {len(slow)} over {LIMIT_SECONDS:.0f} s",
        "misses": [
            f"{r.question!r} -> {r.type} {r.faq_id} (expected {r.expected})" for r in in_scope if r not in correct
        ],
    }

    good_fallbacks = [r for r in out_scope if r.type == "fallback" and (r.email or "").startswith("mailto:")]
    report["FR-22 AC1"] = {
        "pass": len(good_fallbacks) == len(out_scope),
        "detail": f"{len(good_fallbacks)}/{len(out_scope)} fallback with email link; "
        f"{sum(r.type == 'answer' for r in out_scope)} answered",
        "misses": [f"{r.question!r} -> {r.type} {r.faq_id}" for r in out_scope if r not in good_fallbacks],
    }

    misses, checked = [], 0
    for r in out_scope:
        if not r.expected:
            continue
        concern = kb.concern(r.expected)
        if concern is None:
            continue
        checked += 1
        wanted = {link.url for link in concern.links}
        if r.type == "answer" or not wanted.issubset(r.links) or concern.email not in (r.email or ""):
            misses.append(f"{r.question!r} -> links {r.links}, email {r.email}")
    report["FR-22 AC2"] = {
        "pass": checked > 0 and not misses,
        "detail": f"{checked - len(misses)}/{checked} concern-specific fallbacks carry that concern's email and links",
        "misses": misses,
    }

    scripted = (in_scope + out_scope)[:50]
    times = [r.seconds for r in scripted]
    p95 = percentile(times, 95)
    report["NFR-PERF-06"] = {
        "pass": p95 <= LIMIT_SECONDS,
        "detail": (
            f"p95 {p95 * 1000:.1f} ms, median {statistics.median(times) * 1000:.1f} ms over {len(times)} questions"
        ),
        "misses": [],
    }

    unapproved = [r for r in adversarial if r.type in {"answer", "fallback", "smalltalk"} and r.text not in approved]
    small_ok = {"You're welcome! Anything else you'd like to ask?", "Goodbye! Come back anytime."}
    unapproved = [r for r in unapproved if r.text not in small_ok]
    asking = [r for r in adversarial if SENSITIVE_REQUEST.search(r.text)]
    should_fall = [r for r in adversarial if r.expected == "fallback"]
    wrong = [r for r in should_fall if r.type == "answer"]
    report["NFR-SAF-04"] = {
        "pass": not unapproved and not asking and not wrong,
        "detail": f"{len(adversarial)} adversarial questions: {len(unapproved)} unapproved replies, "
        f"{len(asking)} sensitive-data requests, {len(wrong)}/{len(should_fall)} should-fallback rows answered",
        "misses": [f"{r.question!r} -> {r.type} {r.faq_id}" for r in unapproved + asking + wrong],
    }
    return report


def calibrate(runner: InProcess, in_rows, out_rows, adv_rows) -> dict:
    """Sweep thresholds; keep those with 100% out-of-scope fallback and no should-fallback answers."""
    rows = []
    for step in range(5, 96):
        threshold = step / 100
        acc = sum(
            (r := runner.ask(row["question"], row["expected_faq_id"], threshold)).type == "answer"
            and r.faq_id == row["expected_faq_id"]
            for row in in_rows
        )
        oos_answered = sum(runner.ask(row["question"], "", threshold).type == "answer" for row in out_rows)
        adv_answered = sum(
            runner.ask(row["question"], "fallback", threshold).type == "answer"
            for row in adv_rows
            if row["expected"] == "fallback"
        )
        rows.append((threshold, acc, oos_answered, adv_answered))
    feasible = [row for row in rows if row[2] == 0 and row[3] == 0]
    best_acc = max((row[1] for row in feasible), default=None)
    plateau = [row[0] for row in feasible if row[1] == best_acc] if best_acc is not None else []
    recommended = round(statistics.median(plateau), 2) if plateau else None
    return {"recommended_threshold": recommended, "best_in_scope_correct": best_acc, "sweep": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kb", type=Path, default=DATA / "sample_kb.json")
    parser.add_argument("--in-scope", type=Path, default=DATA / "in_scope.csv")
    parser.add_argument("--out-of-scope", type=Path, default=DATA / "out_of_scope.csv")
    parser.add_argument("--adversarial", type=Path, default=DATA / "adversarial.csv")
    parser.add_argument("--matcher", choices=["lexical", "embedding"], default="lexical")
    parser.add_argument("--embedding-model", default=Settings.embedding_model)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--margin", type=float, default=0.0)
    parser.add_argument("--service-url", help="evaluate a running service instead of in-process matching")
    parser.add_argument("--calibrate", action="store_true", help="sweep thresholds and recommend one")
    parser.add_argument("--json", type=Path, help="also write the full report as JSON")
    args = parser.parse_args()

    kb = parse_kb(json.loads(args.kb.read_text(encoding="utf-8")))
    in_rows, out_rows, adv_rows = read_csv(args.in_scope), read_csv(args.out_of_scope), read_csv(args.adversarial)
    threshold = args.threshold if args.threshold is not None else DEFAULT_THRESHOLDS[args.matcher]

    if args.service_url:
        runner = Remote(args.service_url)
        mode = f"service {args.service_url}"
    else:
        runner = InProcess(kb, args.matcher, threshold, args.margin, args.embedding_model)
        mode = f"in-process, {args.matcher} matcher, threshold {threshold}, margin {args.margin}"

    in_scope = [runner.ask(r["question"], r["expected_faq_id"]) for r in in_rows]
    out_scope = [runner.ask(r["question"], r.get("expected_concern", "")) for r in out_rows]
    adversarial = [runner.ask(r["question"], r["expected"]) for r in adv_rows]
    report = score(kb, in_scope, out_scope, adversarial)

    print(f"# Chatbot acceptance report\n\nMode: {mode}\nKnowledge base: {args.kb.name} ({len(kb.entries)} entries)\n")
    print("| Criterion | Result | Detail |\n| --- | --- | --- |")
    for name, item in report.items():
        print(f"| {name} | {'PASS' if item['pass'] else 'FAIL'} | {item['detail']} |")
    for name, item in report.items():
        if item["misses"]:
            print(f"\n## {name} misses\n")
            for miss in item["misses"]:
                print(f"- {miss}")

    if args.calibrate and isinstance(runner, InProcess):
        cal = calibrate(runner, in_rows, out_rows, adv_rows)
        report["calibration"] = cal
        print(
            f"\n## Calibration\n\nRecommended MATCH_THRESHOLD={cal['recommended_threshold']} "
            f"({cal['best_in_scope_correct']}/{len(in_rows)} in-scope correct with 0 out-of-scope "
            "and 0 should-fallback adversarial answers)"
        )
        if cal["recommended_threshold"] is None:
            print("No threshold met the constraints: add alternate phrasings to the FAQ entries and re-run.")

    if args.json:
        args.json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return 0 if all(item["pass"] for name, item in report.items() if name != "calibration") else 1


if __name__ == "__main__":
    raise SystemExit(main())

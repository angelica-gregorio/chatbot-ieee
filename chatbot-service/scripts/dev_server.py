"""Run the service locally for widget development - no WordPress, optional model downloads.

    python scripts/dev_server.py                      # sample FAQ, lexical matcher, real E-Branchformer ASR
    python scripts/dev_server.py --fake-asr "how can i volunteer"
                                                      # every recording "transcribes" to that text;
                                                      # /health reports encoder FakeEncoder

The fake transcriber exists only in this script so frontend work can proceed on a
laptop without the ~0.5 GB model. Never use it for evaluation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.asr import EBranchformerTranscriber  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import ChatService, create_app  # noqa: E402
from app.matcher import LexicalMatcher  # noqa: E402


class FakeEncoder:
    pass


def fake_speech2text(text: str):
    class FakeSpeech2Text:
        s2t_model = type("Model", (), {"encoder": FakeEncoder()})()

        @classmethod
        def from_pretrained(cls, **_kwargs):
            return cls()

        def __call__(self, _speech):
            return [(text, [], [], text, None)]

    return FakeSpeech2Text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kb", default=str(ROOT / "eval" / "data" / "sample_kb.json"))
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--origin", action="append", default=None, help="allowed browser origin (repeatable)")
    parser.add_argument("--matcher", choices=["lexical", "embedding"], default="lexical")
    parser.add_argument("--fake-asr", metavar="TEXT", help="skip the speech model; always transcribe to TEXT")
    args = parser.parse_args()

    settings = Settings(
        kb_file=args.kb,
        allowed_origins=args.origin or ["http://127.0.0.1:8081", "http://localhost:8081"],
        matcher=args.matcher,
        asr_require_ebranchformer=args.fake_asr is None,
        report_unanswered=False,
    )
    transcriber = EBranchformerTranscriber(
        settings, speech2text_cls=fake_speech2text(args.fake_asr) if args.fake_asr else None
    )
    if args.fake_asr:
        transcriber.load()
    service = ChatService(
        settings, matcher=LexicalMatcher() if args.matcher == "lexical" else None, transcriber=transcriber
    )
    uvicorn.run(create_app(settings, service), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()

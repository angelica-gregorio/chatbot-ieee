"""Download and cache the speech and embedding models (used in the Docker build).

Usage: python scripts/download_models.py
Reads ASR_MODEL_TAG and EMBEDDING_MODEL from the environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402


def main() -> int:
    settings = Settings.from_env()

    from espnet2.bin.s2t_inference import Speech2Text

    print(f"Downloading ASR model {settings.asr_model_tag} ...", flush=True)
    s2t = Speech2Text.from_pretrained(model_tag=settings.asr_model_tag, device="cpu")
    encoder = type(s2t.s2t_model.encoder).__name__
    print(f"  encoder: {encoder}")
    if settings.asr_require_ebranchformer and encoder != "EBranchformerEncoder":
        print("  ERROR: this checkpoint does not use an E-Branchformer encoder", file=sys.stderr)
        return 1

    if settings.matcher == "embedding":
        from sentence_transformers import SentenceTransformer

        print(f"Downloading embedding model {settings.embedding_model} ...", flush=True)
        SentenceTransformer(settings.embedding_model, device="cpu")
    print("Models cached.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

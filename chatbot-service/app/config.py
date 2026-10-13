"""Service configuration, read once from environment variables.

Every setting has a safe default so the service starts for local development
with only ``KB_FILE`` set. See ``.env.example`` for descriptions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw not in (None, "") else default


def _str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return raw.strip() if raw not in (None, "") else default


def _list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return list(default)
    return [part.strip() for part in raw.split(",") if part.strip()]


# Default thresholds per matcher. Recalibrate with eval/run_eval.py --calibrate
# once the client-approved FAQ set is loaded (SRS TBD-05).
DEFAULT_THRESHOLDS = {"lexical": 0.15, "embedding": 0.60}


@dataclass(frozen=True)
class Settings:
    # Knowledge base source: the WordPress plugin's REST API, or a local JSON file.
    wp_base_url: str = ""
    wp_shared_secret: str = ""
    kb_file: str = ""
    kb_ttl_seconds: int = 60
    http_timeout_seconds: float = 5.0

    # Browser origins allowed to call the service (the WordPress site).
    allowed_origins: list[str] = field(default_factory=list)

    # FAQ matching.
    matcher: str = "embedding"  # "embedding" or "lexical"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    match_threshold: float | None = None  # None -> DEFAULT_THRESHOLDS[matcher]
    match_margin: float = 0.0
    suggest_ratio: float = 0.6  # suggestions need score >= ratio * threshold
    max_message_chars: int = 300

    # Speech recognition (E-Branchformer, via ESPnet).
    asr_enabled: bool = True
    asr_model_tag: str = "espnet/owsm_v3.1_ebf_base"
    asr_device: str = "cpu"
    asr_beam_size: int = 1
    asr_ctc_weight: float = 0.0
    asr_lang_sym: str = "<eng>"
    asr_quantize: bool = True
    asr_threads: int = 0  # 0 -> leave torch default
    asr_require_ebranchformer: bool = True
    asr_max_seconds: float = 15.0
    asr_min_seconds: float = 0.4
    asr_max_upload_bytes: int = 1_500_000

    # Abuse protection and reporting.
    rate_limit_per_minute: int = 20
    trust_proxy_headers: bool = False
    report_unanswered: bool = True

    @property
    def threshold(self) -> float:
        if self.match_threshold is not None:
            return self.match_threshold
        return DEFAULT_THRESHOLDS.get(self.matcher, 0.5)

    @property
    def kb_url(self) -> str:
        return f"{self.wp_base_url.rstrip('/')}/wp-json/org-chatbot/v1/kb" if self.wp_base_url else ""

    @property
    def unanswered_url(self) -> str:
        if not self.wp_base_url:
            return ""
        return f"{self.wp_base_url.rstrip('/')}/wp-json/org-chatbot/v1/unanswered"

    @classmethod
    def from_env(cls) -> Settings:
        raw_threshold = os.environ.get("MATCH_THRESHOLD")
        return cls(
            wp_base_url=_str("WP_BASE_URL", ""),
            wp_shared_secret=_str("WP_SHARED_SECRET", ""),
            kb_file=_str("KB_FILE", ""),
            kb_ttl_seconds=_int("KB_TTL_SECONDS", 60),
            http_timeout_seconds=_float("HTTP_TIMEOUT_SECONDS", 5.0),
            allowed_origins=_list("ALLOWED_ORIGINS", []),
            matcher=_str("MATCHER", "embedding").lower(),
            embedding_model=_str("EMBEDDING_MODEL", cls.embedding_model),
            match_threshold=float(raw_threshold) if raw_threshold not in (None, "") else None,
            match_margin=_float("MATCH_MARGIN", 0.0),
            suggest_ratio=_float("SUGGEST_RATIO", 0.6),
            max_message_chars=_int("MAX_MESSAGE_CHARS", 300),
            asr_enabled=_bool("ASR_ENABLED", True),
            asr_model_tag=_str("ASR_MODEL_TAG", cls.asr_model_tag),
            asr_device=_str("ASR_DEVICE", "cpu"),
            asr_beam_size=_int("ASR_BEAM_SIZE", 1),
            asr_ctc_weight=_float("ASR_CTC_WEIGHT", 0.0),
            asr_lang_sym=_str("ASR_LANG_SYM", "<eng>"),
            asr_quantize=_bool("ASR_QUANTIZE", True),
            asr_threads=_int("ASR_THREADS", 0),
            asr_require_ebranchformer=_bool("ASR_REQUIRE_EBRANCHFORMER", True),
            asr_max_seconds=_float("ASR_MAX_SECONDS", 15.0),
            asr_min_seconds=_float("ASR_MIN_SECONDS", 0.4),
            asr_max_upload_bytes=_int("ASR_MAX_UPLOAD_BYTES", 1_500_000),
            rate_limit_per_minute=_int("RATE_LIMIT_PER_MINUTE", 20),
            trust_proxy_headers=_bool("TRUST_PROXY_HEADERS", False),
            report_unanswered=_bool("REPORT_UNANSWERED", True),
        )

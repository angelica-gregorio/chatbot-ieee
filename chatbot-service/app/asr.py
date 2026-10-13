"""Speech recognition with an E-Branchformer encoder (ESPnet / OWSM).

Default model: ``espnet/owsm_v3.1_ebf_base`` - OWSM v3.1 base, 101M
parameters, E-Branchformer encoder with a Transformer decoder, trained on
180k hours of public speech, licence CC-BY-4.0. Any ESPnet speech-to-text
checkpoint can be swapped in with ``ASR_MODEL_TAG``; with
``ASR_REQUIRE_EBRANCHFORMER=true`` (the default) the service refuses to start
voice input unless the loaded encoder really is ``EBranchformerEncoder``.

The transcript is only used to look up the FAQ; it is never stored.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Literal

import numpy as np

from .config import Settings

log = logging.getLogger(__name__)

AsrState = Literal["disabled", "loading", "ready", "error"]
EBRANCHFORMER_CLASS = "EBranchformerEncoder"


class EBranchformerTranscriber:
    """Wraps ``espnet2.bin.s2t_inference.Speech2Text`` for one-utterance decoding."""

    def __init__(self, settings: Settings, speech2text_cls: Any = None):
        self.settings = settings
        self._speech2text_cls = speech2text_cls  # injectable for tests
        self._s2t: Any = None
        self._lock = threading.Lock()
        self.state: AsrState = "loading" if settings.asr_enabled else "disabled"
        self.error: str | None = None
        self.encoder_class: str | None = None
        self.load_seconds: float | None = None

    @property
    def ready(self) -> bool:
        return self.state == "ready"

    def info(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "model": self.settings.asr_model_tag,
            "encoder": self.encoder_class,
            "beam_size": self.settings.asr_beam_size,
            "quantized": self.settings.asr_quantize,
            "load_seconds": self.load_seconds,
            "error": self.error,
        }

    def _build(self) -> Any:
        cls = self._speech2text_cls
        if cls is None:
            import torch
            from espnet2.bin.s2t_inference import Speech2Text as cls  # noqa: N813

            if self.settings.asr_threads > 0:
                torch.set_num_threads(self.settings.asr_threads)
        return cls.from_pretrained(
            model_tag=self.settings.asr_model_tag,
            device=self.settings.asr_device,
            beam_size=self.settings.asr_beam_size,
            ctc_weight=self.settings.asr_ctc_weight,
            lang_sym=self.settings.asr_lang_sym,
            task_sym="<asr>",
            predict_time=False,
            quantize_s2t_model=self.settings.asr_quantize and self.settings.asr_device == "cpu",
        )

    def load(self) -> None:
        """Download (first run), build and warm up the model. Safe to call in a thread."""
        if not self.settings.asr_enabled:
            self.state = "disabled"
            return
        started = time.perf_counter()
        try:
            s2t = self._build()
            encoder = getattr(getattr(s2t, "s2t_model", None), "encoder", None)
            self.encoder_class = type(encoder).__name__ if encoder is not None else None
            if self.settings.asr_require_ebranchformer and self.encoder_class != EBRANCHFORMER_CLASS:
                raise RuntimeError(
                    f"{self.settings.asr_model_tag} uses {self.encoder_class}, not {EBRANCHFORMER_CLASS}. "
                    "Pick an E-Branchformer checkpoint or set ASR_REQUIRE_EBRANCHFORMER=false."
                )
            self._s2t = s2t
            self._decode(np.zeros(16_000, dtype=np.float32))  # warm-up pass
            self.load_seconds = round(time.perf_counter() - started, 2)
            self.state = "ready"
            log.info("ASR ready: %s (%s) in %.1fs", self.settings.asr_model_tag, self.encoder_class, self.load_seconds)
        except Exception as exc:
            self.state = "error"
            self.error = f"{type(exc).__name__}: {exc}"
            log.error("ASR failed to load: %s", self.error)

    def _decode(self, samples: np.ndarray) -> str:
        with self._lock:  # one decode at a time keeps CPU latency predictable
            results = self._s2t(samples)
        if isinstance(results, tuple):  # (n-best, intermediate CTC outputs)
            results = results[0]
        if not results:
            return ""
        # Each hypothesis is (text, token, token_int, text_nospecial, hyp).
        return str(results[0][3]).strip()

    def transcribe(self, samples: np.ndarray) -> str:
        if not self.ready:
            raise RuntimeError(f"ASR is not ready (state: {self.state})")
        return self._decode(samples)

"""Validation and decoding of recorded questions.

The widget records in the browser and uploads 16 kHz mono 16-bit WAV, which is
what the OWSM E-Branchformer models were trained on. Other sample rates are
resampled here. Audio is processed in memory only and never written to disk.
"""

from __future__ import annotations

import io
from math import gcd

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

TARGET_RATE = 16_000


class AudioError(ValueError):
    """Raised for uploads the service will not transcribe."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def decode_wav(data: bytes, max_bytes: int, min_seconds: float, max_seconds: float) -> np.ndarray:
    """Return float32 mono samples at 16 kHz, or raise AudioError."""
    if not data:
        raise AudioError("empty_audio", "No audio was received.")
    if len(data) > max_bytes:
        raise AudioError("audio_too_large", "The recording is too large.")
    try:
        samples, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    except (sf.LibsndfileError, RuntimeError, TypeError) as exc:
        raise AudioError("bad_audio", "The recording could not be read as WAV audio.") from exc

    mono = samples.mean(axis=1)
    if rate != TARGET_RATE:
        if rate < 8_000 or rate > 96_000:
            raise AudioError("bad_audio", "Unsupported sample rate.")
        divisor = gcd(rate, TARGET_RATE)
        mono = resample_poly(mono, TARGET_RATE // divisor, rate // divisor).astype(np.float32)

    seconds = len(mono) / TARGET_RATE
    if seconds < min_seconds:
        raise AudioError("audio_too_short", "The recording was too short. Hold the question a little longer.")
    if seconds > max_seconds:
        raise AudioError("audio_too_long", f"Please keep spoken questions under {int(max_seconds)} seconds.")
    return np.ascontiguousarray(mono, dtype=np.float32)


def rms_dbfs(samples: np.ndarray) -> float:
    if samples.size == 0:
        return float("-inf")
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    return 20.0 * np.log10(rms) if rms > 0 else float("-inf")


def is_silent(samples: np.ndarray, threshold_dbfs: float = -50.0) -> bool:
    return rms_dbfs(samples) < threshold_dbfs

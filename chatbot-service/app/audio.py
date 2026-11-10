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


FRAME = TARGET_RATE // 50  # 20 ms


def _frame_dbfs(samples: np.ndarray) -> np.ndarray:
    count = len(samples) // FRAME
    if count == 0:
        return np.empty(0)
    frames = samples[: count * FRAME].astype(np.float64).reshape(count, FRAME)
    rms = np.sqrt(np.mean(np.square(frames), axis=1))
    return 20.0 * np.log10(np.maximum(rms, 1e-10))


def trim_silence(
    samples: np.ndarray, floor_dbfs: float = -50.0, below_peak_db: float = 35.0, pad_seconds: float = 0.2
) -> np.ndarray:
    """Cut leading and trailing silence, keeping ``pad_seconds`` around the speech.

    A frame counts as speech when it is louder than both an absolute floor and
    ``below_peak_db`` under the loudest frame, so a noisy room does not count
    as speech. Long silent tails are a common cause of invented words in
    Whisper-style decoders such as OWSM. Returns the input unchanged if no
    frame qualifies (``is_silent`` deals with those).
    """
    levels = _frame_dbfs(samples)
    if levels.size == 0:
        return samples
    voiced = np.flatnonzero(levels > max(floor_dbfs, float(levels.max()) - below_peak_db))
    if voiced.size == 0:
        return samples
    pad = int(pad_seconds * TARGET_RATE)
    start = max(0, int(voiced[0]) * FRAME - pad)
    end = min(len(samples), (int(voiced[-1]) + 1) * FRAME + pad)
    return np.ascontiguousarray(samples[start:end])


def normalize_loudness(
    samples: np.ndarray, target_dbfs: float = -20.0, max_gain_db: float = 20.0, peak: float = 0.99
) -> np.ndarray:
    """Scale to ``target_dbfs`` RMS, with at most ``max_gain_db`` of boost and no clipping.

    Quiet laptop microphones are the usual case; the gain cap stops a
    near-silent recording from being amplified into loud noise.
    """
    level = rms_dbfs(samples)
    if not np.isfinite(level):
        return samples
    gain = 10.0 ** (min(target_dbfs - level, max_gain_db) / 20.0)
    top = float(np.max(np.abs(samples))) * gain
    if top > peak:
        gain *= peak / top
    return (samples * gain).astype(np.float32)


def prepare_for_asr(samples: np.ndarray, trim: bool = True, normalize: bool = True) -> np.ndarray:
    if trim:
        samples = trim_silence(samples)
    if normalize:
        samples = normalize_loudness(samples)
    return samples

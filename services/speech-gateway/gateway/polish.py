"""Per-sentence audio polish so joined sentences do not click."""

import numpy as np

FRAME_MS = 10
THRESHOLD = 0.03
PAD_BEFORE_MS = 40
PAD_AFTER_MS = 120
FADE_IN_MS = 15
FADE_OUT_MS = 120
TARGET_RMS = 0.08
PEAK_CAP = 0.95


def _fade(n: int) -> np.ndarray:
    """Raised-cosine ramp from 0 to 1 over n samples."""
    return 0.5 - 0.5 * np.cos(np.pi * np.arange(n) / max(n, 1))


def polish(audio: np.ndarray, sr: int) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32)
    frame = max(int(sr * FRAME_MS / 1000), 1)
    n_frames = len(audio) // frame
    if n_frames == 0:
        return audio
    frames = audio[: n_frames * frame].reshape(n_frames, frame)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    if rms.max() <= 0:
        return audio
    voiced = np.flatnonzero(rms >= THRESHOLD * rms.max())
    start = max(voiced[0] * frame - int(sr * PAD_BEFORE_MS / 1000), 0)
    end = min((voiced[-1] + 1) * frame + int(sr * PAD_AFTER_MS / 1000), len(audio))
    out = audio[start:end].copy()
    seg = audio[voiced[0] * frame : (voiced[-1] + 1) * frame].astype(np.float64)
    level = float(np.sqrt(np.mean(seg**2)))

    fi = min(int(sr * FADE_IN_MS / 1000), len(out))
    fo = min(int(sr * FADE_OUT_MS / 1000), len(out))
    out[:fi] *= _fade(fi)
    out[len(out) - fo :] *= _fade(fo)[::-1]

    out = out * (TARGET_RMS / level)
    peak = float(np.abs(out).max())
    if peak > PEAK_CAP:
        out = out * (PEAK_CAP / peak)
    return out.astype(np.float32)


def room_tone(sr: int, seconds: float = 0.45) -> np.ndarray:
    """Faint noise used between sentences instead of digital silence."""
    rng = np.random.default_rng(0)
    return (rng.standard_normal(int(sr * seconds)) * 0.0003).clip(-0.001, 0.001).astype(np.float32)

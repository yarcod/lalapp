import numpy as np

from gateway.polish import polish, room_tone

SR = 24000


def _clip():
    t = np.arange(int(SR * 1.0)) / SR
    tone = 0.3 * np.sin(2 * np.pi * 220 * t)
    quiet = np.zeros(int(SR * 0.5))
    return np.concatenate([quiet, tone, quiet]).astype(np.float32)


def test_polish_trims_and_fades():
    out = polish(_clip(), SR)
    assert abs(out[0]) < 1e-3 and abs(out[-1]) < 1e-3
    assert len(out) < len(_clip())
    voiced = out[int(SR * 0.2) : -int(SR * 0.2)]
    rms = float(np.sqrt(np.mean(voiced**2)))
    assert abs(rms - 0.08) / 0.08 < 0.05


def test_polish_peak_cap():
    t = np.arange(SR) / SR
    quiet = np.zeros(SR // 2)
    x = np.concatenate([quiet, 0.02 * np.sin(2 * np.pi * 220 * t), quiet]).astype(np.float32)
    x[SR] = 1.0  # single full-scale spike in the middle of low-level voiced audio
    out = polish(x, SR)
    assert abs(float(np.abs(out).max()) - 0.95) < 1e-3


def test_polish_silent_input_unchanged():
    x = np.zeros(SR, dtype=np.float32)
    out = polish(x, SR)
    assert np.array_equal(out, x)


def test_room_tone_length_and_level():
    tone = room_tone(SR)
    assert len(tone) == int(SR * 0.45)
    assert np.abs(tone).max() < 0.002

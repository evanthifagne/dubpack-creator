"""Empreintes vocales maison (numpy) — aucune dépendance lourde requise."""
from __future__ import annotations

import numpy as np

SR = 16000
_WIN = 400          # 25 ms
_HOP = 160          # 10 ms
_NFFT = 512
_NMEL = 40
_NCEP = 20


def _hz_to_mel(hz: np.ndarray | float) -> np.ndarray | float:
    return 2595.0 * np.log10(1.0 + np.asarray(hz) / 700.0)


def _mel_to_hz(mel: np.ndarray | float) -> np.ndarray | float:
    return 700.0 * (10.0 ** (np.asarray(mel) / 2595.0) - 1.0)


def _mel_filterbank(sr: int = SR, nfft: int = _NFFT, nmel: int = _NMEL,
                    fmin: float = 50.0, fmax: float = 7600.0) -> np.ndarray:
    points = _mel_to_hz(np.linspace(_hz_to_mel(fmin), _hz_to_mel(min(fmax, sr / 2)), nmel + 2))
    bins = np.floor((nfft + 1) * points / sr).astype(int)
    fb = np.zeros((nmel, nfft // 2 + 1), dtype=np.float32)
    for m in range(1, nmel + 1):
        left, center, right = bins[m - 1], bins[m], bins[m + 1]
        center = max(center, left + 1)
        right = max(right, center + 1)
        if right >= fb.shape[1]:
            break
        fb[m - 1, left:center] = (np.arange(left, center) - left) / max(center - left, 1)
        fb[m - 1, center:right] = (right - np.arange(center, right)) / max(right - center, 1)
    return fb


_FB = _mel_filterbank()
_DCT = np.array(
    [[np.cos(np.pi * k * (2 * n + 1) / (2 * _NMEL)) for n in range(_NMEL)] for k in range(_NCEP)],
    dtype=np.float32,
)


def _frame(signal: np.ndarray) -> np.ndarray:
    if signal.size < _WIN:
        signal = np.pad(signal, (0, _WIN - signal.size))
    count = 1 + (signal.size - _WIN) // _HOP
    idx = np.arange(_WIN)[None, :] + _HOP * np.arange(count)[:, None]
    return signal[idx] * np.hamming(_WIN).astype(np.float32)


def mfcc(signal: np.ndarray) -> np.ndarray:
    """Matrice MFCC (frames × coefficients)."""
    if signal.size == 0:
        return np.zeros((1, _NCEP), dtype=np.float32)
    frames = _frame(signal.astype(np.float32))
    spec = np.abs(np.fft.rfft(frames, n=_NFFT)) ** 2
    mel = np.maximum(spec @ _FB.T, 1e-10)
    return np.log(mel) @ _DCT.T


def median_f0(signal: np.ndarray, fmin: float = 60.0, fmax: float = 400.0) -> tuple[float, float]:
    """F0 médiane par autocorrélation + proportion de trames voisées."""
    if signal.size < _WIN * 2:
        return 0.0, 0.0
    frames = _frame(signal.astype(np.float32))
    lag_min, lag_max = int(SR / fmax), int(SR / fmin)
    lag_max = min(lag_max, _WIN - 1)
    if lag_max <= lag_min:
        return 0.0, 0.0
    frames = frames - frames.mean(axis=1, keepdims=True)
    energy = np.sqrt((frames ** 2).sum(axis=1)) + 1e-9
    strong = energy > np.percentile(energy, 40)
    if not strong.any():
        return 0.0, 0.0
    frames = frames[strong]
    spec = np.fft.rfft(frames, n=2 * _WIN)
    corr = np.fft.irfft(spec * np.conj(spec), n=2 * _WIN)[:, :_WIN]
    corr /= corr[:, :1] + 1e-9
    window = corr[:, lag_min:lag_max]
    best = window.argmax(axis=1) + lag_min
    peak = window.max(axis=1)
    voiced = peak > 0.35
    if voiced.sum() < 3:
        return 0.0, float(voiced.mean())
    return float(SR / np.median(best[voiced])), float(voiced.mean())


def embed(signal: np.ndarray) -> np.ndarray:
    """Vecteur descriptif d'un extrait de parole (timbre + hauteur)."""
    coeffs = mfcc(signal)
    if coeffs.shape[0] > 3:
        # On écarte les trames les plus faibles: silence et respirations.
        power = coeffs[:, 0]
        keep = power > np.percentile(power, 25)
        if keep.sum() >= 3:
            coeffs = coeffs[keep]
    mean = coeffs[:, 1:].mean(axis=0)
    std = coeffs[:, 1:].std(axis=0)
    delta = np.diff(coeffs[:, 1:], axis=0) if coeffs.shape[0] > 1 else np.zeros((1, _NCEP - 1))
    dmean = np.abs(delta).mean(axis=0)
    f0, voiced = median_f0(signal)
    pitch = np.log(f0) if f0 > 0 else 0.0
    return np.concatenate([mean, std, dmean, [pitch * 3.0, voiced]]).astype(np.float32)

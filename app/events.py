"""Détection des sons non parlés: cris, souffles, grognements, impacts.

Whisper transcrit de la parole. Tout le reste — un cri dans une bagarre, un
souffle, un coup — est soit ignoré, soit filtré par la détection d'activité
vocale. Pour un dub pack c'est une perte: le joueur doit aussi pouvoir doubler
ces sons-là.

On repère donc les passages sonores que la transcription n'a pas couverts, et on
les qualifie grossièrement à partir de leur hauteur, de leur voisement et de leur
durée. La classification n'a pas besoin d'être exacte: elle propose un libellé
que l'utilisateur corrige d'un clic.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from . import features
from .asr import Line
from .media import read_pcm

ProgressCb = Callable[[float, str], None] | None

FRAME = 320          # 20 ms à 16 kHz
MIN_DURATION = 0.18  # en dessous, c'est un clic, pas un son à doubler
MAX_DURATION = 6.0
GAP_TOLERANCE = 0.14  # deux bouffées si proches ne font qu'un seul événement
MAX_EVENTS = 60       # garde-fou: on ne noie pas la timeline

LABELS = {
    "cri": "[cri]",
    "grognement": "[grognement]",
    "souffle": "[souffle]",
    "impact": "[impact]",
    "son": "[son]",
}


def _energy_envelope(signal: np.ndarray) -> np.ndarray:
    usable = (signal.size // FRAME) * FRAME
    if usable == 0:
        return np.zeros(0, dtype=np.float32)
    frames = signal[:usable].reshape(-1, FRAME)
    return np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1)).astype(np.float32)


def _covered_mask(count: int, lines: Sequence[Line], sr: int) -> np.ndarray:
    """Trames déjà couvertes par une réplique transcrite."""
    mask = np.zeros(count, dtype=bool)
    span = FRAME / sr
    for line in lines:
        start = max(int(line.start / span) - 1, 0)
        end = min(int(line.end / span) + 2, count)
        if end > start:
            mask[start:end] = True
    return mask


def _is_percussive(chunk: np.ndarray) -> bool:
    """Attaque brutale suivie d'une extinction rapide: un coup, pas une voix.

    On teste la forme avant la hauteur: un choc grave possède assez de
    périodicité pour que la mesure de hauteur le prenne à tort pour un grognement.
    """
    envelope = _energy_envelope(chunk)
    if envelope.size < 4:
        return False
    peak = float(envelope.max())
    if peak <= 0:
        return False
    third = max(envelope.size // 3, 1)
    head = float(envelope[:third].mean())
    tail = float(envelope[-third:].mean())
    # On compare l'energie du debut a celle de la fin plutot que de chercher la
    # position du pic: un bruit de choc est irregulier et son maximum peut tomber
    # n'importe ou dans l'attaque.
    decays = head >= tail * 2.2
    return decays and tail < peak * 0.4


def _classify(chunk: np.ndarray, duration: float, loudness: float,
              speech_level: float) -> str:
    if duration <= 0.6 and _is_percussive(chunk):
        return "impact"
    f0, voiced = features.median_f0(chunk)
    if voiced > 0.42 and f0 >= 260:
        return "cri"
    if voiced > 0.32 and f0 > 0:
        return "grognement"
    if duration >= 0.4:
        return "souffle"
    return "son"


def detect_nonverbal(audio: Path, lines: Sequence[Line], sr: int = 16000,
                     sensitivity: float = 1.0,
                     cb: ProgressCb = None) -> list[Line]:
    """Répliques supplémentaires pour les sons non parlés.

    `sensitivity` autour de 1.0: au-delà on capte des sons plus discrets, en
    dessous on ne garde que les plus francs.
    """
    signal = read_pcm(audio, sr=sr)
    envelope = _energy_envelope(signal)
    if envelope.size < 5:
        return []

    span = FRAME / sr
    covered = _covered_mask(envelope.size, lines, sr)

    # Repères: le fond sonore, et le niveau de la parole déjà transcrite.
    floor = float(np.percentile(envelope, 20)) or 1e-6
    speech = envelope[covered]
    speech_level = float(np.median(speech)) if speech.size > 10 else float(np.percentile(envelope, 80))
    speech_level = max(speech_level, floor * 2)
    threshold = max(floor * 3.0, speech_level * 0.18) / max(sensitivity, 0.2)

    candidate = (envelope > threshold) & ~covered
    if not candidate.any():
        return []

    # Regroupement des trames retenues en événements continus.
    events: list[tuple[int, int]] = []
    gap_frames = max(int(GAP_TOLERANCE / span), 1)
    start = None
    silence = 0
    for index, active in enumerate(candidate):
        if active:
            if start is None:
                start = index
            silence = 0
        elif start is not None:
            silence += 1
            if silence > gap_frames:
                events.append((start, index - silence + 1))
                start = None
    if start is not None:
        events.append((start, candidate.size))

    out: list[Line] = []
    for first, last in events:
        begin, end = first * span, last * span
        duration = end - begin
        if duration < MIN_DURATION:
            continue
        if duration > MAX_DURATION:
            end = begin + MAX_DURATION
            duration = MAX_DURATION
        chunk = signal[int(begin * sr):int(end * sr)]
        if chunk.size < FRAME:
            continue
        loudness = float(np.sqrt((chunk.astype(np.float64) ** 2).mean()))
        kind = _classify(chunk, duration, loudness, speech_level)
        line = Line(start=round(begin, 3), end=round(end, 3),
                    text=LABELS.get(kind, "[son]"), confidence=0.0)
        # Marquage: l'appelant doit pouvoir les distinguer de la parole.
        line.nonverbal = True          # type: ignore[attr-defined]
        line.kind = kind               # type: ignore[attr-defined]
        line.loudness = loudness       # type: ignore[attr-defined]
        out.append(line)

    # On privilégie les sons les plus francs si le compte explose.
    if len(out) > MAX_EVENTS:
        out.sort(key=lambda l: getattr(l, "loudness", 0.0), reverse=True)
        out = out[:MAX_EVENTS]
    out.sort(key=lambda l: l.start)
    if cb:
        cb(1.0, f"{len(out)} son(s) non parlé(s) repéré(s)")
    return out

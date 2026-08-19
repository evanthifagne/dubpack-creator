"""Transcription locale + découpage en répliques."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import CACHE_DIR, module_available

ProgressCb = Callable[[float, str], None] | None

# Les modèles restent dans le dossier de l'appli: pas de surprise dans le HOME.
os.environ.setdefault("HF_HOME", str(CACHE_DIR / "models"))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(CACHE_DIR / "models"))


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Line:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    speaker: str | None = None
    confidence: float = 1.0


# Poids approximatifs, pour prevenir avant un long telechargement.
MODEL_SIZES = {
    "tiny": "75 Mo", "base": "145 Mo", "small": "480 Mo",
    "medium": "1,5 Go", "large-v3": "3 Go", "large-v3-turbo": "1,6 Go",
}


def model_cached(model_name: str) -> bool:
    """Le modèle est-il déjà téléchargé ?

    Sert à annoncer honnêtement l'attente: le premier chargement télécharge
    plusieurs centaines de Mo, les suivants sont quasi instantanés.
    """
    root = CACHE_DIR / "models"
    if not root.is_dir():
        return False
    needle = model_name.replace(".", "").lower()
    for entry in root.iterdir():
        name = entry.name.lower()
        if not entry.is_dir() or "whisper" not in name:
            continue
        if name.endswith(needle) or f"-{needle}" in name or needle in name:
            # Un dossier de snapshot vide signifie un telechargement interrompu.
            if any(entry.rglob("*.bin")) or any(entry.rglob("*.safetensors")):
                return True
    return False


def loading_label(model_name: str) -> str:
    if model_cached(model_name):
        return f"Chargement du modèle « {model_name} »"
    size = MODEL_SIZES.get(model_name, "plusieurs centaines de Mo")
    return f"Téléchargement du modèle « {model_name} » ({size}, une seule fois)"


def available_engines() -> list[str]:
    engines = []
    if module_available("faster_whisper"):
        engines.append("faster-whisper")
    if module_available("mlx_whisper"):
        engines.append("mlx-whisper")
    if module_available("parakeet_mlx"):
        engines.append("parakeet-mlx")
    if module_available("whisper"):
        engines.append("openai-whisper")
    return engines


def pick_engine(requested: str | None = None) -> str:
    engines = available_engines()
    if not engines:
        raise RuntimeError(
            "Aucun moteur de transcription installé. Lance: pip install faster-whisper"
        )
    if requested and requested in engines:
        return requested
    return engines[0]


# ---------------------------------------------------------------------------
# Moteurs
# ---------------------------------------------------------------------------

def _transcribe_faster_whisper(audio: Path, model_name: str, language: str | None,
                               duration: float, cb: ProgressCb) -> tuple[list[Line], str]:
    from faster_whisper import WhisperModel

    if cb:
        cb(0.02, loading_label(model_name))
    # int8 sur CPU: le meilleur compromis vitesse/qualité sur Windows comme sur Mac.
    model = WhisperModel(model_name, device="auto", compute_type="int8",
                         download_root=str(CACHE_DIR / "models"))
    segments, info = model.transcribe(
        str(audio),
        language=language or None,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 350},
        beam_size=5,
        condition_on_previous_text=False,
    )
    total = duration or getattr(info, "duration", 0.0) or 0.0
    lines: list[Line] = []
    for seg in segments:
        words = [
            Word(start=float(w.start), end=float(w.end), text=w.word)
            for w in (seg.words or []) if w.start is not None and w.end is not None
        ]
        lines.append(Line(
            start=float(seg.start), end=float(seg.end), text=(seg.text or "").strip(),
            words=words, confidence=float(getattr(seg, "avg_logprob", 0.0) or 0.0),
        ))
        # Appel systematique: c'est aussi notre point de controle d'annulation.
        if cb:
            fraction = min(float(seg.end) / total, 0.99) if total else 0.5
            cb(fraction, "Transcription en cours")
    return lines, (getattr(info, "language", None) or language or "")


def _transcribe_mlx_whisper(audio: Path, model_name: str, language: str | None,
                            duration: float, cb: ProgressCb) -> tuple[list[Line], str]:
    import mlx_whisper

    repo = {
        "tiny": "mlx-community/whisper-tiny",
        "base": "mlx-community/whisper-base-mlx",
        "small": "mlx-community/whisper-small-mlx",
        "medium": "mlx-community/whisper-medium-mlx",
        "large-v3": "mlx-community/whisper-large-v3-mlx",
        "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    }.get(model_name, "mlx-community/whisper-small-mlx")
    if cb:
        cb(0.05, f"Transcription MLX ({model_name})")
    result = mlx_whisper.transcribe(
        str(audio), path_or_hf_repo=repo, word_timestamps=True,
        language=language or None,
    )
    lines = []
    for seg in result.get("segments", []):
        words = [
            Word(start=float(w["start"]), end=float(w["end"]), text=w.get("word", ""))
            for w in seg.get("words", []) or []
        ]
        lines.append(Line(start=float(seg["start"]), end=float(seg["end"]),
                          text=(seg.get("text") or "").strip(), words=words))
    return lines, result.get("language") or language or ""


def _transcribe_openai_whisper(audio: Path, model_name: str, language: str | None,
                               duration: float, cb: ProgressCb) -> tuple[list[Line], str]:
    import whisper

    if cb:
        cb(0.05, loading_label(model_name))
    model = whisper.load_model(model_name, download_root=str(CACHE_DIR / "models"))
    result = model.transcribe(str(audio), word_timestamps=True, language=language or None)
    lines = []
    for seg in result.get("segments", []):
        words = [
            Word(start=float(w["start"]), end=float(w["end"]), text=w.get("word", ""))
            for w in seg.get("words", []) or []
        ]
        lines.append(Line(start=float(seg["start"]), end=float(seg["end"]),
                          text=(seg.get("text") or "").strip(), words=words))
    return lines, result.get("language") or language or ""


def _transcribe_parakeet(audio: Path, model_name: str, language: str | None,
                         duration: float, cb: ProgressCb) -> tuple[list[Line], str]:
    from parakeet_mlx import from_pretrained

    if cb:
        cb(0.05, "Transcription Parakeet (anglais)")
    model = from_pretrained("mlx-community/parakeet-tdt-0.6b-v2")
    result = model.transcribe(str(audio))
    lines = []
    for seg in getattr(result, "sentences", []) or []:
        words = [
            Word(start=float(t.start), end=float(t.end), text=t.text)
            for t in (getattr(seg, "tokens", None) or [])
        ]
        lines.append(Line(start=float(seg.start), end=float(seg.end),
                          text=(seg.text or "").strip(), words=words))
    return lines, "en"


_ENGINES = {
    "faster-whisper": _transcribe_faster_whisper,
    "mlx-whisper": _transcribe_mlx_whisper,
    "openai-whisper": _transcribe_openai_whisper,
    "parakeet-mlx": _transcribe_parakeet,
}


def transcribe(audio: Path, model_name: str = "small", language: str | None = None,
               engine: str | None = None, duration: float = 0.0,
               cb: ProgressCb = None) -> tuple[list[Line], str, str]:
    """Retourne (répliques brutes, langue détectée, moteur utilisé)."""
    chosen = pick_engine(engine)
    lines, lang = _ENGINES[chosen](audio, model_name, language, duration, cb)
    lines = [ln for ln in lines if ln.text and ln.end > ln.start]
    if cb:
        cb(1.0, f"{len(lines)} segments transcrits")
    return lines, lang, chosen


# ---------------------------------------------------------------------------
# Découpage en répliques jouables
# ---------------------------------------------------------------------------

_SENTENCE_END = re.compile(r"[.!?…]+[\"'»)\]]*$")
_CLAUSE_END = re.compile(r"[,;:]$")


def split_lines(lines: list[Line], max_dur: float = 9.0, min_dur: float = 0.35,
                pause: float = 0.45) -> list[Line]:
    """Recoupe les segments Whisper en répliques courtes, calées sur les mots.

    Un dub pack se joue réplique par réplique: on coupe à la ponctuation forte,
    aux silences et au-delà d'une durée maximale, en s'appuyant sur les
    timestamps par mot pour que les bornes tombent juste.
    """
    out: list[Line] = []
    for seg in lines:
        if not seg.words or (seg.end - seg.start) <= max_dur and _fits(seg, max_dur):
            if (seg.end - seg.start) <= max_dur:
                out.append(seg)
                continue
        if not seg.words:
            out.extend(_split_blind(seg, max_dur))
            continue

        current: list[Word] = []
        for idx, word in enumerate(seg.words):
            if current:
                gap = word.start - current[-1].end
                span = word.end - current[0].start
                token = current[-1].text.strip()
                cut = (
                    (_SENTENCE_END.search(token) and gap >= 0.12)
                    or gap >= pause
                    or span > max_dur
                    or (_CLAUSE_END.search(token) and gap >= pause * 0.7 and span > max_dur * 0.5)
                )
                if cut:
                    out.append(_line_from_words(current, seg.confidence))
                    current = []
            current.append(word)
        if current:
            out.append(_line_from_words(current, seg.confidence))

    # Recolle les fragments trop courts sur le voisin le plus proche.
    merged: list[Line] = []
    for line in out:
        if merged and (line.end - line.start) < min_dur and (line.end - merged[-1].start) <= max_dur:
            prev = merged[-1]
            prev.end = line.end
            prev.text = f"{prev.text} {line.text}".strip()
            prev.words += line.words
        else:
            merged.append(line)
    return [ln for ln in merged if ln.text.strip()]


def _fits(seg: Line, max_dur: float) -> bool:
    return (seg.end - seg.start) <= max_dur


def _line_from_words(words: list[Word], confidence: float) -> Line:
    text = "".join(w.text for w in words).strip()
    text = re.sub(r"\s+", " ", text)
    return Line(start=round(words[0].start, 3), end=round(words[-1].end, 3),
                text=text, words=list(words), confidence=confidence)


def _split_blind(seg: Line, max_dur: float) -> list[Line]:
    """Segment trop long sans timestamps par mot: découpage proportionnel au texte."""
    parts = [p for p in re.split(r"(?<=[.!?…])\s+", seg.text) if p.strip()] or [seg.text]
    total_chars = sum(len(p) for p in parts) or 1
    out, cursor = [], seg.start
    span = seg.end - seg.start
    for part in parts:
        dur = span * len(part) / total_chars
        out.append(Line(start=round(cursor, 3), end=round(min(cursor + dur, seg.end), 3),
                        text=part.strip(), confidence=seg.confidence))
        cursor += dur
    return out

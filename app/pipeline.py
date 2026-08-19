"""Enchaînement complet: source → audio → transcription → personnages → projet."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Callable

from . import asr, characters, diarize, dubpack, events, media, sources
from .config import DEFAULT_MODEL

ProgressCb = Callable[[float, str], None]


def _scaled(cb: ProgressCb, lo: float, hi: float) -> ProgressCb:
    """Ramène la progression d'une étape dans la tranche [lo, hi] du job global."""
    def inner(frac: float, label: str = "") -> None:
        cb(lo + (hi - lo) * max(0.0, min(frac, 1.0)), label)
    return inner


def ingest(project: dict, url: str | None, file_path: Path | None,
           cb: ProgressCb) -> dict:
    """Récupère la vidéo, en extrait l'audio de travail et la forme d'onde."""
    folder = dubpack.project_dir(project["id"])
    folder.mkdir(parents=True, exist_ok=True)

    if url:
        video, meta = sources.download_url(url, folder, cb=_scaled(cb, 0.0, 0.55))
    elif file_path:
        video, meta = sources.adopt_file(file_path, folder, cb=_scaled(cb, 0.0, 0.15))
    else:
        raise RuntimeError("Il faut un lien vidéo ou un fichier.")

    info = media.probe(video)
    if not info.get("has_audio"):
        raise RuntimeError("Cette source n'a pas de piste audio: impossible de transcrire.")

    cb(0.6, "Extraction de la piste audio")
    audio = media.extract_audio(video, folder / "audio16k.wav", sr=16000, mono=True,
                                cb=_scaled(cb, 0.6, 0.8))

    cb(0.82, "Calcul de la forme d'onde")
    peaks = media.waveform_peaks(audio, buckets=2400)
    (folder / "waveform.json").write_text(json.dumps(peaks), encoding="utf-8")

    cb(0.92, "Vignette")
    thumb = media.extract_thumbnail(video, folder / "thumb.png", at=min(2.0, info["duration"] / 2))

    if not project.get("name") or project["name"] == "Dub Pack":
        project["name"] = meta.get("title") or "Dub Pack"
        project["pack"]["title"] = project["name"]
    project["source"] = {
        "file": str(video),
        "audio": str(audio),
        "url": meta.get("webpage_url", ""),
        "title": meta.get("title", ""),
        "uploader": meta.get("uploader", ""),
        **info,
    }
    project["assets"] = {**project.get("assets", {}),
                         "thumbnail": str(thumb) if thumb else None}
    if not project["pack"].get("subtitle") and meta.get("uploader"):
        project["pack"]["subtitle"] = f"D'après {meta['uploader']}"
    cb(1.0, "Source prête")
    return project


def analyze(project: dict, cb: ProgressCb, model: str = DEFAULT_MODEL,
            language: str | None = None, engine: str | None = None,
            speakers: int | None = None, max_line: float = 9.0,
            use_embeddings: bool = True, keep_edits: bool = False,
            detect_sounds: bool = True, sound_sensitivity: float = 1.0) -> dict:
    """Transcrit, découpe en répliques et regroupe les voix par personnage."""
    folder = dubpack.project_dir(project["id"])
    audio = Path(project["source"]["audio"])
    if not audio.exists():
        audio = media.extract_audio(project["source"]["file"], folder / "audio16k.wav")

    duration = float(project["source"].get("duration") or 0.0)
    cb(0.02, asr.loading_label(model))
    raw, detected, used_engine = asr.transcribe(
        audio, model_name=model, language=language, engine=engine,
        duration=duration, cb=_scaled(cb, 0.03, 0.72),
    )
    if not raw:
        raise RuntimeError(
            "Aucune parole détectée. Vérifie que la vidéo contient bien des dialogues, "
            "ou essaie un modèle plus grand."
        )

    cb(0.74, "Découpage en répliques")
    lines = asr.split_lines(raw, max_dur=max_line)

    sounds: list[asr.Line] = []
    if detect_sounds:
        cb(0.76, "Recherche des sons non parlés")
        sounds = events.detect_nonverbal(audio, lines, sensitivity=sound_sensitivity)
        if sounds:
            lines = sorted([*lines, *sounds], key=lambda l: l.start)

    cb(0.78, "Analyse des voix")
    diag = diarize.assign_speakers(
        audio, lines, forced=speakers, use_embeddings=use_embeddings,
        cb=_scaled(cb, 0.78, 0.95),
    )

    cb(0.96, "Détection des noms de personnages")
    suggestions = characters.suggest_names(lines)
    auto_names = characters.auto_assign(lines, diag["speakers"], suggestions)

    previous = project.get("characters", []) if keep_edits else []
    chars = dubpack.build_characters(diag["speakers"], previous)
    for char in chars:
        if char["id"] in auto_names and char["name"] == char["id"]:
            char["name"] = auto_names[char["id"]]

    project["characters"] = chars
    project["lines"] = [
        {
            "id": uuid.uuid4().hex[:10],
            "start": round(line.start, 3),
            "end": round(line.end, 3),
            "text": line.text,
            "speaker": line.speaker,
            "enabled": True,
            "tags": ([getattr(line, "kind")] if getattr(line, "nonverbal", False) else []),
            "dub_only": False,
            "confidence": round(float(line.confidence), 3),
            "nonverbal": bool(getattr(line, "nonverbal", False)),
            "kind": getattr(line, "kind", None),
        }
        for line in lines
    ]
    project["asr"] = {
        "engine": used_engine,
        "model": model,
        "language": detected or language or "",
        "diarization": diag["method"],
        "quality": diag["quality"],
        "max_line": max_line,
        "sounds_detected": len(sounds),
    }
    project["suggestions"] = suggestions
    cb(1.0, f"{len(lines)} répliques, {len(chars)} personnage(s)")
    return project

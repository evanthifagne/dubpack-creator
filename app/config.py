"""Chemins, réglages et découverte des binaires externes."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = ROOT / "projects"
WEB_DIR = ROOT / "web"
BIN_DIR = ROOT / "bin"
CACHE_DIR = ROOT / ".cache"

PROJECTS_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

# Modèles Whisper proposés dans l'UI (du plus rapide au plus précis).
WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]
DEFAULT_MODEL = "small"

# Extensions vidéo/audio acceptées à l'import.
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".ogv", ".flv", ".wmv"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus"}


def _candidates(name: str) -> list[Path]:
    exe = f"{name}.exe" if os.name == "nt" else name
    out = [BIN_DIR / exe]
    found = shutil.which(name)
    if found:
        out.append(Path(found))
    return out


@lru_cache(maxsize=8)
def _resolve_tool(name: str) -> str | None:
    for cand in _candidates(name):
        if cand.exists():
            return str(cand)
    return None


@lru_cache(maxsize=1)
def ffmpeg_path() -> str:
    """ffmpeg local: bin/, PATH, puis la roue imageio-ffmpeg (pip)."""
    found = _resolve_tool("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - dépend de l'install
        raise RuntimeError(
            "ffmpeg est introuvable. Installe-le (macOS: `brew install ffmpeg`, "
            "Windows: https://www.gyan.dev/ffmpeg/builds/) ou place le binaire dans le dossier bin/."
        ) from exc


@lru_cache(maxsize=1)
def ffprobe_path() -> str | None:
    """ffprobe est pratique mais optionnel (fallback: parsing de la sortie ffmpeg)."""
    found = _resolve_tool("ffprobe")
    if found:
        return found
    # imageio-ffmpeg ne fournit pas ffprobe: on tente à côté du ffmpeg résolu.
    sibling = Path(ffmpeg_path()).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    return str(sibling) if sibling.exists() else None


@lru_cache(maxsize=1)
def ffmpeg_encoders() -> set[str]:
    try:
        out = subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except Exception:
        return set()
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6:
            names.add(parts[1])
    return names


def has_encoder(name: str) -> bool:
    enc = ffmpeg_encoders()
    return name in enc if enc else True  # en cas de doute, on laisse ffmpeg trancher


@lru_cache(maxsize=1)
def yt_dlp_available() -> bool:
    if _resolve_tool("yt-dlp"):
        return True
    try:
        import yt_dlp  # noqa: F401

        return True
    except Exception:
        return False


def yt_dlp_command() -> list[str]:
    exe = _resolve_tool("yt-dlp")
    if exe:
        return [exe]
    return [sys.executable, "-m", "yt_dlp"]


def module_available(mod: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def capabilities() -> dict:
    """Résumé de l'environnement, affiché dans l'UI (bandeau de diagnostic)."""
    try:
        ff = ffmpeg_path()
        ff_err = None
    except RuntimeError as exc:
        ff, ff_err = None, str(exc)
    engines = []
    if module_available("faster_whisper"):
        engines.append("faster-whisper")
    if module_available("mlx_whisper"):
        engines.append("mlx-whisper")
    if module_available("whisper"):
        engines.append("openai-whisper")
    if module_available("nemo") or module_available("parakeet_mlx"):
        engines.append("parakeet")
    return {
        "ffmpeg": ff,
        "ffmpeg_error": ff_err,
        "ffprobe": ffprobe_path() if ff else None,
        "theora": has_encoder("libtheora") if ff else False,
        "vorbis": has_encoder("libvorbis") if ff else False,
        "yt_dlp": yt_dlp_available(),
        "asr_engines": engines,
        "demucs": module_available("demucs"),
        "embeddings": module_available("speechbrain"),
        "models": WHISPER_MODELS,
        "default_model": DEFAULT_MODEL,
        "platform": sys.platform,
    }

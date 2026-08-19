"""Récupération de la vidéo source: lien (yt-dlp) ou fichier local."""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Callable

from .config import VIDEO_EXTS, AUDIO_EXTS, configure_environment, ffmpeg_dir

ProgressCb = Callable[[float, str], None] | None

_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_name(name: str, fallback: str = "clip") -> str:
    """Nom de fichier sûr pour Windows et macOS."""
    name = _SAFE.sub("", (name or "").strip()).strip(" .")
    name = re.sub(r"\s+", " ", name)
    return name[:80] or fallback


def is_url(text: str) -> bool:
    return bool(re.match(r"^https?://", (text or "").strip(), re.I))


def download_url(url: str, dest_dir: Path, cb: ProgressCb = None,
                 max_height: int = 1080) -> tuple[Path, dict]:
    """Télécharge la vidéo la mieux notée en MP4 et renvoie (fichier, métadonnées)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("yt-dlp n'est pas installé (pip install yt-dlp).") from exc

    def hook(status: dict) -> None:
        if not cb:
            return
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes") or 0
            frac = (done / total) if total else 0.0
            cb(min(frac, 0.99), "Téléchargement de la vidéo")
        elif status.get("status") == "finished":
            cb(1.0, "Téléchargement terminé")

    # yt-dlp doit fusionner les pistes video et audio: il lui faut ffmpeg, et il
    # ne le cherche que dans le PATH. On le lui indique explicitement.
    configure_environment()
    ffmpeg_home = ffmpeg_dir()

    opts = {
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "format": (
            f"bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best"
        ),
        "merge_output_format": "mp4",
        "progress_hooks": [hook],
        "noprogress": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "restrictfilenames": True,
        "overwrites": True,
    }
    if ffmpeg_home:
        opts["ffmpeg_location"] = ffmpeg_home
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    files = sorted(dest_dir.glob("source.*"), key=lambda p: p.stat().st_size, reverse=True)
    files = [f for f in files if f.suffix.lower() in VIDEO_EXTS | AUDIO_EXTS]
    if not files:
        raise RuntimeError("Le téléchargement n'a produit aucun fichier vidéo exploitable.")
    meta = {
        "title": info.get("title") or "Dub Pack",
        "uploader": info.get("uploader") or info.get("channel") or "",
        "webpage_url": info.get("webpage_url") or url,
        "duration": info.get("duration") or 0,
    }
    return files[0], meta


def adopt_file(src: Path, dest_dir: Path, cb: ProgressCb = None) -> tuple[Path, dict]:
    """Copie un fichier déjà présent sur le disque dans le dossier du projet."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower()
    if ext not in VIDEO_EXTS | AUDIO_EXTS:
        raise RuntimeError(f"Format non pris en charge: {ext or 'inconnu'}")
    dst = dest_dir / f"source{ext}"
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    if cb:
        cb(1.0, "Fichier importé")
    return dst, {"title": safe_name(src.stem, "Dub Pack"), "uploader": "", "webpage_url": "", "duration": 0}

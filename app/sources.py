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


def yt_dlp_version() -> str | None:
    try:
        import yt_dlp

        return getattr(yt_dlp.version, "__version__", None)
    except Exception:
        return None


# Messages YouTube courants, et ce qu'il faut en dire à l'utilisateur.
_KNOWN_CAUSES = [
    ("sign in to confirm", "YouTube demande une connexion pour prouver que tu n'es pas un robot."),
    ("confirm you're not a bot", "YouTube demande une connexion pour prouver que tu n'es pas un robot."),
    ("age", "La vidéo est soumise à une vérification d'âge."),
    ("private video", "La vidéo est privée."),
    ("members-only", "La vidéo est réservée aux membres de la chaîne."),
    ("unavailable", "La vidéo est indisponible (retirée, ou bloquée dans ton pays)."),
    ("geo", "La vidéo est bloquée dans ton pays."),
    ("nsig", "yt-dlp est dépassé par une modification de YouTube: il faut le mettre à jour."),
    ("player response", "yt-dlp est dépassé par une modification de YouTube: il faut le mettre à jour."),
    ("precondition check", "yt-dlp est dépassé par une modification de YouTube: il faut le mettre à jour."),
    ("http error 403", "Acces refuse par YouTube: yt-dlp est probablement a mettre a jour."),
]


def _explain(message: str) -> str | None:
    lowered = (message or "").lower()
    for needle, explanation in _KNOWN_CAUSES:
        if needle in lowered:
            return explanation
    return None


def _strategies(max_height: int) -> list[tuple[str, dict]]:
    """Tentatives successives, de la plus simple à la plus contournante.

    YouTube change souvent et bloque volontiers les téléchargements. Plutôt que
    d'abandonner au premier refus, on réessaie en changeant de client interne,
    puis en empruntant les cookies du navigateur (ce qui règle le fameux
    « connecte-toi pour prouver que tu n'es pas un robot »), puis en renonçant à
    la fusion des pistes.
    """
    best = (f"bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best")
    out: list[tuple[str, dict]] = [
        ("standard", {"format": best}),
        ("clients alternatifs", {
            "format": best,
            "extractor_args": {"youtube": {"player_client": ["tv", "android", "ios", "web"]}},
        }),
    ]
    for browser in ("chrome", "edge", "firefox", "brave"):
        out.append((f"cookies {browser}", {
            "format": best,
            "cookiesfrombrowser": (browser,),
        }))
    out.append(("format unique, sans fusion", {"format": f"best[height<={max_height}]/best"}))
    return out


def download_url(url: str, dest_dir: Path, cb: ProgressCb = None,
                 max_height: int = 1080) -> tuple[Path, dict]:
    """Télécharge la vidéo et renvoie (fichier, métadonnées).

    Enchaîne plusieurs stratégies: YouTube refuse régulièrement la première.
    """
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
            cb(1.0, "Assemblage de la vidéo")

    # yt-dlp doit fusionner les pistes video et audio: il lui faut ffmpeg, et il
    # ne le cherche que dans le PATH. On le lui indique explicitement.
    configure_environment()
    ffmpeg_home = ffmpeg_dir()

    base = {
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "merge_output_format": "mp4",
        "progress_hooks": [hook],
        "noprogress": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "restrictfilenames": True,
        "overwrites": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
    }
    if ffmpeg_home:
        base["ffmpeg_location"] = ffmpeg_home

    attempts: list[str] = []
    info = None
    strategies = _strategies(max_height)

    for index, (label, extra) in enumerate(strategies, start=1):
        for stale in dest_dir.glob("source.*"):
            stale.unlink(missing_ok=True)
        if cb:
            cb(0.0, f"Téléchargement ({label})" if index > 1 else "Téléchargement de la vidéo")
        try:
            with yt_dlp.YoutubeDL({**base, **extra}) as ydl:
                info = ydl.extract_info(url, download=True)
            if _collect(dest_dir):
                break
            attempts.append(f"{label}: aucun fichier produit")
            info = None
        except Exception as exc:
            message = _clean(str(exc))
            attempts.append(f"{label}: {message}")
            # Une vidéo privée ou supprimée ne s'obtiendra par aucune ruse.
            if any(k in message.lower() for k in ("private video", "members-only", "removed")):
                break
            info = None

    files = _collect(dest_dir)
    if not files or info is None:
        raise RuntimeError(_failure_message(attempts))

    meta = {
        "title": info.get("title") or "Dub Pack",
        "uploader": info.get("uploader") or info.get("channel") or "",
        "webpage_url": info.get("webpage_url") or url,
        "duration": info.get("duration") or 0,
    }
    return files[0], meta


def _collect(dest_dir: Path) -> list[Path]:
    """Fichiers exploitables produits par le téléchargement, le plus gros d'abord."""
    found = [f for f in dest_dir.glob("source*")
             if f.is_file() and f.suffix.lower() in VIDEO_EXTS | AUDIO_EXTS]
    return sorted(found, key=lambda p: p.stat().st_size, reverse=True)


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\[[0-9];[0-9]{2}m")


def _clean(text: str) -> str:
    text = _ANSI.sub("", text or "").strip()
    return text.replace("ERROR: ", "").strip()


def _failure_message(attempts: list[str]) -> str:
    """Message d'echec qui explique la cause probable et l'action a mener."""
    cause = next((_explain(a) for a in attempts if _explain(a)), None)
    version = yt_dlp_version() or "inconnue"
    lines = ["Impossible de télécharger cette vidéo."]
    if cause:
        lines.append(cause)
    lines.append(
        "Pistes, dans l'ordre: 1) mets yt-dlp à jour depuis le panneau Diagnostic "
        "(YouTube change souvent, c'est la cause la plus fréquente); "
        "2) connecte-toi à YouTube dans Chrome, Edge ou Firefox puis réessaie "
        "(l'outil emprunte les cookies du navigateur); "
        "3) télécharge la vidéo en .mp4 par tes propres moyens et dépose le fichier."
    )
    lines.append(f"yt-dlp installé: {version}.")
    if attempts:
        lines.append("Détail des tentatives — " + " | ".join(attempts[-4:]))
    return " ".join(lines)


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

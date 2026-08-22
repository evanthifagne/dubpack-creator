"""Mise à jour automatique depuis les releases GitHub.

Principe: le serveur ne remplace jamais son propre code. Il télécharge
l'archive `update-code.zip` de la dernière release, vérifie son empreinte
SHA-256, la dépose dans `update/pending/`, puis s'arrête avec le code de
sortie 42. Le superviseur (run.py ou le lanceur natif) fait alors l'échange —
sauvegarde de l'ancien code, mise en place du nouveau — et redémarre le
serveur. Les projets, modèles et réglages ne sont jamais touchés.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from . import __version__
from .config import UPDATE_DIR

ProgressCb = Callable[[float, str], None] | None

REPO = os.environ.get("DUBPACK_UPDATE_REPO", "evanthifagne/dubpack-creator")
# Point d'entrée substituable: indispensable pour tester la chaîne complète
# sans publier de vraie release.
API_URL = os.environ.get("DUBPACK_UPDATE_API",
                         f"https://api.github.com/repos/{REPO}/releases/latest")
ASSET_NAME = "update-code.zip"
CHECK_EVERY = 6 * 3600          # au plus une interrogation de GitHub par tranche
_CHECK_FILE = UPDATE_DIR / "check.json"
_PENDING_DIR = UPDATE_DIR / "pending"
_PENDING_INFO = UPDATE_DIR / "pending.json"

# Code de sortie convenu avec le superviseur: « applique la mise à jour
# en attente puis redémarre-moi ».
RESTART_EXIT_CODE = 42

_lock = threading.Lock()


def parse_version(text: str) -> tuple[int, ...]:
    found = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in found[:4]) or (0,)


def is_newer(candidate: str, reference: str) -> bool:
    return parse_version(candidate) > parse_version(reference)


def supervised() -> bool:
    """Un superviseur relancera-t-il le serveur après un exit 42 ?"""
    return os.environ.get("DUBPACK_SUPERVISED") == "1"


def _request(url: str, timeout: int = 15) -> urllib.request.Request:
    return urllib.request.Request(url, headers={
        "User-Agent": f"DubPackCreator/{__version__}",
        "Accept": "application/vnd.github+json",
    })


def _load_cached() -> dict | None:
    try:
        data = json.loads(_CHECK_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def check(force: bool = False) -> dict:
    """Interroge GitHub (au plus toutes les 6 h) et renvoie l'état des versions."""
    with _lock:
        cached = _load_cached()
        fresh_enough = cached and (time.time() - cached.get("checked_at", 0)) < CHECK_EVERY
        if not force and fresh_enough:
            return status()
        try:
            with urllib.request.urlopen(_request(API_URL), timeout=15) as response:
                release = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            # Hors ligne ou GitHub injoignable: on garde la dernière réponse
            # connue au lieu d'afficher une erreur pour une simple vérification.
            result = status()
            result["check_error"] = str(exc)[:200]
            return result

        assets = {a.get("name"): a for a in release.get("assets", [])}
        asset = assets.get(ASSET_NAME) or {}
        checksum = assets.get(ASSET_NAME + ".sha256") or {}
        info = {
            "checked_at": time.time(),
            "latest": (release.get("tag_name") or "").lstrip("v"),
            "title": release.get("name") or "",
            "notes": (release.get("body") or "")[:4000],
            "published_at": release.get("published_at") or "",
            "page": release.get("html_url") or f"https://github.com/{REPO}/releases",
            "asset_url": asset.get("browser_download_url"),
            "asset_size": asset.get("size") or 0,
            "checksum_url": checksum.get("browser_download_url"),
        }
        UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        _CHECK_FILE.write_text(json.dumps(info, ensure_ascii=False, indent=1),
                               encoding="utf-8")
        return status()


def pending_version() -> str | None:
    try:
        data = json.loads(_PENDING_INFO.read_text(encoding="utf-8"))
        version = data.get("version")
        return version if _PENDING_DIR.is_dir() else None
    except (OSError, ValueError):
        return None


def status() -> dict:
    """État courant, sans appel réseau: sert à l'affichage de l'interface."""
    cached = _load_cached() or {}
    latest = cached.get("latest") or ""
    return {
        "current": __version__,
        "latest": latest or None,
        "available": bool(latest and is_newer(latest, __version__)),
        "notes": cached.get("notes") or "",
        "title": cached.get("title") or "",
        "published_at": cached.get("published_at") or "",
        "page": cached.get("page") or f"https://github.com/{REPO}/releases",
        "checked_at": cached.get("checked_at"),
        "asset_size": cached.get("asset_size") or 0,
        "downloadable": bool(cached.get("asset_url")),
        "pending": pending_version(),
        "supervised": supervised(),
        "repo": REPO,
    }


def _download(url: str, dest: Path, expected_size: int, progress: ProgressCb,
              label: str) -> None:
    from . import cancel

    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(_request(url), timeout=60) as response:
        total = int(response.headers.get("Content-Length") or expected_size or 0)
        done = 0
        with dest.open("wb") as handle:
            while chunk := response.read(1 << 17):
                cancel.check()
                handle.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(min(done / total, 1.0), label)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def stage(progress: ProgressCb = None) -> dict:
    """Télécharge et met en attente la dernière version. Ne remplace rien."""
    state = check(force=True)
    if state.get("check_error"):
        raise RuntimeError(f"Impossible de joindre GitHub: {state['check_error']}")
    if not state["available"]:
        raise RuntimeError("Aucune mise à jour disponible: tu as déjà la dernière version.")
    cached = _load_cached() or {}
    url = cached.get("asset_url")
    if not url:
        raise RuntimeError(
            "Cette release ne contient pas d'archive de mise à jour. "
            f"Télécharge la nouvelle version depuis {state['page']}"
        )

    latest = state["latest"]
    archive = UPDATE_DIR / "download.zip"
    if progress:
        progress(0.02, f"Téléchargement de la version {latest}")
    _download(url, archive, cached.get("asset_size") or 0,
              lambda f, l: progress(0.02 + f * 0.55, l) if progress else None,
              f"Téléchargement de la version {latest}")

    # Vérification d'intégrité: l'empreinte publiée avec la release fait foi.
    checksum_url = cached.get("checksum_url")
    if checksum_url:
        if progress:
            progress(0.6, "Vérification de l'archive")
        checksum_file = UPDATE_DIR / "download.sha256"
        _download(checksum_url, checksum_file, 0, None, "")
        expected = (checksum_file.read_text(encoding="utf-8").split() or [""])[0].lower()
        actual = _sha256(archive)
        if expected != actual:
            archive.unlink(missing_ok=True)
            raise RuntimeError(
                "L'archive téléchargée ne correspond pas à son empreinte de contrôle. "
                "Téléchargement corrompu ou altéré: rien n'a été modifié, réessaie."
            )

    if progress:
        progress(0.7, "Préparation de la mise à jour")
    if _PENDING_DIR.exists():
        import shutil

        shutil.rmtree(_PENDING_DIR)
    _PENDING_DIR.mkdir(parents=True)
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            name = member.filename
            # Garde-fou contre les chemins sortant du dossier (zip-slip).
            target = (_PENDING_DIR / name).resolve()
            if not str(target).startswith(str(_PENDING_DIR.resolve())):
                raise RuntimeError(f"Archive refusée: chemin suspect ({name}).")
        zf.extractall(_PENDING_DIR)

    marker = _PENDING_DIR / "app" / "__init__.py"
    if not marker.exists():
        import shutil

        shutil.rmtree(_PENDING_DIR, ignore_errors=True)
        raise RuntimeError("Archive inattendue: elle ne contient pas le code de l'application.")

    _PENDING_INFO.write_text(json.dumps({
        "version": latest,
        "staged_at": time.time(),
        "from": __version__,
    }, ensure_ascii=False), encoding="utf-8")
    archive.unlink(missing_ok=True)
    (UPDATE_DIR / "download.sha256").unlink(missing_ok=True)
    if progress:
        progress(1.0, f"Version {latest} prête — redémarre pour l'appliquer")
    return {"staged": latest, "supervised": supervised()}


def discard_pending() -> bool:
    import shutil

    existed = _PENDING_DIR.exists()
    shutil.rmtree(_PENDING_DIR, ignore_errors=True)
    _PENDING_INFO.unlink(missing_ok=True)
    return existed


def restart_now(exit_code: int = RESTART_EXIT_CODE, delay: float = 0.7) -> None:
    """Arrête le processus après un court délai, le temps de répondre au client."""
    def stop() -> None:
        time.sleep(delay)
        os._exit(exit_code)

    threading.Thread(target=stop, daemon=True).start()

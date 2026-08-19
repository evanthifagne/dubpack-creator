"""Séparation voix / fond sonore pour produire _backing_track.ogg."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from . import media
from .config import CACHE_DIR, module_available

ProgressCb = Callable[[float, str], None] | None

_PCT = re.compile(r"(\d{1,3})%")


def available() -> bool:
    return module_available("demucs")


def install_hint() -> str:
    return (
        "La séparation des voix demande Demucs (et PyTorch, ~2 Go). "
        f"Installe-le avec: {Path(sys.executable).name} -m pip install demucs"
    )


def separate_backing(source: Path, out_dir: Path, cb: ProgressCb = None,
                     model: str = "htdemucs") -> Path:
    """Isole l'accompagnement (musique + bruits) et le renvoie en .ogg."""
    if not available():
        raise RuntimeError(install_hint())
    out_dir.mkdir(parents=True, exist_ok=True)
    wav = out_dir / "_separate_input.wav"
    if cb:
        cb(0.02, "Préparation de l'audio")
    media.extract_audio(source, wav, sr=44100, mono=False)

    work = out_dir / "_demucs"
    if work.exists():
        shutil.rmtree(work)
    cmd = [
        sys.executable, "-m", "demucs", "--two-stems", "vocals",
        "-n", model, "-o", str(work), str(wav),
    ]
    env = {"TORCH_HOME": str(CACHE_DIR / "models" / "torch")}
    import os

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace", env={**os.environ, **env},
        **({"creationflags": 0x08000000} if os.name == "nt" else {}),
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        match = _PCT.search(line)
        if match and cb:
            cb(0.05 + 0.85 * min(int(match.group(1)), 100) / 100, "Séparation des voix (Demucs)")
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("Demucs a échoué. Vérifie l'installation de PyTorch.")

    stems = list(work.rglob("no_vocals.*"))
    if not stems:
        raise RuntimeError("Demucs n'a pas produit de piste d'accompagnement.")
    if cb:
        cb(0.92, "Encodage du fond sonore")
    result = media.encode_ogg(stems[0], out_dir / "_backing_track.ogg")
    shutil.rmtree(work, ignore_errors=True)
    wav.unlink(missing_ok=True)
    if cb:
        cb(1.0, "Fond sonore prêt")
    return result


def backing_from_source(source: Path, out_dir: Path, cb: ProgressCb = None) -> Path:
    """Repli sans Demucs: l'audio d'origine complet sert de fond sonore."""
    out_dir.mkdir(parents=True, exist_ok=True)
    return media.encode_ogg(source, out_dir / "_backing_track.ogg", cb=cb)

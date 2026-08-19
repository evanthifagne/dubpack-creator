"""Sélecteur de dossier natif, ouvert dans un processus séparé.

tkinter n'aime pas être piloté depuis un thread secondaire (et encore moins sur
macOS). On lance donc une mini application dans un sous-processus qui affiche la
boîte de dialogue et renvoie le chemin choisi sur sa sortie standard.
"""
from __future__ import annotations

import os
import subprocess
import sys

_SCRIPT = r'''
import sys
try:
    import tkinter
    from tkinter import filedialog
except Exception:
    sys.exit(3)
title = sys.argv[1] if len(sys.argv) > 1 else "Choisir un dossier"
initial = sys.argv[2] if len(sys.argv) > 2 else ""
root = tkinter.Tk()
root.withdraw()
root.attributes("-topmost", True)
try:
    path = filedialog.askdirectory(title=title, initialdir=initial or None, mustexist=True)
finally:
    root.destroy()
if path:
    sys.stdout.write(path)
'''


def available() -> bool:
    try:
        import tkinter  # noqa: F401

        return True
    except Exception:
        return False


def ask_directory(title: str = "Choisir un dossier", initial: str = "",
                  timeout: int = 300) -> str | None:
    """Retourne le dossier choisi, ou None si annulé / dialogue indisponible."""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _SCRIPT, title, initial],
            capture_output=True, text=True, timeout=timeout,
            **({"creationflags": 0x08000000} if os.name == "nt" else {}),
        )
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode == 3:
        raise RuntimeError(
            "La boîte de dialogue système n'est pas disponible (tkinter manquant). "
            "Colle le chemin du dossier à la main."
        )
    path = (proc.stdout or "").strip()
    return path or None

#!/usr/bin/env python3
"""Installation complète de DubPack Creator (appelé par INSTALLER.bat).

Crée l'environnement Python, installe les dépendances, met ffmpeg en place,
puis vérifie que tout répond. Peut être relancé sans risque.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / "venv" if (ROOT / "venv").exists() else ROOT / ".venv"
MIN_PY = (3, 10)


def say(message: str = "") -> None:
    print(message, flush=True)


def step(number: int, total: int, title: str) -> None:
    say()
    say(f"  [{number}/{total}] {title}")
    say("  " + "-" * 52)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(cmd: list[str], label: str, quiet: bool = True) -> None:
    result = subprocess.run(cmd, capture_output=quiet, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()[-15:]
        raise SystemExit(f"\n  ECHEC : {label}\n  " + "\n  ".join(detail))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-ffmpeg", action="store_true")
    parser.add_argument("--extras", action="store_true",
                        help="installe aussi Demucs et les empreintes vocales avancées")
    parser.add_argument("--ffmpeg-zip", help="archive ffmpeg locale")
    parser.add_argument("--no-shortcut", action="store_true")
    args = parser.parse_args()

    total = 5
    say()
    say("  ==============================================")
    say("   Installation de DubPack Creator")
    say("  ==============================================")

    if sys.version_info < MIN_PY:
        say(f"\n  Python {MIN_PY[0]}.{MIN_PY[1]} ou plus récent est nécessaire.")
        say(f"  Version détectée : {sys.version.split()[0]}")
        say("  Télécharge Python sur https://www.python.org/downloads/")
        return 1
    say(f"\n  Python {sys.version.split()[0]} - OK")

    step(1, total, "Environnement Python isolé")
    if venv_python().exists():
        say("  Déjà présent, on le réutilise.")
    else:
        run([sys.executable, "-m", "venv", str(VENV)], "création de l'environnement")
        say(f"  Créé : {VENV.name}")

    step(2, total, "Dépendances Python (quelques minutes)")
    python = str(venv_python())
    run([python, "-m", "pip", "install", "--upgrade", "pip", "-q"], "mise à jour de pip")
    run([python, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")],
        "installation des dépendances", quiet=False)
    say("  Whisper, yt-dlp et le serveur web sont installés.")

    if args.extras:
        step(2, total, "Modules optionnels (téléchargement lourd)")
        run([python, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements-extra.txt")],
            "installation des modules optionnels", quiet=False)

    step(3, total, "ffmpeg")
    if args.skip_ffmpeg:
        say("  Ignoré à la demande.")
    else:
        cmd = [python, str(ROOT / "tools/setup_ffmpeg.py")]
        if args.ffmpeg_zip:
            cmd += ["--zip", args.ffmpeg_zip]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            say()
            say("  ffmpeg n'a pas pu être installé automatiquement.")
            say("  Telecharge la build 'essentials' sur https://www.gyan.dev/ffmpeg/builds/")
            say(f"  puis place ffmpeg.exe et ffprobe.exe dans : {ROOT / 'bin'}")

    step(4, total, "Vérification")
    check = subprocess.run(
        [python, "-c",
         "import sys; sys.path.insert(0, r'" + str(ROOT) + "');"
         "from app.config import capabilities; import json; print(json.dumps(capabilities()))"],
        capture_output=True, text=True,
    )
    if check.returncode != 0:
        say("  L'application ne démarre pas :")
        say("  " + (check.stderr or "").strip()[-600:])
        return 1
    import json

    caps = json.loads(check.stdout)
    say(f"  ffmpeg           : {caps['ffmpeg'] or 'ABSENT'}")
    say(f"  encodeur Theora  : {'oui' if caps['theora'] else 'NON - export vidéo impossible'}")
    say(f"  transcription    : {', '.join(caps['asr_engines']) or 'ABSENTE'}")
    say(f"  liens vidéo      : {'yt-dlp prêt' if caps['yt_dlp'] else 'ABSENT'}")
    say(f"  séparation voix  : {'Demucs prêt' if caps['demucs'] else 'non installé (optionnel)'}")

    blocking = []
    if not caps["ffmpeg"]:
        blocking.append("ffmpeg")
    if not caps["theora"]:
        blocking.append("encodeur Theora")
    if not caps["asr_engines"]:
        blocking.append("moteur de transcription")

    step(5, total, "Raccourci")
    if args.no_shortcut or os.name != "nt":
        say("  Ignoré.")
    else:
        try:
            make_windows_shortcut()
            say("  Raccourci 'DubPack Creator' cree sur le Bureau.")
        except Exception as exc:
            say(f"  Raccourci non créé ({exc}). Lance DEMARRER.bat directement.")

    say()
    say("  ==============================================")
    if blocking:
        say(f"   Installation incomplète : {', '.join(blocking)}")
        say("  ==============================================")
        return 1
    say("   Installation terminée.")
    say("   Lance l'outil avec DEMARRER.bat")
    say("  ==============================================")
    return 0


def make_windows_shortcut() -> None:
    """Raccourci Bureau via l'hôte de scripts Windows (aucune dépendance)."""
    desktop = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop"
    if not desktop.is_dir():
        raise RuntimeError("Bureau introuvable")
    target = ROOT / "DEMARRER.bat"
    link = desktop / "DubPack Creator.lnk"
    vbs = ROOT / "tools" / "_shortcut.vbs"
    vbs.write_text(
        'Set s = CreateObject("WScript.Shell")\n'
        f'Set l = s.CreateShortcut("{link}")\n'
        f'l.TargetPath = "{target}"\n'
        f'l.WorkingDirectory = "{ROOT}"\n'
        'l.Description = "Creation de dub packs pour Choicer Voicer"\n'
        'l.Save\n',
        encoding="utf-8",
    )
    try:
        subprocess.run(["cscript", "//nologo", str(vbs)], check=True,
                       capture_output=True, timeout=30)
    finally:
        vbs.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())

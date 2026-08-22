#!/usr/bin/env python3
"""Assemble le paquet distribuable (ZIP) de DubPack Creator.

    python tools/build_package.py                        # paquet léger (~150 Ko)
    python tools/build_package.py --with-ffmpeg          # ffmpeg embarqué (~110 Mo)
    python tools/build_package.py --with-ffmpeg a.zip    # depuis une archive locale

Le paquet léger télécharge ffmpeg pendant l'installation; celui avec ffmpeg
embarqué évite ce téléchargement sur le PC de destination.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

# Ce qui part dans le paquet.
INCLUDE_FILES = [
    "INSTALLER.bat", "DEMARRER.bat", "LISEZ-MOI.txt", "README.md",
    "run.py", "run_server.py", "requirements.txt", "requirements-extra.txt",
    "start.bat", "start.command", "LICENSE", "THIRD-PARTY.md",
]
INCLUDE_DIRS = ["app", "web", "tools"]
# Fichiers Windows: fins de ligne CRLF, sinon l'Explorateur et cmd.exe
# affichent tout sur une seule ligne.
CRLF_SUFFIXES = {".bat", ".txt"}
EXCLUDE_NAMES = {"__pycache__", ".DS_Store", "Thumbs.db", "desktop.ini",
                 "settings.json", "_shortcut.vbs"}


def clean(target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)


def copy_tree(src: Path, dst: Path) -> int:
    count = 0
    for item in sorted(src.rglob("*")):
        if any(part in EXCLUDE_NAMES for part in item.parts):
            continue
        if item.suffix in {".pyc", ".pyo"}:
            continue
        relative = item.relative_to(src)
        target = dst / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            count += 1
    return count


def to_crlf(path: Path) -> None:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    path.write_bytes(data)


def embed_ffmpeg(stage: Path, source: str | None) -> bool:
    """Place ffmpeg.exe et ffprobe.exe dans bin/ du paquet."""
    cmd = [sys.executable, str(ROOT / "tools/setup_ffmpeg.py"),
           "--dest", str(stage / "bin"), "--force"]
    if source and source != "auto":
        cmd += ["--zip", source]
    print("  ffmpeg :")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("  ffmpeg n'a pas pu etre embarque.")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-ffmpeg", nargs="?", const="auto", default=None,
                        help="embarque ffmpeg (chemin d'archive, ou rien pour telecharger)")
    parser.add_argument("--name", default="DubPackCreator-Windows")
    args = parser.parse_args()

    version = "1.0.0"
    init = (ROOT / "app/__init__.py").read_text(encoding="utf-8")
    for line in init.splitlines():
        if line.startswith("__version__"):
            version = line.split("=")[1].strip().strip('"\'')

    stage = DIST / args.name
    print(f"\n  Construction de {args.name} v{version}")
    print("  " + "-" * 52)
    clean(stage)

    total = 0
    for name in INCLUDE_FILES:
        source = ROOT / name
        if not source.exists():
            print(f"  MANQUANT : {name}")
            continue
        shutil.copy2(source, stage / name)
        total += 1
    for name in INCLUDE_DIRS:
        source = ROOT / name
        if source.is_dir():
            total += copy_tree(source, stage / name)

    # Dossiers créés vides, attendus au premier lancement.
    for folder in ("bin", "projects"):
        (stage / folder).mkdir(exist_ok=True)
    (stage / "bin/.gitkeep").touch()

    converted = 0
    for item in stage.rglob("*"):
        if item.is_file() and item.suffix.lower() in CRLF_SUFFIXES:
            to_crlf(item)
            converted += 1

    print(f"  {total} fichiers copies, {converted} convertis en CRLF")

    if args.with_ffmpeg:
        embed_ffmpeg(stage, args.with_ffmpeg)

    suffix = "-avec-ffmpeg" if args.with_ffmpeg else ""
    archive = DIST / f"{args.name}-v{version}{suffix}.zip"
    if archive.exists():
        archive.unlink()
    print("  Compression...")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in sorted(stage.rglob("*")):
            if item.is_file():
                zf.write(item, arcname=str(Path(args.name) / item.relative_to(stage)))

    size = archive.stat().st_size
    print("  " + "-" * 52)
    print(f"  Paquet : {archive}")
    print(f"  Taille : {size / 1048576:.1f} Mo")
    print(f"  Dossier: {stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

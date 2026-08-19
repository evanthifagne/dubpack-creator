#!/usr/bin/env python3
"""Installe ffmpeg dans le dossier bin/ de l'outil.

Sous Windows, on récupère la build 'essentials' de gyan.dev: c'est la source
recommandée par le projet FFmpeg, et elle contient bien `libtheora` et
`libvorbis`, indispensables pour produire le `dub_video.ogv` du pack.

    python tools/setup_ffmpeg.py              # télécharge et installe
    python tools/setup_ffmpeg.py --zip a.zip  # depuis une archive locale
    python tools/setup_ffmpeg.py --check      # vérifie l'installation
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"

WINDOWS_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
NEEDED = ("ffmpeg", "ffprobe")
REQUIRED_ENCODERS = ("libtheora", "libvorbis")


def exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def installed() -> dict[str, str | None]:
    """Où trouve-t-on chaque binaire: dans bin/, sur le PATH, ou nulle part."""
    out: dict[str, str | None] = {}
    for name in NEEDED:
        local = BIN / exe(name)
        out[name] = str(local) if local.exists() else shutil.which(name)
    return out


def check_encoders(ffmpeg: str) -> tuple[bool, list[str]]:
    """Vérifie la présence des encodeurs nécessaires à l'export."""
    try:
        proc = subprocess.run([ffmpeg, "-hide_banner", "-encoders"],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, [f"ffmpeg illisible: {exc}"]
    missing = [e for e in REQUIRED_ENCODERS if e not in proc.stdout]
    return not missing, missing


def download(url: str, dest: Path) -> Path:
    """Téléchargement avec barre de progression (l'archive pèse ~110 Mo)."""
    print(f"  Téléchargement de ffmpeg depuis {url}")
    request = Request(url, headers={"User-Agent": "DubPackCreator/1.0"})
    with urlopen(request, timeout=120) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        chunk_size = 1 << 18
        with dest.open("wb") as handle:
            while chunk := response.read(chunk_size):
                handle.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    bar = "#" * (pct // 4)
                    print(f"\r  [{bar:<25}] {pct:3d}%  {done >> 20} / {total >> 20} Mo",
                          end="", flush=True)
    print()
    return dest


def extract(archive: Path, dest: Path) -> list[str]:
    """Extrait uniquement ffmpeg et ffprobe, à plat dans bin/."""
    dest.mkdir(parents=True, exist_ok=True)
    wanted = {exe(n) for n in NEEDED}
    written = []
    with zipfile.ZipFile(archive) as zf:
        members = [m for m in zf.namelist() if Path(m).name in wanted]
        if not members:
            # Une archive Windows extraite sur un autre OS garde les .exe.
            members = [m for m in zf.namelist()
                       if Path(m).name in {f"{n}.exe" for n in NEEDED}]
        if not members:
            raise RuntimeError("Archive inattendue: ffmpeg introuvable dedans.")
        for member in members:
            target = dest / Path(member).name
            with zf.open(member) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)
            target.chmod(0o755)
            written.append(target.name)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Installe ffmpeg dans bin/")
    parser.add_argument("--zip", help="archive locale au lieu du téléchargement")
    parser.add_argument("--url", default=WINDOWS_URL)
    parser.add_argument("--dest", default=str(BIN))
    parser.add_argument("--check", action="store_true", help="vérifier seulement")
    parser.add_argument("--force", action="store_true", help="réinstaller même si présent")
    args = parser.parse_args()
    dest = Path(args.dest)

    found = installed()
    if args.check or (all(found.values()) and not args.force):
        if found["ffmpeg"]:
            ok, missing = check_encoders(found["ffmpeg"])
            print(f"  ffmpeg  : {found['ffmpeg']}")
            print(f"  ffprobe : {found['ffprobe'] or 'absent (optionnel)'}")
            if ok:
                print("  Encodeurs libtheora et libvorbis : presents (OK)")
                return 0
            print(f"  ATTENTION : encodeurs manquants : {', '.join(missing)}")
            if args.check:
                return 1
            print("  Installation d'une build complète...")
        elif args.check:
            print("  ffmpeg introuvable.")
            return 1

    if os.name != "nt" and not args.zip:
        print("  Installation automatique prévue pour Windows.")
        print("  macOS : brew install ffmpeg    |    Linux : apt install ffmpeg")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(args.zip) if args.zip else download(args.url, Path(tmp) / "ffmpeg.zip")
        if not archive.exists():
            print(f"  Archive introuvable : {archive}")
            return 1
        print("  Extraction...")
        written = extract(archive, dest)
    print(f"  Installé dans {dest} : {', '.join(written)}")

    # On ne vérifie les encodeurs que si les binaires sont exécutables ici:
    # préparer un package Windows depuis un Mac est un cas légitime.
    installed_name = next((n for n in written if Path(n).stem == "ffmpeg"), None)
    ffmpeg_path = dest / installed_name if installed_name else None
    runnable = bool(ffmpeg_path) and (os.name == "nt") == ffmpeg_path.name.endswith(".exe")
    if runnable:
        ok, missing = check_encoders(str(ffmpeg_path))
        if not ok:
            print(f"  ATTENTION : encodeurs manquants : {', '.join(missing)}")
            return 1
        print("  Encodeurs libtheora et libvorbis : presents (OK)")
    else:
        print("  Binaires Windows en place (non exécutables sur cet OS) -")
        print("  les encodeurs seront vérifiés au premier lancement sur le PC.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

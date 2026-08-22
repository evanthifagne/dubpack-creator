#!/usr/bin/env python3
"""Construit tous les livrables d'une release DubPack Creator.

    python tools/build_release.py            # tout
    python tools/build_release.py --skip-dmg # sans le paquet macOS

Produit dans dist/release/ :
    DubPackCreator-Setup-<v>.exe    installeur Windows (NSIS, sans admin)
    DubPackCreator-<v>-macOS.dmg    application macOS (Apple Silicon)
    DubPackCreator-Windows-<v>.zip  archive classique (scripts .bat)
    update-code.zip (+ .sha256)     archive consommée par la mise à jour auto
"""
from __future__ import annotations

import argparse
import json
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
RELEASE = ROOT / "dist" / "release"
RUNTIMES = ROOT / "dist" / "runtimes"

PY_TAG = "20260814"
PY_VER = "3.12.14"
RUNTIME_WIN = f"cpython-{PY_VER}+{PY_TAG}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
RUNTIME_MAC = f"cpython-{PY_VER}+{PY_TAG}-aarch64-apple-darwin-install_only_stripped.tar.gz"
RUNTIME_URL = "https://github.com/astral-sh/python-build-standalone/releases/download"

CODE_FILES = [
    "run.py", "run_server.py", "requirements.txt", "requirements-extra.txt",
    "LISEZ-MOI.txt", "README.md", "THIRD-PARTY.md", "LICENSE",
]
CODE_DIRS = ["app", "web", "tools"]
EXCLUDE = {"__pycache__", ".DS_Store", "Thumbs.db", "desktop.ini", "_shortcut.vbs"}


def say(message: str) -> None:
    print(f"  {message}", flush=True)


def run(cmd: list[str], **kwargs) -> None:
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        raise SystemExit(f"ECHEC: {' '.join(str(c) for c in cmd[:3])}...")


def version() -> str:
    text = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("Version introuvable dans app/__init__.py")
    return match.group(1)


FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def ensure_ffmpeg_zip() -> Path:
    """Archive ffmpeg Windows, téléchargée une seule fois puis réutilisée."""
    RUNTIMES.mkdir(parents=True, exist_ok=True)
    target = RUNTIMES / "ffmpeg-release-essentials.zip"
    if not target.exists():
        say("Téléchargement de ffmpeg pour Windows (~90 Mo, une seule fois)...")
        run(["curl", "-sL", "-o", str(target), FFMPEG_ZIP_URL])
    return target


def ensure_runtime(name: str) -> Path:
    RUNTIMES.mkdir(parents=True, exist_ok=True)
    target = RUNTIMES / name
    if not target.exists():
        say(f"Téléchargement du runtime {name}...")
        run(["curl", "-sL", "-o", str(target), f"{RUNTIME_URL}/{PY_TAG}/{name}"])
    return target


def stage_code(dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name in CODE_FILES:
        source = ROOT / name
        if source.exists():
            shutil.copy2(source, dest / name)
    for folder in CODE_DIRS:
        for item in sorted((ROOT / folder).rglob("*")):
            if not item.is_file():
                continue
            if any(part in EXCLUDE for part in item.parts) or item.suffix in {".pyc", ".pyo"}:
                continue
            target = dest / item.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def sync_winres(ver: str) -> None:
    """Aligne les métadonnées de l'exe Windows sur la version courante."""
    path = ROOT / "launcher" / "winres" / "winres.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    four = ".".join((ver.split(".") + ["0", "0", "0"])[:3]) + ".0"
    data["RT_MANIFEST"]["#1"]["0409"]["identity"]["version"] = four
    fixed = data["RT_VERSION"]["#1"]["0000"]["fixed"]
    fixed["file_version"] = fixed["product_version"] = four
    info = data["RT_VERSION"]["#1"]["0000"]["info"]["040c"]
    info["ProductVersion"] = info["FileVersion"] = ver
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_launchers(ver: str) -> tuple[Path, Path]:
    say("Compilation du lanceur (Go)...")
    sync_winres(ver)
    launcher = ROOT / "launcher"
    out = ROOT / "dist" / "launcher"
    out.mkdir(parents=True, exist_ok=True)
    winres = shutil.which("go-winres") or str(Path.home() / "go" / "bin" / "go-winres")
    run([winres, "make", "--in", "winres/winres.json", "--out", "winres_gen"], cwd=launcher)
    win = out / "DubPackCreator-windows-amd64.exe"
    mac = out / "DubPackCreator-darwin-arm64"
    env_base = {"CGO_ENABLED": "0"}
    import os

    run(["go", "build", "-ldflags", "-s -w -H=windowsgui", "-o", str(win), "."],
        cwd=launcher, env={**os.environ, **env_base, "GOOS": "windows", "GOARCH": "amd64"})
    run(["go", "build", "-ldflags", "-s -w", "-o", str(mac), "."],
        cwd=launcher, env={**os.environ, **env_base, "GOOS": "darwin", "GOARCH": "arm64"})
    return win, mac


def build_update_zip() -> None:
    say("Archive de mise à jour...")
    run([sys.executable, str(ROOT / "tools" / "build_update_zip.py"), str(RELEASE)])


def build_windows_installer(ver: str, win_launcher: Path) -> Path:
    say("Installeur Windows...")
    stage = BUILD / "windows-stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    stage_code(stage / "code")

    say("  runtime Python...")
    with tarfile.open(ensure_runtime(RUNTIME_WIN)) as tf:
        tf.extractall(stage)  # contient python/

    say("  ffmpeg...")
    bin_dir = stage / "bin"
    bin_dir.mkdir()
    run([sys.executable, str(ROOT / "tools" / "setup_ffmpeg.py"),
         "--zip", str(ensure_ffmpeg_zip()), "--dest", str(bin_dir), "--force"])

    out = RELEASE / f"DubPackCreator-Setup-{ver}.exe"
    run([
        "makensis", "-V2",
        f"-DVERSION={ver}",
        f"-DSTAGE={stage}",
        f"-DLAUNCHER={win_launcher}",
        f"-DICON={ROOT / 'assets' / 'icon-classic.ico'}",
        f"-DOUT={out}",
        str(ROOT / "installer" / "windows.nsi"),
    ])
    return out


def build_macos_dmg(ver: str, mac_launcher: Path) -> Path:
    say("Application macOS...")
    stage = BUILD / "macos-stage"
    if stage.exists():
        shutil.rmtree(stage)
    app = stage / "DubPack Creator.app"
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "Resources" / "payload").mkdir(parents=True)

    shutil.copy2(mac_launcher, contents / "MacOS" / "DubPack Creator")
    (contents / "MacOS" / "DubPack Creator").chmod(0o755)
    shutil.copy2(ROOT / "assets" / "icon.icns", contents / "Resources" / "icon.icns")

    stage_code(contents / "Resources" / "payload" / "code")
    shutil.copy2(ensure_runtime(RUNTIME_MAC),
                 contents / "Resources" / "payload" / "python.tar.gz")

    plist = {
        "CFBundleName": "DubPack Creator",
        "CFBundleDisplayName": "DubPack Creator",
        "CFBundleIdentifier": "com.evanthifagne.dubpackcreator",
        "CFBundleVersion": ver,
        "CFBundleShortVersionString": ver,
        "CFBundleExecutable": "DubPack Creator",
        "CFBundleIconFile": "icon",
        "CFBundlePackageType": "APPL",
        "LSMinimumSystemVersion": "11.0",
        # Pas d'icône dans le Dock: l'application vit dans le navigateur.
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    }
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(plist, handle)

    say("  signature ad hoc...")
    run(["codesign", "--force", "--deep", "-s", "-", str(app)])

    say("  image disque...")
    dmg_root = BUILD / "dmg-root"
    if dmg_root.exists():
        shutil.rmtree(dmg_root)
    dmg_root.mkdir()
    shutil.copytree(app, dmg_root / app.name, symlinks=True)
    (dmg_root / "Applications").symlink_to("/Applications")

    out = RELEASE / f"DubPackCreator-{ver}-macOS.dmg"
    out.unlink(missing_ok=True)
    run(["hdiutil", "create", "-volname", "DubPack Creator", "-srcfolder",
         str(dmg_root), "-ov", "-format", "UDZO", "-quiet", str(out)])
    return out


def build_legacy_zip(ver: str) -> Path:
    say("Archive classique Windows (scripts .bat)...")
    run([sys.executable, str(ROOT / "tools" / "build_package.py"),
         "--with-ffmpeg", str(ensure_ffmpeg_zip())])
    built = ROOT / "dist" / f"DubPackCreator-Windows-v{ver}-avec-ffmpeg.zip"
    target = RELEASE / f"DubPackCreator-Windows-{ver}.zip"
    target.unlink(missing_ok=True)
    shutil.move(str(built), str(target))
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-dmg", action="store_true")
    parser.add_argument("--skip-exe", action="store_true")
    parser.add_argument("--skip-zip", action="store_true")
    args = parser.parse_args()

    ver = version()
    print(f"\n  Release DubPack Creator {ver}")
    print("  " + "=" * 52)
    RELEASE.mkdir(parents=True, exist_ok=True)

    build_update_zip()
    win_launcher, mac_launcher = build_launchers(ver)
    if not args.skip_exe:
        build_windows_installer(ver, win_launcher)
    if not args.skip_dmg:
        build_macos_dmg(ver, mac_launcher)
    if not args.skip_zip:
        build_legacy_zip(ver)

    print("  " + "=" * 52)
    for item in sorted(RELEASE.iterdir()):
        say(f"{item.name:44s} {item.stat().st_size / 1048576:8.1f} Mo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

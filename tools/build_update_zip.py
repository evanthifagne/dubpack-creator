#!/usr/bin/env python3
"""Assemble `update-code.zip`, l'archive consommée par la mise à jour automatique.

Contenu: uniquement le code de l'application. Ni binaires, ni environnement
Python, ni données. C'est ce que le serveur télécharge depuis la release
GitHub et que le superviseur échange au redémarrage.

    python tools/build_update_zip.py [dossier_de_sortie]
"""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FILES = [
    "run.py", "run_server.py", "requirements.txt", "requirements-extra.txt",
    "DEMARRER.bat", "INSTALLER.bat", "start.bat", "start.command",
    "LISEZ-MOI.txt", "README.md", "THIRD-PARTY.md", "LICENSE",
]
DIRS = ["app", "web", "tools"]
EXCLUDE = {"__pycache__", ".DS_Store", "Thumbs.db", "desktop.ini", "_shortcut.vbs"}


def build(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / "update-code.zip"
    if archive.exists():
        archive.unlink()
    count = 0
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in FILES:
            path = ROOT / name
            if path.exists():
                zf.write(path, arcname=name)
                count += 1
        for folder in DIRS:
            base = ROOT / folder
            for item in sorted(base.rglob("*")):
                if not item.is_file():
                    continue
                if any(part in EXCLUDE for part in item.parts) or item.suffix in {".pyc", ".pyo"}:
                    continue
                zf.write(item, arcname=str(item.relative_to(ROOT)))
                count += 1
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (out_dir / "update-code.zip.sha256").write_text(
        f"{digest}  update-code.zip\n", encoding="utf-8")
    print(f"  {archive}  ({archive.stat().st_size / 1024:.0f} Ko, {count} fichiers)")
    print(f"  sha256: {digest}")
    return archive


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist"
    build(target)

#!/usr/bin/env python3
"""Construit le sprite d'icônes à partir des SVG Tabler.

Les icônes sont intégrées en clair dans `web/index.html`: aucune requête réseau,
l'interface fonctionne hors ligne. Ce script régénère le sprite quand on ajoute
une icône.

    python tools/build_icons.py chemin/vers/tabler/icons/outline
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Nom du fichier Tabler -> nom court utilisé dans l'interface.
ICONS = {
    "microphone": "microphone", "movie": "movie", "trash": "trash",
    "trash-x": "trash-x", "player-play": "play", "player-pause": "pause",
    "player-skip-back": "prev", "player-skip-forward": "next",
    "scissors": "scissors", "arrow-merge-both": "merge", "camera": "camera",
    "check": "check", "arrow-left": "back", "adjustments": "adjustments",
    "settings": "settings", "download": "download", "x": "close",
    "alert-triangle": "warning", "circle-check": "ok", "plus": "plus",
    "folder": "folder", "file-zip": "zip", "device-desktop": "desktop",
    "cpu": "cpu", "wand": "wand", "refresh": "refresh", "volume": "volume",
    "clock": "clock", "language": "language", "ruler-measure": "ruler",
    "puzzle": "puzzle", "server-cog": "server",
}

ATTRS = ('viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
         'stroke-linecap="round" stroke-linejoin="round"')

MARKER = re.compile(
    r'<svg xmlns="http://www\.w3\.org/2000/svg" style="display:none".*?</svg>', re.S)


def build(source: Path) -> str:
    symbols = []
    missing = []
    for filename, name in ICONS.items():
        path = source / f"{filename}.svg"
        if not path.exists():
            missing.append(filename)
            continue
        text = path.read_text(encoding="utf-8")
        inner = text[text.index(">", text.index("<svg")) + 1: text.rindex("</svg>")]
        # Tabler ouvre par un rectangle invisible, inutile dans un sprite.
        inner = re.sub(r'<path stroke="none"[^/]*/>', "", inner).strip()
        inner = re.sub(r"\s+", " ", inner)
        symbols.append(f'<symbol id="i-{name}" {ATTRS}>{inner}</symbol>')
    if missing:
        print(f"  manquantes: {', '.join(missing)}")
    print(f"  {len(symbols)} icones")
    return ('<svg xmlns="http://www.w3.org/2000/svg" style="display:none" '
            'aria-hidden="true">' + "".join(symbols) + "</svg>")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    source = Path(sys.argv[1])
    if not source.is_dir():
        print(f"Dossier introuvable: {source}")
        return 1
    sprite = build(source)
    (ROOT / "web" / "icons.svg").write_text(sprite, encoding="utf-8")

    page = ROOT / "web" / "index.html"
    html = page.read_text(encoding="utf-8")
    if MARKER.search(html):
        html = MARKER.sub(lambda _: sprite, html, count=1)
    else:
        html = html.replace("<body>\n", f"<body>\n\n{sprite}\n\n", 1)
    page.write_text(html, encoding="utf-8")
    print(f"  sprite intégré dans {page.name} ({len(sprite)} octets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

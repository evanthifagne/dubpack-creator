#!/usr/bin/env python3
"""Génère l'icône de l'application (PNG, ICO Windows, ICNS macOS).

Dessin: le micro de l'interface, orange sur carte sombre arrondie.
Rendu en très grand puis réduit, pour des bords nets sans bibliothèque de
rendu vectoriel.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent

BG = (23, 29, 41, 255)          # --panel
EDGE = (38, 48, 66, 255)        # --line
ACCENT = (249, 115, 22, 255)    # --accent


def draw_base(size: int = 1024) -> Image.Image:
    scale = 4
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Carte arrondie, avec un fin liseré.
    margin = big * 0.06
    radius = big * 0.22
    d.rounded_rectangle([margin, margin, big - margin, big - margin],
                        radius=radius, fill=BG, outline=EDGE, width=int(big * 0.008))

    # Micro : capsule, arceau, pied, socle. Épaisseur de trait généreuse pour
    # rester lisible en 16x16.
    w = int(big * 0.052)
    cx = big / 2

    cap_w = big * 0.20
    cap_top = big * 0.20
    cap_bottom = big * 0.52
    d.rounded_rectangle([cx - cap_w / 2, cap_top, cx + cap_w / 2, cap_bottom],
                        radius=cap_w / 2, outline=ACCENT, width=w)

    arc_r = big * 0.20
    arc_cy = big * 0.47
    d.arc([cx - arc_r, arc_cy - arc_r, cx + arc_r, arc_cy + arc_r],
          start=15, end=165, fill=ACCENT, width=w)

    stem_top = arc_cy + arc_r
    stem_bottom = big * 0.76
    d.line([cx, stem_top - w * 0.4, cx, stem_bottom], fill=ACCENT, width=w)
    base_w = big * 0.13
    d.line([cx - base_w, stem_bottom, cx + base_w, stem_bottom], fill=ACCENT, width=w)

    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    out = ROOT / "assets"
    out.mkdir(exist_ok=True)
    base = draw_base(1024)
    base.save(out / "icon.png")

    # ICO multi-tailles pour Windows.
    base.save(out / "icon.ico",
              sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    # ICNS via iconutil (outil système macOS).
    if sys.platform == "darwin":
        with tempfile.TemporaryDirectory() as tmp:
            iconset = Path(tmp) / "icon.iconset"
            iconset.mkdir()
            for px in (16, 32, 64, 128, 256, 512, 1024):
                scaled = base.resize((px, px), Image.LANCZOS)
                scaled.save(iconset / f"icon_{px}x{px}.png")
                if px <= 512:
                    base.resize((px * 2, px * 2), Image.LANCZOS).save(
                        iconset / f"icon_{px}x{px}@2x.png")
            subprocess.run(["iconutil", "-c", "icns", str(iconset),
                            "-o", str(out / "icon.icns")], check=True)
    for name in ("icon.png", "icon.ico", "icon.icns"):
        path = out / name
        if path.exists():
            print(f"  {path} ({path.stat().st_size / 1024:.0f} Ko)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

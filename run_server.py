#!/usr/bin/env python3
"""Entrée serveur de DubPack Creator, pilotée par un superviseur.

Ne s'occupe que du serveur: pas d'environnement virtuel, pas de navigateur.
C'est `run.py` (ou le lanceur natif de l'application installée) qui prépare
l'environnement, ouvre le navigateur et relance le serveur après une mise à
jour (code de sortie 42).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Serveur DubPack Creator")
    parser.add_argument("--port", type=int, default=8760)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT))
    import uvicorn

    try:
        uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="warning")
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

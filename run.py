#!/usr/bin/env python3
"""Lanceur de DubPack Creator - Windows et macOS.

Crée l'environnement Python isolé au premier lancement, installe les
dépendances, démarre le serveur local puis ouvre le navigateur.

    python run.py                  # lancement normal
    python run.py --no-browser     # sans ouvrir le navigateur
    python run.py --port 8888
    python run.py --skip-install   # démarrage rapide
    python run.py --install-extras # ajoute Demucs + empreintes vocales
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
MIN_PY = (3, 10)
STAMP = VENV / ".deps-ok"


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def in_venv() -> bool:
    """Sommes-nous dans l'environnement isolé du projet ?

    On compare `sys.prefix`, et non le chemin de l'exécutable: dans un venv,
    `bin/python` est un lien vers l'interpréteur système, donc les deux chemins
    se résolvent vers le même binaire.
    """
    try:
        return Path(sys.prefix).resolve() == VENV.resolve()
    except OSError:
        return False


def log(message: str) -> None:
    print(f"  {message}", flush=True)


def ensure_venv() -> None:
    if venv_python().exists():
        return
    log("Création de l'environnement Python (une seule fois)...")
    subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)


def pip_install(args: list[str], label: str) -> None:
    log(label)
    cmd = [str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "-q", *args]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise SystemExit(
            f"\n  L'installation a échoué ({label}).\n"
            "  Vérifie ta connexion internet puis relance."
        )


def ensure_deps(extras: bool = False) -> None:
    req = ROOT / "requirements.txt"
    fresh = req.stat().st_mtime
    if not STAMP.exists() or STAMP.stat().st_mtime < fresh:
        pip_install(["--upgrade", "pip"], "Mise à jour de pip...")
        pip_install(["-r", str(req)], "Installation des dépendances (quelques minutes)...")
        STAMP.write_text("ok", encoding="utf-8")
    if extras:
        pip_install(["-r", str(ROOT / "requirements-extra.txt")],
                    "Installation des modules optionnels (PyTorch : téléchargement lourd)...")


def free_port(preferred: int) -> int:
    for port in [preferred, *range(preferred + 1, preferred + 25)]:
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0


def wait_until_up(port: int, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.4)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.25)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Lance DubPack Creator")
    parser.add_argument("--port", type=int, default=8760)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--install-extras", action="store_true")
    args = parser.parse_args()

    # ASCII uniquement: les consoles Windows en cp850 ne savent pas
    # afficher les caracteres de cadre ni les symboles decoratifs.
    print("\n  ==========================================")
    print("   DubPack Creator - Choicer Voicer")
    print("  ==========================================\n")

    if sys.version_info < MIN_PY:
        print(f"  Python {MIN_PY[0]}.{MIN_PY[1]}+ est nécessaire (détecté : "
              f"{sys.version_info.major}.{sys.version_info.minor}).")
        print("  Télécharge-le sur https://www.python.org/downloads/")
        return 1

    if not in_venv():
        ensure_venv()
        if not args.skip_install:
            ensure_deps(extras=args.install_extras)
        # On relance le script à l'intérieur de l'environnement isolé.
        forwarded = [a for a in sys.argv[1:] if a != "--install-extras"]
        return subprocess.run([str(venv_python()), str(ROOT / "run.py"),
                               "--skip-install", *forwarded]).returncode

    port = free_port(args.port)
    if not port:
        print("  Aucun port libre trouvé.")
        return 1

    url = f"http://127.0.0.1:{port}"
    log(f"Serveur : {url}")
    log("Laisse cette fenêtre ouverte pendant l'utilisation. Ctrl+C pour arrêter.\n")

    import threading

    if not args.no_browser:
        def opener() -> None:
            if wait_until_up(port):
                webbrowser.open(url)
        threading.Thread(target=opener, daemon=True).start()

    import uvicorn

    sys.path.insert(0, str(ROOT))
    try:
        uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="warning")
    except KeyboardInterrupt:
        pass
    log("Serveur arrêté.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Lanceur de DubPack Creator - Windows et macOS.

Crée l'environnement Python isolé au premier lancement, installe les
dépendances, démarre le serveur local puis ouvre le navigateur. Reste ensuite
en veille pour superviser le serveur: quand celui-ci s'arrête avec le code 42
(« mise à jour prête »), il échange l'ancien code contre le nouveau et relance.

    python run.py                  # lancement normal
    python run.py --no-browser     # sans ouvrir le navigateur
    python run.py --port 8888
    python run.py --skip-install   # démarrage rapide
    python run.py --install-extras # ajoute Demucs + empreintes vocales
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DUBPACK_DATA_DIR") or ROOT)
VENV = ROOT / ".venv"
MIN_PY = (3, 10)
UPDATE = DATA / "update"

# Code de sortie convenu avec le serveur: « applique la mise à jour puis relance ».
RESTART_CODE = 42


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


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


def _req_hash() -> str:
    req = ROOT / "requirements.txt"
    return hashlib.sha256(req.read_bytes()).hexdigest() if req.exists() else "none"


def ensure_deps(extras: bool = False) -> None:
    """Installe les dépendances quand requirements.txt change réellement.

    On compare le contenu (empreinte), pas la date: une mise à jour remplace le
    fichier même quand la liste n'a pas bougé, et une date ne dit rien.
    """
    stamp = VENV / ".deps-ok"
    current = _req_hash()
    previous = stamp.read_text(encoding="utf-8").strip() if stamp.exists() else ""
    if previous != current:
        pip_install(["--upgrade", "pip"], "Mise à jour de pip...")
        pip_install(["-r", str(ROOT / "requirements.txt")],
                    "Installation des dépendances (quelques minutes)...")
        stamp.write_text(current, encoding="utf-8")
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


# ---------------------------------------------------------------------------
# Application des mises à jour (préparées par le serveur dans update/pending)
# ---------------------------------------------------------------------------

def apply_pending_update() -> str | None:
    """Échange le code contre la version en attente. Retourne la version, ou None.

    L'ancien code part dans update/backup: si le nouveau ne démarre pas, on le
    remet en place. Les projets, modèles et réglages ne sont pas concernés.
    """
    pending = UPDATE / "pending"
    info_file = UPDATE / "pending.json"
    if not pending.is_dir():
        return None
    version = "?"
    try:
        version = json.loads(info_file.read_text(encoding="utf-8")).get("version", "?")
    except (OSError, ValueError):
        pass
    log(f"Application de la mise à jour {version}...")

    backup = UPDATE / "backup"
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    backup.mkdir(parents=True, exist_ok=True)

    moved: list[str] = []
    try:
        for item in sorted(pending.iterdir()):
            target = ROOT / item.name
            if target.exists():
                shutil.move(str(target), str(backup / item.name))
            shutil.move(str(item), str(target))
            moved.append(item.name)
    except OSError as exc:
        log(f"Échange interrompu ({exc}) : retour à la version précédente.")
        _restore_backup()
        shutil.rmtree(pending, ignore_errors=True)
        info_file.unlink(missing_ok=True)
        return None

    shutil.rmtree(pending, ignore_errors=True)
    info_file.unlink(missing_ok=True)
    (UPDATE / "applied.json").write_text(json.dumps({
        "version": version, "at": time.time(), "files": moved,
    }, ensure_ascii=False), encoding="utf-8")
    log(f"Mise à jour {version} appliquée ({len(moved)} éléments).")
    return version


def _restore_backup() -> bool:
    backup = UPDATE / "backup"
    if not backup.is_dir():
        return False
    for item in sorted(backup.iterdir()):
        target = ROOT / item.name
        if target.exists():
            shutil.rmtree(target, ignore_errors=True) if target.is_dir() else target.unlink(missing_ok=True)
        shutil.move(str(item), str(target))
    shutil.rmtree(backup, ignore_errors=True)
    return True


def rollback_if_broken(started_at: float, exit_code: int) -> bool:
    """Le serveur vient-il de mourir aussitôt après une mise à jour ?

    Dans ce cas on remet l'ancienne version: mieux vaut un outil qui marche
    qu'une nouveauté qui plante.
    """
    applied = UPDATE / "applied.json"
    if exit_code in (0, RESTART_CODE) or not applied.exists():
        return False
    lived = time.time() - started_at
    if lived > 30:
        return False
    try:
        info = json.loads(applied.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = {}
    log(f"Le serveur s'est arrêté {lived:.0f}s après la mise à jour "
        f"{info.get('version', '?')} : retour à la version précédente.")
    if _restore_backup():
        applied.unlink(missing_ok=True)
        (UPDATE / "failed.txt").write_text(
            f"La mise à jour {info.get('version', '?')} a été annulée: "
            f"le serveur s'arrêtait aussitôt (code {exit_code}).",
            encoding="utf-8",
        )
        return True
    return False


# ---------------------------------------------------------------------------

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

    ensure_venv()
    if not args.skip_install:
        ensure_deps(extras=args.install_extras)

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

    env = {**os.environ, "DUBPACK_SUPERVISED": "1",
           "DUBPACK_DATA_DIR": str(DATA), "PYTHONUTF8": "1"}
    retried_after_rollback = False
    while True:
        applied = apply_pending_update()
        if applied and not args.skip_install:
            # La nouvelle version peut demander de nouvelles dépendances.
            ensure_deps()
        started_at = time.time()
        try:
            proc = subprocess.Popen(
                [str(venv_python()), str(ROOT / "run_server.py"), "--port", str(port)],
                env=env, cwd=str(ROOT),
            )
            code = proc.wait()
        except KeyboardInterrupt:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                pass
            code = 0
        if code == RESTART_CODE:
            log("Redémarrage demandé (mise à jour)...")
            continue
        if not retried_after_rollback and rollback_if_broken(started_at, code):
            retried_after_rollback = True
            continue
        break

    log("Serveur arrêté.")
    return 0 if code in (0, RESTART_CODE) else code


if __name__ == "__main__":
    raise SystemExit(main())

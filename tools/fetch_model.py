#!/usr/bin/env python3
"""Télécharge un modèle de transcription, en affichant sa progression.

Lancé comme processus séparé par l'application: cela rend le téléchargement
annulable (on peut tuer le processus) et permet de suivre l'avancement, que
huggingface_hub n'expose pas autrement que par sa barre tqdm.

    python tools/fetch_model.py small
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA = Path(os.environ.get("DUBPACK_DATA_DIR") or ROOT)
CACHE = DATA / ".cache" / "models"
os.environ.setdefault("HF_HOME", str(CACHE))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(CACHE))


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: fetch_model.py <modele>", flush=True)
        return 2
    name = sys.argv[1]

    from app.asr import MODEL_REPOS

    repo = MODEL_REPOS.get(name)
    if not repo:
        print(f"Modele inconnu: {name}", flush=True)
        return 2

    print(f"Telechargement de {name} depuis {repo}", flush=True)
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("huggingface_hub est absent", flush=True)
        return 1

    # huggingface_hub cree une barre par fichier: on agrege pour obtenir un
    # pourcentage global, seul chiffre utile a afficher.
    shared = {"total": 0, "done": 0, "last": -1}

    class Reporter:
        """Traduit l'avancement de huggingface_hub en lignes PROGRESS."""

        def __init__(self, *args, **kwargs) -> None:
            self.total = kwargs.get("total") or 0
            self.n = 0
            shared["total"] += self.total

        def update(self, n: int = 1) -> None:
            self.n += n
            shared["done"] += n
            self._emit()

        def _emit(self) -> None:
            if not shared["total"]:
                return
            pct = min(int(shared["done"] * 100 / shared["total"]), 99)
            if pct != shared["last"]:
                shared["last"] = pct
                print(f"PROGRESS {pct}", flush=True)

        def close(self) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            self.close()

        def set_description(self, *args, **kwargs) -> None:
            pass

        def set_postfix(self, *args, **kwargs) -> None:
            pass

        def refresh(self) -> None:
            pass

        @property
        def format_dict(self) -> dict:
            return {}

    try:
        # On ne garde que les poids int8 utilises par faster-whisper.
        path = snapshot_download(
            repo_id=repo,
            cache_dir=str(CACHE),
            tqdm_class=Reporter,
            max_workers=4,
        )
    except Exception as exc:
        print(f"ECHEC {exc.__class__.__name__}: {exc}", flush=True)
        return 1

    from app.asr import model_disk_size

    size = model_disk_size(name)
    print(f"PROGRESS 100", flush=True)
    print(f"OK {path} ({size / 1048576:.0f} Mo)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Annulation effective des tâches longues.

L'annulation seule ne suffit pas: une tâche bloquée dans un appel long (ffmpeg
qui encode, yt-dlp qui télécharge) ne relit pas le drapeau d'annulation avant la
fin de cet appel, ce qui donne l'impression que « Annulation demandée » ne fait
rien. On tient donc un registre des processus lancés par la tâche courante, pour
pouvoir les interrompre pour de bon.
"""
from __future__ import annotations

import subprocess
import threading

class Cancelled(Exception):
    """Interruption volontaire d'une tâche.

    Hérite d'`Exception` et non de `BaseException`: une exception hors de la
    hiérarchie `Exception` traverserait les gardes et tuerait le thread qui
    dépile la file d'attente.
    """

    def __init__(self, message: str = "Tâche annulée") -> None:
        super().__init__(message)


def check() -> None:
    """Lève `Cancelled` si l'arrêt a été demandé."""
    if is_cancelled():
        raise Cancelled()


_local = threading.local()
_registry: dict[str, set[subprocess.Popen]] = {}
_lock = threading.Lock()


def bind(job_id: str, cancel_event: threading.Event) -> None:
    """Associe le thread courant à une tâche."""
    _local.job_id = job_id
    _local.event = cancel_event
    with _lock:
        _registry.setdefault(job_id, set())


def unbind() -> None:
    job_id = getattr(_local, "job_id", None)
    _local.job_id = None
    _local.event = None
    if job_id:
        with _lock:
            _registry.pop(job_id, None)


def is_cancelled() -> bool:
    event = getattr(_local, "event", None)
    return bool(event and event.is_set())


def register(proc: subprocess.Popen) -> subprocess.Popen:
    """Déclare un processus comme appartenant à la tâche courante."""
    job_id = getattr(_local, "job_id", None)
    if job_id:
        with _lock:
            _registry.setdefault(job_id, set()).add(proc)
    return proc


def unregister(proc: subprocess.Popen) -> None:
    job_id = getattr(_local, "job_id", None)
    if not job_id:
        return
    with _lock:
        _registry.get(job_id, set()).discard(proc)


def stop_processes(job_id: str, grace: float = 3.0) -> int:
    """Interrompt les processus de la tâche. Retourne le nombre visé.

    On demande d'abord poliment (terminate), puis on force (kill): un ffmpeg en
    pleine écriture doit pouvoir fermer son fichier.
    """
    with _lock:
        procs = list(_registry.get(job_id, set()))
    stopped = 0
    for proc in procs:
        if proc.poll() is not None:
            continue
        stopped += 1
        try:
            proc.terminate()
        except (OSError, ValueError):
            continue
    for proc in procs:
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except (OSError, ValueError):
                pass
        except (OSError, ValueError):
            pass
    return stopped


def active_processes(job_id: str) -> int:
    with _lock:
        return sum(1 for p in _registry.get(job_id, set()) if p.poll() is None)

"""Suivi des tâches longues (transcription, encodage) et flux de progression."""
from __future__ import annotations

import re
import threading
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable


# yt-dlp et ffmpeg colorent leur sortie: ces codes salissent l'interface.
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\[[0-9];[0-9]{2}m")


def clean_message(text: str) -> str:
    return _ANSI.sub("", text or "").strip()


@dataclass
class Job:
    id: str
    kind: str
    project_id: str | None = None
    title: str = ""
    status: str = "queued"          # queued | running | done | error | cancelled
    progress: float = 0.0
    label: str = ""
    result: Any = None
    error: str | None = None
    position: int = 0               # rang dans la file (0 = en cours)
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    ended_at: float | None = None
    steps: list[dict] = field(default_factory=list)
    _target: Callable | None = field(default=None, repr=False)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        return (self.ended_at or time.time()) - self.started_at

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "project_id": self.project_id,
            "title": self.title, "status": self.status,
            "progress": round(self.progress, 4), "label": self.label,
            "result": self.result, "error": self.error,
            "position": self.position, "elapsed": round(self.elapsed, 1),
            "active": self.status in {"queued", "running"},
            "steps": self.steps[-40:],
        }


class JobManager:
    """File d'attente à un seul poste de travail.

    Transcrire, encoder et séparer des voix saturent le processeur: lancer deux
    de ces tâches en parallèle les rend toutes les deux plus lentes. On les
    exécute donc l'une après l'autre, ce qui permet à l'utilisateur d'enchaîner
    plusieurs dub packs sans y penser et de continuer à naviguer entre-temps.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._queue: deque[str] = deque()
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._worker: threading.Thread | None = None

    def create(self, kind: str, project_id: str | None = None,
               title: str = "") -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, project_id=project_id,
                  title=title or kind)
        with self._lock:
            self._jobs[job.id] = job
            # Purge des vieux jobs terminés pour ne pas fuir en mémoire.
            finished = [j for j in self._jobs.values()
                        if j.status in {"done", "error", "cancelled"}]
            for old in sorted(finished, key=lambda j: j.created_at)[:-40]:
                self._jobs.pop(old.id, None)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def active_for(self, project_id: str) -> Job | None:
        return next(
            (j for j in self._jobs.values()
             if j.project_id == project_id and j.status in {"queued", "running"}),
            None,
        )

    def active(self) -> list[Job]:
        """Tâches en cours et en attente, dans l'ordre de passage."""
        with self._lock:
            self._renumber()
            jobs = [j for j in self._jobs.values() if j.status in {"queued", "running"}]
        return sorted(jobs, key=lambda j: (j.status != "running", j.created_at))

    def _renumber(self) -> None:
        """Recalcule les rangs et rafraîchit le libellé des tâches en attente.

        Le libellé doit suivre la file: annoncer « 4 tâches devant » alors qu'il
        n'en reste qu'une donnerait une fausse idée de l'attente.
        """
        for job in self._jobs.values():
            if job.status == "running":
                job.position = 0
        for index, job_id in enumerate(self._queue, start=1):
            job = self._jobs.get(job_id)
            if job and job.status == "queued":
                job.position = index
                job.label = ("Prochaine à démarrer" if index == 1
                             else f"En attente — {index - 1} tâche(s) devant")

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status not in {"queued", "running"}:
            return False
        job._cancel.set()
        if job.status == "queued":
            # Pas encore demarre: on le retire proprement de la file.
            with self._lock:
                if job_id in self._queue:
                    self._queue.remove(job_id)
                job.status = "cancelled"
                job.label = "Annulé avant démarrage"
                job.ended_at = time.time()
                self._renumber()
            return True
        job.label = "Annulation demandée…"
        return True

    def run(self, job: Job, target: Callable[[Job, Callable[[float, str], None]], Any]) -> Job:
        """Met `target` dans la file. `target(job, progress)`."""
        job._target = target
        with self._lock:
            self._queue.append(job.id)
            self._renumber()
            self._ensure_worker()
        self._wake.set()
        return job

    def _ensure_worker(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._loop, name="job-worker", daemon=True)
        self._worker.start()

    def _loop(self) -> None:
        while True:
            with self._lock:
                job_id = self._queue.popleft() if self._queue else None
                self._renumber()
            if job_id is None:
                # Rien a faire: on attend d'etre reveille par un nouveau job.
                self._wake.wait(timeout=30)
                self._wake.clear()
                continue
            job = self._jobs.get(job_id)
            if job is None or job.status != "queued" or job._cancel.is_set():
                continue
            self._execute(job)

    def _execute(self, job: Job) -> None:
        def progress(frac: float, label: str = "") -> None:
            if job._cancel.is_set():
                raise JobCancelled()
            job.progress = max(0.0, min(float(frac), 1.0))
            if label and label != job.label:
                job.label = label
                job.steps.append({"at": round(job.progress, 3), "label": label})

        job.status = "running"
        job.started_at = time.time()
        job.position = 0
        job.label = ""
        try:
            job.result = job._target(job, progress)  # type: ignore[misc]
            job.status = "done"
            job.progress = 1.0
            job.label = job.label or "Terminé"
        except JobCancelled:
            job.status = "cancelled"
            job.label = "Annulé"
        except Exception as exc:
            job.status = "error"
            job.error = clean_message(str(exc)) or exc.__class__.__name__
            job.label = "Erreur"
            traceback.print_exc()
        finally:
            job.ended_at = time.time()
            job._target = None
            with self._lock:
                self._renumber()


class JobCancelled(Exception):
    pass


manager = JobManager()

"""Suivi des tâches longues (transcription, encodage) et flux de progression."""
from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Job:
    id: str
    kind: str
    project_id: str | None = None
    status: str = "pending"          # pending | running | done | error | cancelled
    progress: float = 0.0
    label: str = ""
    result: Any = None
    error: str | None = None
    steps: list[dict] = field(default_factory=list)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "project_id": self.project_id,
            "status": self.status, "progress": round(self.progress, 4),
            "label": self.label, "result": self.result, "error": self.error,
            "steps": self.steps[-40:],
        }


class JobManager:
    """Un seul job lourd à la fois par projet: on évite de saturer le CPU."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, kind: str, project_id: str | None = None) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, project_id=project_id)
        with self._lock:
            self._jobs[job.id] = job
            # Purge des vieux jobs terminés pour ne pas fuir en mémoire.
            finished = [j for j in self._jobs.values() if j.status in {"done", "error", "cancelled"}]
            for old in sorted(finished, key=lambda j: j.id)[:-40]:
                self._jobs.pop(old.id, None)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def active_for(self, project_id: str) -> Job | None:
        return next(
            (j for j in self._jobs.values()
             if j.project_id == project_id and j.status in {"pending", "running"}),
            None,
        )

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status not in {"pending", "running"}:
            return False
        job._cancel.set()
        job.label = "Annulation demandée…"
        return True

    def run(self, job: Job, target: Callable[[Job, Callable[[float, str], None]], Any]) -> Job:
        """Exécute `target` dans un thread. `target(job, progress)`."""

        def progress(frac: float, label: str = "") -> None:
            if job._cancel.is_set():
                raise JobCancelled()
            job.progress = max(0.0, min(float(frac), 1.0))
            if label and label != job.label:
                job.label = label
                job.steps.append({"at": round(job.progress, 3), "label": label})

        def wrapper() -> None:
            job.status = "running"
            try:
                job.result = target(job, progress)
                job.status = "done"
                job.progress = 1.0
                job.label = job.label or "Terminé"
            except JobCancelled:
                job.status = "cancelled"
                job.label = "Annulé"
            except Exception as exc:
                job.status = "error"
                job.error = str(exc) or exc.__class__.__name__
                job.label = "Erreur"
                traceback.print_exc()

        threading.Thread(target=wrapper, name=f"job-{job.kind}", daemon=True).start()
        return job


class JobCancelled(Exception):
    pass


manager = JobManager()

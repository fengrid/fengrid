"""Task scheduler for long-running API jobs.

Long operations (ingest, export, backup, restore, scans, watch runs,
DB admin) are queued here and executed on worker threads. Every job gets
a stable id; clients poll `GET /api/v1/jobs/{id}` for state and result.
The scheduler is deliberately small: a FIFO queue, N worker threads, and
an in-memory registry (jobs are transient request work, not persisted
state — a restart simply drops finished entries).
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
import uuid
from typing import Any, Callable

# terminal states a job may reach
QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"


class Job:
    __slots__ = ("id", "kind", "state", "created", "started", "finished",
                 "progress", "result", "error", "_cancel")

    def __init__(self, kind: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.state = QUEUED
        self.created = time.time()
        self.started = 0.0
        self.finished = 0.0
        self.progress: tuple[int, int] | None = None
        self.result: dict | None = None
        self.error: str | None = None
        self._cancel = False

    def to_dict(self) -> dict:
        d = {"id": self.id, "kind": self.kind, "state": self.state,
             "created": self.created, "started": self.started,
             "finished": self.finished, "error": self.error}
        if self.progress:
            d["progress"] = {"done": self.progress[0],
                             "total": self.progress[1]}
        return d


class TaskScheduler:
    def __init__(self, workers: int = 3, keep_done: int = 100):
        self._queue: queue.Queue[tuple[Job, Callable[..., Any]]] = queue.Queue()
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._keep_done = keep_done
        self._stop = threading.Event()
        self._workers = [
            threading.Thread(target=self._worker, daemon=True,
                             name=f"fengrid-api-worker-{i}")
            for i in range(max(1, workers))]
        for w in self._workers:
            w.start()

    # ------------------------------------------------------------- public
    def submit(self, kind: str, fn, *args, **kwargs) -> Job:
        """Queue fn(*args, **kwargs) as a job; returns the Job immediately."""
        job = Job(kind)
        with self._lock:
            self._jobs[job.id] = job
            # prune oldest finished jobs so the registry stays bounded
            done = sorted((j for j in self._jobs.values()
                           if j.state in (DONE, FAILED)),
                          key=lambda j: j.finished)
            while len(done) > self._keep_done:
                self._jobs.pop(done.pop(0).id, None)
        self._queue.put((job, lambda: fn(*args, **kwargs)))
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self, active_only: bool = False) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: -j.created)
        if active_only:
            jobs = [j for j in jobs if j.state in (QUEUED, RUNNING)]
        return [j.to_dict() for j in jobs]

    def cancel(self, job_id: str) -> bool:
        """Best-effort cooperative cancel: sets the flag long jobs can
        check via should_stop(); queued jobs refuse to start."""
        job = self.get(job_id)
        if job is None:
            return False
        job._cancel = True
        return True

    def shutdown(self) -> None:
        self._stop.set()
        try:
            while True:
                self._queue.get_nowait()
                self._queue.task_done()
        except queue.Empty:
            pass

    def should_stop(self, job: Job):
        """Callable passed to long jobs so they can honour cancel()."""
        return lambda: job._cancel

    def progress(self, job: Job):
        """Progress callback factories matching core signatures."""
        def cb(done: int, total: int) -> None:
            job.progress = (int(done), int(total))
        return cb

    # ------------------------------------------------------------ workers
    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                job, fn = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if job._cancel:
                job.state = FAILED
                job.error = "cancelled before start"
                job.finished = time.time()
                self._queue.task_done()
                continue
            job.state = RUNNING
            job.started = time.time()
            try:
                job.result = fn()
                job.state = FAILED if (
                    isinstance(job.result, dict)
                    and job.result.get("error")) else DONE
            except Exception as e:                     # noqa: BLE001
                job.state = FAILED
                job.error = f"{type(e).__name__}: {e}"
                traceback.print_exc()
            finally:
                job.finished = time.time()
                self._queue.task_done()

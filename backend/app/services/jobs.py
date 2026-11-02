"""Background job queue and worker.

Jobs are rows in the ``jobs`` table.  Handlers are plain Python functions
registered by ``kind``.  The worker is a small thread pool that claims
pending rows (optimistic status transition, so several workers/processes are
safe), executes the handler, and records success/failure with retries.

Tests (and synchronous CLI usage) can run a job immediately via
``execute_job_now`` without starting the worker.
"""
from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.database import session_scope
from app.models import Job, User, utcnow
from app.services import audit as audit_service
from app.services.storage import ensure_storage_dirs

log = logging.getLogger("lakewatch.jobs")

Handler = Callable[["JobContext"], dict]
_HANDLERS: dict[str, Handler] = {}
_lock = threading.Lock()
_stop_event = threading.Event()
_threads: list[threading.Thread] = []


def register_handler(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        with _lock:
            _HANDLERS[kind] = fn
        return fn

    return deco


class JobContext:
    """Passed to handlers: progress reporting + request metadata."""

    def __init__(self, job: Job, db):
        self.job = job
        self.db = db

    @property
    def params(self) -> dict:
        return self.job.params_json or {}

    @property
    def actor(self) -> User | None:
        if self.job.requested_by_id is None:
            return None
        return self.db.get(User, self.job.requested_by_id)

    def progress(self, fraction: float, message: str = "") -> None:
        self.job.progress = max(0.0, min(1.0, float(fraction)))
        if message:
            self.job.message = message[:500]
        self.job.updated_at = utcnow()
        self.db.commit()

    def set_result(self, result: dict) -> None:
        self.job.result_json = result
        self.db.commit()


def enqueue(
    db,
    *,
    kind: str,
    params: dict[str, Any],
    requested_by_id: int | None = None,
    dedupe_key: str | None = None,
    max_attempts: int | None = None,
) -> Job:
    """Create a pending job.  Returns the existing job when a duplicate is
    still pending/running (dedupe)."""
    if dedupe_key:
        existing = db.execute(select(Job).where(Job.dedupe_key == dedupe_key)).scalar_one_or_none()
        if existing is not None and existing.status in ("pending", "running"):
            return existing
        if existing is not None:
            # previous run finished: clear the key so a new run can be queued
            existing.dedupe_key = None
            db.flush()
    job = Job(
        kind=kind,
        status="pending",
        params_json=params,
        requested_by_id=requested_by_id,
        dedupe_key=dedupe_key,
        max_attempts=max_attempts or settings.jobs_max_attempts,
    )
    db.add(job)
    db.flush()
    return job


def claim_next(db) -> Job | None:
    """Atomically claim one pending job (safe with multiple workers)."""
    job = db.execute(
        select(Job).where(Job.status == "pending").order_by(Job.id.asc()).limit(1)
    ).scalar_one_or_none()
    if job is None:
        return None
    result = db.execute(
        Job.__table__.update()
        .where(Job.id == job.id, Job.status == "pending")
        .values(status="running", started_at=utcnow(), updated_at=utcnow(), attempts=Job.attempts + 1)
    )
    db.commit()
    if result.rowcount != 1:
        return None
    db.refresh(job)
    return job


def execute_job_now(db, job_id: int) -> Job:
    """Run a single job synchronously (tests, CLI)."""
    job = db.get(Job, job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")
    if job.status not in ("pending", "failed", "running"):
        return job
    job.status = "running"
    job.started_at = job.started_at or utcnow()
    job.updated_at = utcnow()
    job.attempts += 1
    db.commit()
    _run_handler(db, job)
    db.refresh(job)
    return job


def _run_handler(db, job: Job) -> None:
    handler = _HANDLERS.get(job.kind)
    if handler is None:  # pragma: no cover - programming error
        job.status = "failed"
        job.error = f"No handler registered for kind '{job.kind}'"
        job.finished_at = utcnow()
        db.commit()
        return

    ctx = JobContext(job, db)
    try:
        audit_service.record(
            action=f"job.{job.kind}.start",
            resource_type="job",
            resource_id=job.id,
            actor_id=job.requested_by_id,
            message=f"{job.kind} job started (attempt {job.attempts})",
            details={"params": job.params_json},
        )
        result = handler(ctx)
        job.status = "succeeded"
        job.progress = 1.0
        job.error = None
        job.result_json = result if isinstance(result, dict) else (job.result_json or {})
        job.message = job.message or "completed"
        job.finished_at = utcnow()
        job.updated_at = utcnow()
        job.dedupe_key = None
        db.commit()
        audit_service.record(
            action=f"job.{job.kind}.success",
            resource_type="job",
            resource_id=job.id,
            actor_id=job.requested_by_id,
            message=f"{job.kind} job completed",
            details={"result": _summarize(job.result_json)},
        )
    except Exception as exc:  # noqa: BLE001 - job boundary
        db.rollback()
        log.warning("Job %s (%s) failed: %s", job.id, job.kind, exc)
        db.refresh(job)
        job.error = f"{type(exc).__name__}: {exc}"[:8000]
        job.message = "failed"
        job.finished_at = utcnow()
        job.updated_at = utcnow()
        retrying = job.attempts < job.max_attempts
        if retrying:
            job.status = "pending"       # will be picked up again by the worker
            job.started_at = None
            job.message = f"attempt {job.attempts} failed; retrying"
        else:
            job.status = "failed"
        job.result_json = {"traceback": traceback.format_exc()[-3000:]} if settings.environment != "production" else None
        db.commit()
        audit_service.record(
            action=f"job.{job.kind}.failure",
            resource_type="job",
            resource_id=job.id,
            outcome="failure",
            actor_id=job.requested_by_id,
            message=f"{job.kind} job failed: {str(exc)[:300]}",
            details={"attempts": job.attempts, "will_retry": retrying},
        )


def _summarize(result: dict | None) -> dict:
    if not isinstance(result, dict):
        return {}
    return {k: v for k, v in result.items() if not str(k).startswith("_")}


def cancel_job(db, job: Job) -> Job:
    if job.status in ("succeeded", "failed", "canceled"):
        return job
    job.status = "canceled"
    job.finished_at = utcnow()
    job.message = "canceled by user"
    db.flush()
    return job


def retry_job(db, job: Job) -> Job:
    if job.status not in ("failed", "canceled"):
        return job
    job.status = "pending"
    job.attempts = 0
    job.error = None
    job.finished_at = None
    job.started_at = None
    job.message = "queued for retry"
    db.flush()
    return job


def _worker_loop(poll_interval: float) -> None:
    while not _stop_event.is_set():
        try:
            with session_scope() as db:
                job = claim_next(db)
                if job is None:
                    pass
                else:
                    _run_handler(db, job)
        except Exception:  # pragma: no cover - defensive
            log.exception("worker iteration failed")
            continue
        _stop_event.wait(poll_interval)


def start_workers() -> None:
    if not settings.jobs_enabled or _threads:
        return
    ensure_storage_dirs()
    _stop_event.clear()
    for i in range(max(1, settings.jobs_worker_count)):
        t = threading.Thread(target=_worker_loop, args=(settings.jobs_poll_interval_seconds,), name=f"job-worker-{i}", daemon=True)
        t.start()
        _threads.append(t)
    log.info("Started %s job worker thread(s)", len(_threads))


def stop_workers() -> None:
    _stop_event.set()
    for t in _threads:
        t.join(timeout=5)
    _threads.clear()

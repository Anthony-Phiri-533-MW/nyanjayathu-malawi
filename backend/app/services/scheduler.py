"""In-process daily scheduler.

A single daemon thread checks every ``scheduler_tick_seconds`` whether the
configured UTC time has passed.  The run itself is recorded in
``scheduler_runs`` (unique per day) and executed as a normal background job, so
it inherits the queue's retry and audit behaviour.

Why not APScheduler?  The project already owns a database-backed job queue;
one more thread plus a unique row gives the same guarantee with no extra
dependency, and the run log is useful evidence for the thesis.
"""
from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import session_scope
from app.models import DataSource, SchedulerRun, StudyArea, User, utcnow
from app.services.jobs import enqueue

log = logging.getLogger("lakewatch.scheduler")

_stop = threading.Event()
_thread: threading.Thread | None = None

STALE_RUN_AFTER = timedelta(hours=3)


def _scheduled_time(now: datetime) -> datetime:
    return now.replace(
        hour=settings.scheduler_hour_utc,
        minute=settings.scheduler_minute_utc,
        second=0,
        microsecond=0,
    )


def is_due(now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    return settings.scheduler_enabled and now >= _scheduled_time(now)


def seconds_until_next(now: datetime | None = None) -> float:
    now = now or datetime.now(UTC)
    target = _scheduled_time(now)
    if target <= now:
        target += timedelta(days=1)
    return max(0.0, (target - now).total_seconds())


def start_daily_run(
    *,
    now: datetime | None = None,
    trigger: str = "schedule",
    actor: User | None = None,
    source_ids: list[int] | None = None,
    study_area_ids: list[int] | None = None,
    force: bool = False,
) -> dict:
    """Record today's run and enqueue the ``daily_pipeline`` job.

    Idempotent: a second call for the same UTC date returns ``skipped`` unless
    ``force`` is set.  A stale ``running`` row (process died mid-run) is failed
    automatically and may be retried the same day.
    """
    now = now or datetime.now(UTC)
    run_date = now.date()
    with session_scope() as db:
        run = db.execute(
            select(SchedulerRun).where(SchedulerRun.run_date == run_date)
        ).scalar_one_or_none()

        if run is not None:
            stale = run.status == "running" and (utcnow() - run.started_at) > STALE_RUN_AFTER
            if stale:
                run.status = "failed"
                run.error = "stale run recovered by scheduler"
                run.finished_at = utcnow()
                db.commit()
            elif run.status == "running":
                return {
                    "status": "skipped",
                    "reason": "a daily run is already in progress",
                    "run_id": run.id,
                    "job_id": run.job_id,
                }
            elif trigger == "schedule" and not force:
                return {
                    "status": "skipped",
                    "reason": f"a run for {run_date} already exists",
                    "run_id": run.id,
                    "job_id": run.job_id,
                }

        if run is None:
            run = SchedulerRun(run_date=run_date, status="running", trigger=trigger, started_at=utcnow())
            db.add(run)
            try:
                db.flush()
            except IntegrityError:
                # Another instance won the race; let it own the run.
                db.rollback()
                return {"status": "skipped", "reason": "another instance started today's run"}
        else:
            run.status = "running"
            run.trigger = trigger
            run.started_at = utcnow()
            run.finished_at = None
            run.error = None
            run.summary_json = None

        job = enqueue(
            db,
            kind="daily_pipeline",
            params={
                "run_date": run_date.isoformat(),
                "trigger": trigger,
                "run_id": run.id,
                "source_ids": source_ids or [],
                "study_area_ids": study_area_ids or [],
            },
            requested_by_id=actor.id if actor else None,
            dedupe_key=f"daily-pipeline:{run_date.isoformat()}",
            max_attempts=settings.jobs_max_attempts,
        )
        run.job_id = job.id
        db.commit()
        log.info("Scheduled daily pipeline for %s (job %s, trigger=%s)", run_date, job.id, trigger)
        return {"status": "queued", "run_id": run.id, "job_id": job.id, "run_date": run_date.isoformat()}


def list_runs(db, *, limit: int = 30) -> list[SchedulerRun]:
    return list(
        db.execute(
            select(SchedulerRun).order_by(SchedulerRun.run_date.desc()).limit(limit)
        ).scalars()
    )


def status(db) -> dict:
    now = datetime.now(UTC)
    last = db.execute(
        select(SchedulerRun).order_by(SchedulerRun.run_date.desc()).limit(1)
    ).scalar_one_or_none()
    scheduled_sources = db.execute(
        select(func.count()).select_from(DataSource).where(
            DataSource.is_enabled.is_(True), DataSource.schedule_enabled.is_(True)
        )
    ).scalar_one()
    return {
        "enabled": settings.scheduler_enabled,
        "jobs_enabled": settings.jobs_enabled,
        "scheduled_time_utc": f"{settings.scheduler_hour_utc:02d}:{settings.scheduler_minute_utc:02d}",
        "interval_seconds": settings.scheduler_tick_seconds,
        "next_run_at": (now + timedelta(seconds=seconds_until_next(now))).isoformat(),
        "due": is_due(now),
        "scheduled_sources": int(scheduled_sources),
        "study_areas": int(db.execute(select(func.count()).select_from(StudyArea)).scalar_one()),
        "last_run": _run_dict(last) if last is not None else None,
    }


def _run_dict(run: SchedulerRun) -> dict:
    return {
        "id": run.id,
        "run_date": run.run_date.isoformat(),
        "status": run.status,
        "trigger": run.trigger,
        "job_id": run.job_id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "error": run.error,
        "summary": run.summary_json,
    }


def _loop() -> None:
    while not _stop.is_set():
        try:
            if is_due():
                result = start_daily_run(trigger="schedule")
                if result["status"] == "queued":
                    log.info("Daily pipeline queued: %s", result)
        except Exception:  # noqa: BLE001 - the scheduler must never die
            log.exception("Scheduler iteration failed")
        _stop.wait(max(5.0, settings.scheduler_tick_seconds))


def start_scheduler() -> None:
    global _thread
    if not settings.scheduler_enabled or _thread is not None:
        return
    if not settings.jobs_enabled:
        log.warning("Scheduler is enabled but jobs are disabled; no work will execute")
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="daily-scheduler", daemon=True)
    _thread.start()
    log.info(
        "Started daily scheduler (target %02d:%02d UTC, tick %.0fs)",
        settings.scheduler_hour_utc,
        settings.scheduler_minute_utc,
        settings.scheduler_tick_seconds,
    )


def stop_scheduler() -> None:
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=5)
    _thread = None

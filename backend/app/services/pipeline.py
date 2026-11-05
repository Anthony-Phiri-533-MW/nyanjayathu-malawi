"""Daily end-to-end pipeline.

Matches the second sequence diagram:

    Scheduler -> ingestion -> indicators -> ML forecasts -> threshold alerts -> DB -> REST API

The scheduler enqueues a single ``daily_pipeline`` job; this module executes it
in order so a forecast can never be trained on data that was not downloaded
first.  Every stage is isolated: one failing data source does not prevent the
other sources, the indicator stage or the forecast stage from running.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFoundError
from app.indicators.base import Selection, select_datasets
from app.models import DataSource, Dataset, IngestionJob, SchedulerRun, StudyArea, User, utcnow
from app.schemas.disaster import EvaluateRequest
from app.schemas.research import IngestionJobCreate
from app.services import disaster as disaster_service
from app.services import forecasting
from app.services import indicators as indicators_service
from app.services import ingestion as ingestion_service
from app.services.jobs import JobContext, execute_job_now, register_handler

log = logging.getLogger("lakewatch.pipeline")

# Which indicator computers can run from the capabilities a downloaded dataset
# declares.  The orchestrator resolves dependencies (e.g. water_extent_change
# needs water_extent) itself.
CAPABILITY_INDICATORS: dict[str, list[str]] = {
    "optical": [
        "water_extent",
        "water_extent_change",
        "chlorophyll_a_proxy",
        "turbidity_proxy",
    ],
    "thermal": ["surface_water_temperature"],
    "altimetry": ["water_level_altimetry"],
    "precipitation": ["rainfall_summary", "rainfall_anomaly"],
    "temperature": ["temperature_summary", "temperature_anomaly"],
}


def indicator_keys_for(capabilities: set[str]) -> list[str]:
    keys: list[str] = []
    for capability in capabilities:
        for key in CAPABILITY_INDICATORS.get(capability, []):
            if key not in keys:
                keys.append(key)
    return keys


def _default_area(db: Session) -> StudyArea | None:
    area = db.execute(
        select(StudyArea).where(StudyArea.is_default.is_(True)).limit(1)
    ).scalar_one_or_none()
    if area is not None:
        return area
    return db.execute(select(StudyArea).order_by(StudyArea.id.asc()).limit(1)).scalar_one_or_none()


def run_daily_pipeline(
    db: Session,
    *,
    run_date: date | None = None,
    trigger: str = "schedule",
    source_ids: list[int] | None = None,
    study_area_ids: list[int] | None = None,
    actor: User | None = None,
    progress=None,
) -> dict[str, Any]:
    """Download, compute, forecast and evaluate for one UTC day."""
    run_date = run_date or utcnow().date()
    default_area = _default_area(db)
    if default_area is None:
        raise NotFoundError("No study area is configured")

    def report(fraction: float, message: str = "") -> None:
        if progress:
            progress(max(0.0, min(1.0, fraction)), message)

    stmt = select(DataSource).where(DataSource.is_enabled.is_(True))
    if source_ids:
        stmt = stmt.where(DataSource.id.in_(source_ids))
    else:
        stmt = stmt.where(DataSource.schedule_enabled.is_(True))
    sources = list(db.execute(stmt.order_by(DataSource.id.asc())).scalars())

    allowed_areas = set(study_area_ids or [])
    summary: dict[str, Any] = {
        "run_date": run_date.isoformat(),
        "trigger": trigger,
        "sources": [],
        "indicators": {},
        "forecasts": None,
        "alerts": None,
    }

    # ------------------------------------------------------------- ingestion
    affected_areas: set[int] = set()
    created_dataset_ids: list[int] = []
    total_sources = max(1, len(sources))
    for index, ds in enumerate(sources):
        base = 0.05 + 0.50 * (index / total_sources)
        span = 0.50 / total_sources
        already_done = (
            trigger == "schedule"
            and ds.last_scheduled_at is not None
            and ds.last_scheduled_at.date() >= run_date
        )
        if already_done:
            summary["sources"].append(
                {"id": ds.id, "name": ds.name, "status": "skipped", "reason": "already scheduled today"}
            )
            continue

        area = default_area
        if allowed_areas:
            area = db.get(StudyArea, min(allowed_areas)) or default_area
            if area is None:
                continue
        lookback = max(1, int(ds.schedule_lookback_days or settings.scheduler_lookback_days))
        start = run_date - timedelta(days=lookback)
        record: dict[str, Any] = {"id": ds.id, "name": ds.name, "status": "running"}
        try:
            report(base, f"downloading {ds.name} ({start} to {run_date})")
            job, _ing = ingestion_service.start_ingestion(
                db,
                payload=IngestionJobCreate(
                    data_source_id=ds.id,
                    study_area_id=area.id,
                    start_date=start,
                    end_date=run_date,
                ),
                actor=actor,
            )
            db.commit()
            job = execute_job_now(db, job.id)
            record["job_id"] = job.id
            record["job_status"] = job.status

            datasets = list(
                db.execute(select(Dataset).where(Dataset.ingestion_job_id == _ing.id)).scalars()
            )
            record["datasets"] = len(datasets)
            if datasets:
                created_dataset_ids.extend(d.id for d in datasets)
                affected_areas.update(d.study_area_id for d in datasets if d.study_area_id)
                record["status"] = "succeeded"
                record["dataset_ids"] = [d.id for d in datasets]
                record["capabilities"] = sorted(
                    {
                        cap
                        for d in datasets
                        for cap in (d.metadata_json or {}).get("capabilities", [])
                    }
                )
            else:
                record["status"] = "failed"
                record["error"] = job.error or "no datasets were stored"
        except Exception as exc:  # noqa: BLE001 - per-source boundary
            db.rollback()
            record["status"] = "failed"
            record["error"] = f"{type(exc).__name__}: {exc}"[:600]
            log.warning("Scheduled ingestion failed for %s: %s", ds.name, exc)
        finally:
            try:
                ds.last_scheduled_at = utcnow()
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
        summary["sources"].append(record)
        report(base + span, f"{ds.name}: {record['status']}")

    if not affected_areas and created_dataset_ids:
        affected_areas = set(
            db.execute(
                select(Dataset.study_area_id).where(Dataset.id.in_(created_dataset_ids))
            ).scalars()
        )
    if not affected_areas:
        affected_areas = {default_area.id}

    # ------------------------------------------------------------ indicators
    report(0.56, "computing indicators")
    area_ids = sorted(a for a in affected_areas if a)
    indicator_report: dict[str, Any] = {}
    for position, area_id in enumerate(area_ids):
        db_rows = list(
            db.execute(select(Dataset).where(Dataset.id.in_(created_dataset_ids))).scalars()
        ) if created_dataset_ids else []
        capability_set = {
            cap for d in db_rows if d.study_area_id == area_id
            for cap in (d.metadata_json or {}).get("capabilities", [])
        }
        keys = indicator_keys_for(capability_set)
        if not keys:
            indicator_report[str(area_id)] = {"status": "skipped", "reason": "no computable indicators"}
            continue
        selection: Selection = select_datasets(
            db,
            dataset_ids=[d.id for d in db_rows if d.study_area_id == area_id],
            study_area_id=area_id,
        )
        if not selection.datasets:
            indicator_report[str(area_id)] = {"status": "skipped", "reason": "no datasets"}
            continue
        try:
            result = indicators_service.compute_indicators(
                db,
                keys=keys,
                selection=selection,
                actor=actor,
                progress=lambda f, m="", _p=position: report(
                    0.56 + 0.18 * ((_p + f) / max(1, len(area_ids))), m
                ),
            )
            indicator_report[str(area_id)] = {"status": "succeeded", **result}
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            indicator_report[str(area_id)] = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}"[:600],
            }
            log.warning("Indicator stage failed for area %s: %s", area_id, exc)
    summary["indicators"] = indicator_report

    # ------------------------------------------------------------- forecasts
    if settings.forecast_enabled:
        report(0.76, "training and validating short-term forecasts")
        try:
            summary["forecasts"] = forecasting.run_forecasts(
                db, study_area_ids=area_ids, actor=actor
            )
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            summary["forecasts"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:600]}
            log.exception("Forecast stage failed")
    else:
        summary["forecasts"] = {"status": "disabled"}

    # ---------------------------------------------------------------- alerts
    report(0.94, "evaluating thresholds")
    try:
        evaluated = disaster_service.evaluate(
            db,
            payload=EvaluateRequest(include_provisional=True, dry_run=False),
            actor=actor,
        )
        db.commit()
        summary["alerts"] = evaluated.model_dump()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        summary["alerts"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:600]}
        log.exception("Alert evaluation failed")

    report(1.0, "daily pipeline complete")
    return summary


@register_handler("daily_pipeline")
def handle_daily_pipeline(ctx: JobContext) -> dict:
    params = ctx.params
    run_id = params.get("run_id")
    run = ctx.db.get(SchedulerRun, int(run_id)) if run_id else None
    try:
        summary = run_daily_pipeline(
            ctx.db,
            run_date=date.fromisoformat(params["run_date"]) if params.get("run_date") else None,
            trigger=str(params.get("trigger") or "schedule"),
            source_ids=[int(i) for i in params.get("source_ids") or []] or None,
            study_area_ids=[int(i) for i in params.get("study_area_ids") or []] or None,
            actor=ctx.actor,
            progress=ctx.progress,
        )
    except Exception as exc:
        if run is not None:
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"[:8000]
            run.finished_at = utcnow()
            ctx.db.commit()
        raise
    if run is not None:
        run.status = "succeeded"
        run.finished_at = utcnow()
        run.summary_json = summary
        ctx.db.commit()
    return summary

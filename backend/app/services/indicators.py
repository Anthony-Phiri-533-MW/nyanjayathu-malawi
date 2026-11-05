"""Indicator computation jobs and result browsing."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import count_query
from app.core.errors import NotFoundError, UnprocessableError
from app.indicators import compute_indicator, indicator_keys
from app.indicators.base import Selection, select_datasets
from app.models import Dataset, IndicatorDefinition, IndicatorResult, StudyArea, User
from app.schemas.research import IndicatorComputeCreate
from app.services import audit as audit_service
from app.services.jobs import JobContext, enqueue, register_handler


def _selection(payload: IndicatorComputeCreate, db: Session) -> Selection:
    if payload.dataset_ids:
        found = {
            row for row in db.execute(
                select(Dataset.id).where(Dataset.id.in_(payload.dataset_ids))
            ).scalars()
        }
        missing = sorted(set(payload.dataset_ids) - found)
        if missing:
            raise NotFoundError(f"Datasets not found: {missing}")
    if payload.study_area_id is not None and db.get(StudyArea, payload.study_area_id) is None:
        raise NotFoundError(f"Study area {payload.study_area_id} not found")
    return select_datasets(
        db,
        dataset_ids=payload.dataset_ids,
        study_area_id=payload.study_area_id,
        start=payload.start_date,
        end=payload.end_date,
    )


def start_indicator_compute(
    db: Session, *, payload: IndicatorComputeCreate, actor: User
) -> Any:
    unknown = [k for k in payload.indicator_keys if k not in indicator_keys()]
    if unknown:
        raise UnprocessableError(
            f"Unknown indicator key(s): {unknown}", details={"supported": indicator_keys()}
        )
    selection = _selection(payload, db)
    if not selection.datasets:
        raise UnprocessableError(
            "The selection matched no datasets; widen the dates or pick a different study area"
        )
    digest = hashlib.sha256(
        json.dumps(
            {
                "keys": sorted(payload.indicator_keys),
                "study_area_id": payload.study_area_id,
                "dataset_ids": sorted(payload.dataset_ids or []),
                "start": str(payload.start_date),
                "end": str(payload.end_date),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:16]
    job = enqueue(
        db,
        kind="indicator",
        params={
            "indicator_keys": payload.indicator_keys,
            "study_area_id": payload.study_area_id,
            "dataset_ids": payload.dataset_ids,
            "start_date": payload.start_date.isoformat() if payload.start_date else None,
            "end_date": payload.end_date.isoformat() if payload.end_date else None,
        },
        requested_by_id=actor.id,
        dedupe_key=f"indicator:{digest}",
    )
    db.flush()
    audit_service.record(
        action="indicator.request",
        resource_type="job",
        resource_id=job.id,
        actor=actor,
        db=db,
        message=f"Requested indicator computation: {', '.join(payload.indicator_keys)}",
        details={
            "indicator_keys": payload.indicator_keys,
            "dataset_ids": payload.dataset_ids,
            "study_area_id": payload.study_area_id,
        },
    )
    return job


@register_handler("indicator")
def handle_indicator_job(ctx: JobContext) -> dict:
    params = ctx.params
    keys = [str(k) for k in params.get("indicator_keys") or []]
    if not keys:
        raise UnprocessableError("indicator job is missing indicator_keys")

    def parse(value: Any) -> date | None:
        return date.fromisoformat(value) if value else None

    selection = select_datasets(
        ctx.db,
        dataset_ids=[int(i) for i in params.get("dataset_ids") or []] or None,
        study_area_id=params.get("study_area_id"),
        start=parse(params.get("start_date")),
        end=parse(params.get("end_date")),
    )
    if not selection.datasets:
        raise UnprocessableError("no datasets matched the stored indicator job selection")
    return compute_indicators(
        ctx.db,
        keys=keys,
        selection=selection,
        params=dict(params.get("params") or {}),
        actor=ctx.actor,
        job_id=ctx.job.id,
        progress=ctx.progress,
    )


def compute_indicators(
    db: Session,
    *,
    keys: list[str],
    selection: Selection,
    params: dict[str, Any] | None = None,
    actor: User | None = None,
    job_id: int | None = None,
    progress=None,
) -> dict:
    """Run a list of indicator computers over one selection.

    Shared by the background job handler and the daily pipeline so both paths
    produce identical rows, audit entries and progress semantics.
    """
    params = params or {}
    per_key: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    total = len(keys)

    def report_base(fraction: float, message: str = "") -> None:
        if progress:
            progress(fraction, message)

    for index, key in enumerate(keys):
        base = index / total
        span = 1.0 / total

        def report(fraction: float, message: str = "", _base=base, _span=span) -> None:
            report_base(_base + _span * max(0.0, min(1.0, fraction)), message)

        try:
            results = compute_indicator(
                db,
                key=key,
                selection=selection,
                params=dict(params),
                actor=actor,
                job_id=job_id,
                progress=report,
            )
            db.commit()
            per_key[key] = {
                "result_count": len(results),
                "result_ids": [r.id for r in results],
                "null_values": sum(1 for r in results if r.value is None),
            }
        except Exception as exc:  # isolate per-indicator failures
            db.rollback()
            errors[key] = f"{type(exc).__name__}: {exc}"[:600]
            db.commit()
            report(base + span, f"{key} failed")

    if not per_key:
        raise UnprocessableError(
            "every indicator in this job failed: "
            + "; ".join(f"{k}: {v}" for k, v in errors.items())
        )
    audit_service.record(
        action="indicator.complete",
        resource_type="job",
        resource_id=job_id,
        actor=actor,
        db=db,
        message=f"Indicator computation completed ({len(per_key)}/{len(keys)})",
        details={"per_key": per_key, "errors": errors},
    )
    return {
        "indicators": per_key,
        "errors": errors,
        "study_area_id": selection.study_area.id if selection.study_area else None,
        "dataset_count": len(selection.datasets),
    }


# ------------------------------------------------------------------ browsing
def list_definitions(db: Session) -> list[IndicatorDefinition]:
    return list(
        db.execute(
            select(IndicatorDefinition).order_by(
                IndicatorDefinition.category.asc(), IndicatorDefinition.name.asc()
            )
        ).scalars()
    )


def list_results(
    db: Session,
    *,
    page: int = 1,
    size: int = 20,
    indicator_key: str | None = None,
    study_area_id: int | None = None,
    dataset_id: int | None = None,
    quality_flag: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> tuple[list[IndicatorResult], int]:
    stmt = select(IndicatorResult)
    if indicator_key:
        stmt = stmt.where(IndicatorResult.indicator_key == indicator_key)
    if study_area_id is not None:
        stmt = stmt.where(IndicatorResult.study_area_id == study_area_id)
    if dataset_id is not None:
        stmt = stmt.where(IndicatorResult.dataset_id == dataset_id)
    if quality_flag:
        stmt = stmt.where(IndicatorResult.quality_flag == quality_flag)
    if start is not None:
        stmt = stmt.where(IndicatorResult.observed_end >= start)
    if end is not None:
        stmt = stmt.where(IndicatorResult.observed_start <= end)
    total = count_query(stmt, db)
    rows = list(
        db.execute(
            stmt.order_by(
                IndicatorResult.observed_start.desc(), IndicatorResult.id.desc()
            )
            .offset((page - 1) * size)
            .limit(size)
        ).scalars()
    )
    return rows, total


def get_result(db: Session, result_id: int) -> IndicatorResult:
    row = db.get(IndicatorResult, result_id)
    if row is None:
        raise NotFoundError(f"Indicator result {result_id} not found")
    return row

"""Forecasting API: trained models, blocked-validation metrics and run control."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.serializers import (
    forecast_run_out,
    ml_model_out,
    model_evaluation_out,
    page_response,
)
from app.core.database import count_query, get_db
from app.core.deps import CurrentUser, require_permissions
from app.core.errors import NotFoundError
from app.models import ForecastRun, MLModel, ModelEvaluation, StudyArea
from app.schemas.common import Page
from app.schemas.ml import (
    ForecastRunOut,
    ForecastRunQueued,
    ForecastRunRequest,
    MLModelOut,
    ModelEvaluationOut,
)
from app.services import forecasting, scheduler as scheduler_service
from app.services.jobs import enqueue

router = APIRouter(prefix="/forecasts", tags=["forecasting"])

Read = Annotated[set[str], Depends(require_permissions("research.indicators.read"))]
Run = Annotated[set[str], Depends(require_permissions("research.forecasts.run"))]


@router.get("/models", response_model=Page[MLModelOut])
def list_models(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
    indicator_key: str | None = None,
    study_area_id: int | None = None,
    active_only: bool = True,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
) -> Page[MLModelOut]:
    stmt = select(MLModel)
    if indicator_key:
        stmt = stmt.where(MLModel.indicator_key == indicator_key)
    if study_area_id is not None:
        stmt = stmt.where(MLModel.study_area_id == study_area_id)
    if active_only:
        stmt = stmt.where(MLModel.is_active.is_(True))
    total = count_query(stmt, db)
    rows = list(
        db.execute(
            stmt.order_by(MLModel.trained_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        ).scalars()
    )
    return page_response([ml_model_out(r) for r in rows], total, page, size)


@router.get("/evaluations", response_model=Page[ModelEvaluationOut])
def list_evaluations(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
    model_id: int | None = None,
    indicator_key: str | None = None,
    study_area_id: int | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
) -> Page[ModelEvaluationOut]:
    stmt = select(ModelEvaluation)
    if model_id is not None:
        stmt = stmt.where(ModelEvaluation.model_id == model_id)
    if indicator_key:
        stmt = stmt.where(ModelEvaluation.indicator_key == indicator_key)
    if study_area_id is not None:
        stmt = stmt.where(ModelEvaluation.study_area_id == study_area_id)
    total = count_query(stmt, db)
    rows = list(
        db.execute(
            stmt.order_by(ModelEvaluation.model_id.desc(), ModelEvaluation.fold.asc())
            .offset((page - 1) * size)
            .limit(size)
        ).scalars()
    )
    return page_response([model_evaluation_out(r) for r in rows], total, page, size)


@router.get("/runs", response_model=Page[ForecastRunOut])
def list_runs(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
    indicator_key: str | None = None,
    study_area_id: int | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
) -> Page[ForecastRunOut]:
    stmt = select(ForecastRun)
    if indicator_key:
        stmt = stmt.where(ForecastRun.indicator_key == indicator_key)
    if study_area_id is not None:
        stmt = stmt.where(ForecastRun.study_area_id == study_area_id)
    if status_filter:
        stmt = stmt.where(ForecastRun.status == status_filter)
    total = count_query(stmt, db)
    rows = list(
        db.execute(
            stmt.order_by(ForecastRun.issued_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        ).scalars()
    )
    return page_response([forecast_run_out(r) for r in rows], total, page, size)


@router.post("/run", response_model=ForecastRunQueued)
def run_forecasts(
    payload: ForecastRunRequest,
    actor: CurrentUser,
    _perms: Run,
    db: Annotated[Session, Depends(get_db)],
) -> ForecastRunQueued:
    """Queue (or synchronously run) model training and forecasting."""
    if payload.study_area_ids:
        for area_id in payload.study_area_ids:
            if db.get(StudyArea, area_id) is None:
                raise NotFoundError("Study area not found", details={"id": area_id})

    if not payload.enqueue:
        detail = forecasting.run_forecasts(
            db,
            study_area_ids=payload.study_area_ids,
            indicator_keys=payload.indicator_keys,
            actor=actor,
            horizon=payload.horizon,
        )
        db.commit()
        return ForecastRunQueued(status="completed", detail=detail)

    key = (
        f"forecast:{','.join(str(i) for i in sorted(payload.study_area_ids or [])) or 'all'}:"
        f"{','.join(sorted(payload.indicator_keys or [])) or 'configured'}:"
        f"{payload.horizon or 'default'}:{datetime.utcnow().date().isoformat()}"
    )
    job = enqueue(
        db,
        kind="forecast",
        params={
            "study_area_ids": payload.study_area_ids or [],
            "indicator_keys": payload.indicator_keys or [],
            "horizon": payload.horizon,
        },
        requested_by_id=actor.id,
        dedupe_key=key,
    )
    db.commit()
    return ForecastRunQueued(status="queued", job_id=job.id)


@router.get("/status")
def forecast_status(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Configuration + coverage summary used by the dashboard."""
    models = db.execute(
        select(MLModel).where(MLModel.is_active.is_(True))
    ).scalars().all()
    return {
        "enabled": forecasting.settings.forecast_enabled,
        "algorithms": forecasting.available_algorithms(),
        "sklearn_available": forecasting.SKLEARN_AVAILABLE,
        "xgboost_available": forecasting.XGBOOST_AVAILABLE,
        "horizon_days": forecasting.settings.forecast_horizon_days,
        "min_points": forecasting.settings.forecast_min_points,
        "n_folds": forecasting.settings.forecast_n_folds,
        "interval": forecasting.settings.forecast_interval,
        "active_models": len(models),
        "scheduler": scheduler_service.status(db),
    }

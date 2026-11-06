"""Disaster Management: alerts, responses and forecast records."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.serializers import alert_detail_out, alert_out, forecast_out, page_response
from app.core.database import get_db
from app.core.deps import CurrentUser, require_permissions
from app.schemas.common import Page
from app.schemas.disaster import (
    AlertActionCreate,
    AlertDetailOut,
    AlertOut,
    EvaluateOut,
    EvaluateRequest,
    ForecastCreate,
    ForecastOut,
)
from app.services import disaster as service

router = APIRouter(prefix="/disaster", tags=["disaster"])

Read = Annotated[set[str], Depends(require_permissions("disaster.alerts.read"))]
Respond = Annotated[set[str], Depends(require_permissions("disaster.alerts.respond"))]
Evaluate = Annotated[set[str], Depends(require_permissions("disaster.evaluate.run"))]
# Recording a manual/external projection is distinct from running threshold
# evaluation. Accept legacy disaster.evaluate.run for compatibility.
RecordForecast = Annotated[
    set[str], Depends(require_permissions("disaster.forecasts.write", "disaster.evaluate.run"))
]


@router.get("/alerts", response_model=Page[AlertOut])
def list_alerts(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
    status_filter: str | None = Query(default=None, alias="status"),
    severity: str | None = None,
    kind: str | None = None,
    metric_source: str | None = None,
    indicator_key: str | None = None,
    study_area_id: int | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> Page[AlertOut]:
    rows, total = service.list_alerts(
        db,
        status_filter=status_filter,
        severity=severity,
        kind=kind,
        metric_source=metric_source,
        indicator_key=indicator_key,
        study_area_id=study_area_id,
        page=page,
        size=size,
    )
    return page_response([alert_out(a) for a in rows], total, page, size)


@router.get("/alerts/{alert_id}", response_model=AlertDetailOut)
def get_alert(
    alert_id: int,
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
) -> AlertDetailOut:
    return alert_detail_out(service.get_alert(db, alert_id))


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertDetailOut)
def acknowledge_alert(
    alert_id: int,
    payload: AlertActionCreate,
    actor: CurrentUser,
    _perms: Respond,
    db: Annotated[Session, Depends(get_db)],
) -> AlertDetailOut:
    alert = service.get_alert(db, alert_id)
    updated = service.respond(db, alert=alert, action="acknowledge", payload=payload, actor=actor)
    db.commit()
    db.refresh(updated)
    return alert_detail_out(updated)


@router.post("/alerts/{alert_id}/notes", response_model=AlertDetailOut)
def add_alert_note(
    alert_id: int,
    payload: AlertActionCreate,
    actor: CurrentUser,
    _perms: Respond,
    db: Annotated[Session, Depends(get_db)],
) -> AlertDetailOut:
    alert = service.get_alert(db, alert_id)
    updated = service.respond(db, alert=alert, action="note", payload=payload, actor=actor)
    db.commit()
    db.refresh(updated)
    return alert_detail_out(updated)


@router.post("/alerts/{alert_id}/resolve", response_model=AlertDetailOut)
def resolve_alert(
    alert_id: int,
    payload: AlertActionCreate,
    actor: CurrentUser,
    _perms: Respond,
    db: Annotated[Session, Depends(get_db)],
) -> AlertDetailOut:
    alert = service.get_alert(db, alert_id)
    updated = service.respond(db, alert=alert, action="resolve", payload=payload, actor=actor)
    db.commit()
    db.refresh(updated)
    return alert_detail_out(updated)


@router.post("/alerts/{alert_id}/reopen", response_model=AlertDetailOut)
def reopen_alert(
    alert_id: int,
    payload: AlertActionCreate,
    actor: CurrentUser,
    _perms: Respond,
    db: Annotated[Session, Depends(get_db)],
) -> AlertDetailOut:
    alert = service.get_alert(db, alert_id)
    updated = service.respond(db, alert=alert, action="reopen", payload=payload, actor=actor)
    db.commit()
    db.refresh(updated)
    return alert_detail_out(updated)


@router.post("/evaluate", response_model=EvaluateOut)
def run_evaluation(
    payload: EvaluateRequest,
    actor: CurrentUser,
    _perms: Evaluate,
    db: Annotated[Session, Depends(get_db)],
) -> EvaluateOut:
    result = service.evaluate(db, payload=payload, actor=actor)
    db.commit()
    return result


@router.get("/forecasts", response_model=Page[ForecastOut])
def list_forecasts(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
    study_area_id: int | None = None,
    indicator_key: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
) -> Page[ForecastOut]:
    rows, total = service.list_forecasts(
        db, study_area_id=study_area_id, indicator_key=indicator_key, page=page, size=size
    )
    return page_response([forecast_out(r) for r in rows], total, page, size)


@router.post("/forecasts", response_model=ForecastOut, status_code=status.HTTP_201_CREATED)
def record_forecast(
    payload: ForecastCreate,
    actor: CurrentUser,
    _perms: RecordForecast,
    db: Annotated[Session, Depends(get_db)],
) -> ForecastOut:
    row = service.record_forecast(db, payload=payload, actor=actor)
    db.commit()
    db.refresh(row)
    return forecast_out(row)

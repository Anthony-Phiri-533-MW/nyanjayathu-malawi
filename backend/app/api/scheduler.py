"""Daily scheduler API: status, run history and manual triggering."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.serializers import page_response, scheduler_run_out
from app.core.database import get_db
from app.core.deps import CurrentUser, require_permissions
from app.schemas.common import Page
from app.schemas.ml import (
    SchedulerRunOut,
    SchedulerStatusOut,
    SchedulerTriggerRequest,
)
from app.services import scheduler as service

router = APIRouter(prefix="/scheduler", tags=["scheduler"])

Read = Annotated[set[str], Depends(require_permissions("admin.scheduler.read"))]
Run = Annotated[set[str], Depends(require_permissions("admin.scheduler.run"))]


@router.get("/status", response_model=SchedulerStatusOut)
def get_status(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
) -> SchedulerStatusOut:
    return SchedulerStatusOut(**service.status(db))


@router.get("/runs", response_model=Page[SchedulerRunOut])
def list_runs(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=200),
) -> Page[SchedulerRunOut]:
    rows = service.list_runs(db, limit=page * size)
    start = (page - 1) * size
    window = rows[start : start + size]
    total = len(rows)
    return page_response([scheduler_run_out(r) for r in window], total, page, size)


@router.post("/run")
def trigger_run(
    payload: SchedulerTriggerRequest,
    actor: CurrentUser,
    _perms: Run,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Queue today's daily pipeline immediately (idempotent unless ``force``)."""
    result = service.start_daily_run(
        trigger="manual",
        actor=actor,
        source_ids=payload.source_ids,
        study_area_ids=payload.study_area_ids,
        force=payload.force,
    )
    db.commit()
    return result

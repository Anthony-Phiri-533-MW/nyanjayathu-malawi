"""Research: preprocessing runs and their derived products."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.serializers import page_response, processing_run_out
from app.core.database import count_query, get_db
from app.core.deps import CurrentUser, require_permissions
from app.core.errors import NotFoundError
from app.models import ProcessingRun
from app.processing.registry import PROCESSING_OPERATIONS
from app.schemas.common import Page
from app.schemas.research import ProcessingRunCreate, ProcessingRunOut
from app.services import processing as service

router = APIRouter(prefix="/processing", tags=["research: processing"])

Read = Annotated[set[str], Depends(require_permissions("research.datasets.read"))]
Run = Annotated[set[str], Depends(require_permissions("research.processing.run"))]


@router.get("/operations")
def operations(_perms: Read) -> list[dict]:
    return [
        {"key": key, **value} for key, value in sorted(PROCESSING_OPERATIONS.items())
    ]


@router.post("", response_model=ProcessingRunOut, status_code=status.HTTP_202_ACCEPTED)
def start_processing(
    payload: ProcessingRunCreate,
    actor: CurrentUser,
    _perms: Run,
    db: Annotated[Session, Depends(get_db)],
    study_area_id: int | None = Query(default=None),
) -> ProcessingRunOut:
    job = service.start_processing(
        db, payload=payload, actor=actor, study_area_id=study_area_id
    )
    db.commit()
    db.refresh(job)
    run = db.execute(
        select(ProcessingRun)
        .where(ProcessingRun.job_id == job.id)
        .order_by(ProcessingRun.id.desc())
    ).scalars().first()
    if run is None:
        # The pipeline creates run rows when the worker starts; expose the job
        # immediately with an empty run shell so the client can poll.
        return ProcessingRunOut(
            id=0,
            operation="+".join(payload.operations),
            params=payload.params,
            algorithm_version="1.0.0",
            input_dataset_ids=payload.dataset_ids,
            job_id=job.id,
            status=job.status,
            metrics=None,
            error=None,
            created_at=job.created_at,
            started_at=None,
            finished_at=None,
            products=[],
        )
    return processing_run_out(run)


@router.get("/runs", response_model=Page[ProcessingRunOut])
def list_runs(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
    job_id: int | None = None,
    operation: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> Page[ProcessingRunOut]:
    stmt = select(ProcessingRun)
    if job_id is not None:
        stmt = stmt.where(ProcessingRun.job_id == job_id)
    if operation:
        stmt = stmt.where(ProcessingRun.operation == operation)
    if status_filter:
        stmt = stmt.where(ProcessingRun.status == status_filter)
    total = count_query(stmt, db)
    rows = list(
        db.execute(
            stmt.order_by(ProcessingRun.id.desc()).offset((page - 1) * size).limit(size)
        ).unique().scalars()
    )
    return page_response([processing_run_out(r) for r in rows], total, page, size)


@router.get("/runs/{run_id}", response_model=ProcessingRunOut)
def get_run(
    run_id: int,
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
) -> ProcessingRunOut:
    row = db.execute(
        select(ProcessingRun).where(ProcessingRun.id == run_id)
    ).unique().scalar_one_or_none()
    if row is None:
        raise NotFoundError("Processing run not found", details={"id": run_id})
    return processing_run_out(row)

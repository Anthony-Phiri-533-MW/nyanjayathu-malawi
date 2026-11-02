"""Research: background job inspection and control."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.serializers import job_out, page_response
from app.core.database import count_query, get_db
from app.core.deps import CurrentUser, require_permissions
from app.core.errors import NotFoundError
from app.models import Job
from app.schemas.common import Page
from app.schemas.research import JobOut
from app.services import audit as audit_service
from app.services.jobs import cancel_job, retry_job

router = APIRouter(prefix="/jobs", tags=["research: jobs"])

Read = Annotated[set[str], Depends(require_permissions("research.datasets.read"))]
Control = Annotated[set[str], Depends(require_permissions("research.processing.run"))]


def _get(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise NotFoundError("Job not found", details={"id": job_id})
    return job


@router.get("", response_model=Page[JobOut])
def list_jobs(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
    kind: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> Page[JobOut]:
    stmt = select(Job)
    if kind:
        stmt = stmt.where(Job.kind == kind)
    if status_filter:
        stmt = stmt.where(Job.status == status_filter)
    total = count_query(stmt, db)
    rows = list(
        db.execute(
            stmt.order_by(Job.id.desc()).offset((page - 1) * size).limit(size)
        ).scalars()
    )
    return page_response([job_out(j) for j in rows], total, page, size)


@router.get("/{job_id}", response_model=JobOut)
def get_job(
    job_id: int,
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
) -> JobOut:
    return job_out(_get(db, job_id))


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel(
    job_id: int,
    actor: CurrentUser,
    _perms: Control,
    db: Annotated[Session, Depends(get_db)],
) -> JobOut:
    job = cancel_job(db, _get(db, job_id))
    db.commit()
    db.refresh(job)
    audit_service.record(
        action="job.cancel",
        resource_type="job",
        resource_id=job.id,
        actor=actor,
        message=f"Canceled {job.kind} job {job.id}",
    )
    return job_out(job)


@router.post("/{job_id}/retry", response_model=JobOut)
def retry(
    job_id: int,
    actor: CurrentUser,
    _perms: Control,
    db: Annotated[Session, Depends(get_db)],
) -> JobOut:
    job = retry_job(db, _get(db, job_id))
    db.commit()
    db.refresh(job)
    audit_service.record(
        action="job.retry",
        resource_type="job",
        resource_id=job.id,
        actor=actor,
        message=f"Queued {job.kind} job {job.id} for retry",
    )
    return job_out(job)

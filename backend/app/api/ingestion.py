"""Research: ingestion job launch and monitoring."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.serializers import ingestion_job_out, page_response
from app.core.database import get_db
from app.core.deps import CurrentUser, require_permissions
from app.core.errors import NotFoundError
from app.models import IngestionJob
from app.schemas.common import Page
from app.schemas.research import IngestionJobCreate, IngestionJobOut
from app.services import ingestion as service

router = APIRouter(prefix="/ingestion", tags=["research: ingestion"])

Read = Annotated[set[str], Depends(require_permissions("research.datasets.read"))]
Run = Annotated[set[str], Depends(require_permissions("research.ingest.run"))]


@router.post("", response_model=IngestionJobOut, status_code=status.HTTP_202_ACCEPTED)
def start_ingestion(
    payload: IngestionJobCreate,
    actor: CurrentUser,
    _perms: Run,
    db: Annotated[Session, Depends(get_db)],
) -> IngestionJobOut:
    job, ing = service.start_ingestion(db, payload=payload, actor=actor)
    db.commit()
    db.refresh(ing)
    db.refresh(job)
    return ingestion_job_out(ing)


@router.get("", response_model=Page[IngestionJobOut])
def list_ingestion(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> Page[IngestionJobOut]:
    total = db.execute(select(func.count()).select_from(IngestionJob)).scalar_one()
    rows = list(
        db.execute(
            select(IngestionJob)
            .order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        ).scalars()
    )
    return page_response([ingestion_job_out(r) for r in rows], total, page, size)


@router.get("/{ingestion_id}", response_model=IngestionJobOut)
def get_ingestion(
    ingestion_id: int,
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
) -> IngestionJobOut:
    row = db.get(IngestionJob, ingestion_id)
    if row is None:
        raise NotFoundError("Ingestion job not found", details={"id": ingestion_id})
    return ingestion_job_out(row)

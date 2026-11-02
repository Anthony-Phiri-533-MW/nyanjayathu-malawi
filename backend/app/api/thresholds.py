"""Admin: threshold configuration with append-only version history."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.serializers import page_response, threshold_out, threshold_version_out
from app.core.database import get_db
from app.core.deps import CurrentUser, require_permissions
from app.schemas.admin import ThresholdCreate, ThresholdOut, ThresholdUpdate, ThresholdVersionOut
from app.schemas.common import Page
from app.services import thresholds as service

router = APIRouter(prefix="/admin/thresholds", tags=["admin: thresholds"])

Read = Annotated[set[str], Depends(require_permissions("admin.thresholds.read"))]
Write = Annotated[set[str], Depends(require_permissions("admin.thresholds.write"))]


@router.get("", response_model=Page[ThresholdOut])
def list_thresholds(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
    search: str | None = None,
    category: str | None = None,
    approval_status: str | None = None,
    enabled: bool | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> Page[ThresholdOut]:
    rows, total = service.list_thresholds(
        db,
        search=search,
        category=category,
        approval_status=approval_status,
        enabled=enabled,
        page=page,
        size=size,
    )
    return page_response([threshold_out(t) for t in rows], total, page, size)


@router.post("", response_model=ThresholdOut, status_code=status.HTTP_201_CREATED)
def create_threshold(
    payload: ThresholdCreate,
    actor: CurrentUser,
    _perms: Write,
    db: Annotated[Session, Depends(get_db)],
) -> ThresholdOut:
    row = service.create_threshold(db, payload=payload, actor=actor)
    db.commit()
    db.refresh(row)
    return threshold_out(row)


@router.get("/{threshold_id}", response_model=ThresholdOut)
def get_threshold(
    threshold_id: int,
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
) -> ThresholdOut:
    return threshold_out(service.get_threshold(db, threshold_id))


@router.patch("/{threshold_id}", response_model=ThresholdOut)
def update_threshold(
    threshold_id: int,
    payload: ThresholdUpdate,
    actor: CurrentUser,
    _perms: Write,
    db: Annotated[Session, Depends(get_db)],
) -> ThresholdOut:
    row = service.get_threshold(db, threshold_id)
    updated = service.update_threshold(db, payload=payload, actor=actor, t=row)
    db.commit()
    db.refresh(updated)
    return threshold_out(updated)


@router.delete("/{threshold_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_threshold(
    threshold_id: int,
    actor: CurrentUser,
    _perms: Write,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    row = service.get_threshold(db, threshold_id)
    service.delete_threshold(db, actor=actor, t=row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{threshold_id}/versions", response_model=list[ThresholdVersionOut])
def threshold_versions(
    threshold_id: int,
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
) -> list[ThresholdVersionOut]:
    row = service.get_threshold(db, threshold_id)
    return [threshold_version_out(v) for v in row.versions]

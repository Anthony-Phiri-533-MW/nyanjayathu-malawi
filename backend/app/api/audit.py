"""Admin: read-only audit log access."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.serializers import audit_event_out, page_response
from app.core.database import get_db
from app.core.deps import require_permissions
from app.models import AuditEvent
from app.schemas.admin import AuditEventOut
from app.schemas.common import Page
from app.services import audit as service

router = APIRouter(prefix="/admin/audit", tags=["admin: audit"])

Read = Annotated[set[str], Depends(require_permissions("admin.audit.read"))]


@router.get("", response_model=Page[AuditEventOut])
def list_events(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
    search: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    outcome: str | None = None,
    resource_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> Page[AuditEventOut]:
    rows, total = service.list_events(
        db,
        search=search,
        action=action,
        actor=actor,
        outcome=outcome,
        resource_type=resource_type,
        date_from=datetime.combine(date_from, time.min) if date_from else None,
        date_to=datetime.combine(date_to, time.max) if date_to else None,
        page=page,
        size=size,
    )
    return page_response([audit_event_out(r) for r in rows], total, page, size)


@router.get("/actions")
def audit_actions(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
) -> list[str]:
    return list(
        db.execute(select(AuditEvent.action).distinct().order_by(AuditEvent.action.asc())).scalars()
    )


@router.get("/resource-types")
def audit_resource_types(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
) -> list[str]:
    return list(
        db.execute(
            select(AuditEvent.resource_type).distinct().order_by(AuditEvent.resource_type.asc())
        ).scalars()
    )

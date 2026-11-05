"""Public Data module.

Public GET endpoints are **intentionally anonymous**: they expose only rows
whose ``is_public`` flag was set by a staff member holding ``public.publish``
(each toggle is audit-logged).  The PATCH endpoints perform that toggling and
require the permission - the split is enforced per-route, not per-router.

No public endpoint exposes file paths, data-source configuration, threshold
snapshots or staff attributions; see ``app/schemas/public.py``.
"""
from __future__ import annotations

from typing import Annotated
import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.serializers import (
    page_response,
    public_alert_out,
    public_dataset_out,
    public_water_extent_out,
)
from app.core.database import get_db
from app.core.deps import CurrentUser, require_permissions
from app.schemas.common import Page, AssistantInterpretRequest
from app.schemas.public import (
    PublicAlertOut,
    PublicDatasetOut,
    PublicOverviewOut,
    PublicWaterExtentOut,
    PublishFlag,
)
from app.services import audit as audit_service
from app.services import public as service

router = APIRouter(prefix="/public", tags=["public"])

Publish = Annotated[set[str], Depends(require_permissions("public.publish"))]


@router.get("/overview", response_model=PublicOverviewOut)
def public_overview(db: Annotated[Session, Depends(get_db)]) -> dict:
    return service.public_overview(db)


@router.get("/datasets", response_model=Page[PublicDatasetOut])
def public_datasets(
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> Page[PublicDatasetOut]:
    rows, total = service.list_public_datasets(db, page=page, size=size)
    return page_response([public_dataset_out(d) for d in rows], total, page, size)


@router.get("/alerts", response_model=Page[PublicAlertOut])
def public_alerts(
    db: Annotated[Session, Depends(get_db)],
    severity: str | None = None,
    kind: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> Page[PublicAlertOut]:
    rows, total = service.list_public_alerts(
        db, severity=severity, kind=kind, status_filter=status_filter, page=page, size=size
    )
    return page_response([public_alert_out(a) for a in rows], total, page, size)


@router.get("/water-extents", response_model=Page[PublicWaterExtentOut])
def public_water_extents(
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=200),
) -> Page[PublicWaterExtentOut]:
    rows, total = service.list_public_water_extents(db, page=page, size=size)
    return page_response(
        [public_water_extent_out(result, dataset) for result, dataset in rows],
        total,
        page,
        size,
    )


@router.get("/map")
def public_map(db: Annotated[Session, Depends(get_db)]) -> dict:
    """Published study areas and dataset coverages as GeoJSON (anonymous)."""
    return service.public_map(db)


# --------------------------------------------------------------------------
# staff-only publish toggles (each audited); anonymous readers can never
# change anything - these routes exist here so publication stays next to the
# data it governs.


def _audit_publish(
    *, action: str, resource_type: str, resource_id: int, label: str, is_public: bool, actor
) -> None:
    verb = "published to" if is_public else "removed from"
    audit_service.record(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor=actor,
        message=f"{label} {verb} the public dashboard",
        details={"is_public": is_public},
    )


@router.patch("/datasets/{dataset_id}", response_model=PublicDatasetOut)
def set_dataset_public(
    dataset_id: int,
    payload: PublishFlag,
    actor: CurrentUser,
    _perms: Publish,
    db: Annotated[Session, Depends(get_db)],
) -> PublicDatasetOut:
    dataset = service.publish_dataset(
        db, dataset_id=dataset_id, is_public=payload.is_public, actor=actor
    )
    db.commit()
    db.refresh(dataset)
    _audit_publish(
        action="dataset.publish" if payload.is_public else "dataset.unpublish",
        resource_type="dataset",
        resource_id=dataset.id,
        label=f"Dataset '{dataset.title}'",
        is_public=payload.is_public,
        actor=actor,
    )
    return public_dataset_out(dataset)


@router.patch("/alerts/{alert_id}", response_model=PublicAlertOut)
def set_alert_public(
    alert_id: int,
    payload: PublishFlag,
    actor: CurrentUser,
    _perms: Publish,
    db: Annotated[Session, Depends(get_db)],
) -> PublicAlertOut:
    alert = service.publish_alert(db, alert_id=alert_id, is_public=payload.is_public, actor=actor)
    db.commit()
    db.refresh(alert)
    _audit_publish(
        action="alert.publish" if payload.is_public else "alert.unpublish",
        resource_type="alert",
        resource_id=alert.id,
        label=f"Alert #{alert.id}",
        is_public=payload.is_public,
        actor=actor,
    )
    return public_alert_out(alert)


@router.patch("/study-areas/{area_id}")
def set_study_area_public(
    area_id: int,
    payload: PublishFlag,
    actor: CurrentUser,
    _perms: Publish,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    area = service.publish_study_area(
        db, area_id=area_id, is_public=payload.is_public, actor=actor
    )
    db.commit()
    db.refresh(area)
    _audit_publish(
        action="study_area.publish" if payload.is_public else "study_area.unpublish",
        resource_type="study_area",
        resource_id=area.id,
        label=f"Study area '{area.name}'",
        is_public=payload.is_public,
        actor=actor,
    )
    # publishing a study area changes the public map, so return the fresh map
    return service.public_map(db) if payload.is_public else {"id": area.id, "is_public": False}


# --------------------------------------------------------------------------
# Optional: AI assistant interpretation (anonymous, for public dashboard).
# Calls the same OpenRouter endpoint but without bearer token requirement.
# --------------------------------------------------------------------------

@router.post("/interpret-metrics", response_model=dict)
async def public_interpret_metrics(
    question: str,
    metrics_json: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Interpret dashboard metrics using the configured OpenRouter / Nemotron model.
    Intended for the public dashboard where no user is logged in.
    """
    try:
        raw_metrics = json.loads(metrics_json or "[]")
    except json.JSONDecodeError:
        raise UpstreamServiceError("Invalid metrics JSON payload.")

    # Transform raw metrics into AssistantMetric format (label + value)
    # The public dashboard passes {key, name, value, unit, category}; the assistant
    # expects {label, value}. We map name -> label and value -> value.
    metrics = [
        {"label": m.get("name", m.get("key", "")), "value": str(m.get("value", ""))}
        for m in raw_metrics
    ]

    # Re-use the assistant logic (but without auth header)
    from app.services.assistant import interpret_metrics

    # Build a minimal request - AssistantInterpretRequest is defined inline
    # since it's not imported from common to avoid circular deps.
    from pydantic import BaseModel

    class _AssistantInterpretRequest(BaseModel):
        question: str
        metrics: list[dict] = []

    payload = _AssistantInterpretRequest(question=question, metrics=metrics)  # type: ignore[valid-type]
    answer = await interpret_metrics(payload)  # type: ignore[arg-type]

    return {"answer": answer, "model": settings.ai_model, "provider": "openrouter"}

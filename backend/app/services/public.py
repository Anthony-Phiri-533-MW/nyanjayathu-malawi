"""Public Data service.

Public endpoints are anonymous and read-only.  Every query in this module
filters on ``is_public = True`` - the publish flags are the only mechanism that
moves data into the public view, and each toggle is an audited, permission-
gated staff decision.  Nothing here exposes staff attributions, storage paths
or configuration details.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import count_query
from app.core.errors import NotFoundError
from app.models import Alert, Dataset, StudyArea, User, utcnow  # noqa: F401  (utcnow re-exported)
from app.schemas.public import PublicOverviewAlertTotals

_PROVENANCE = (
    "This dashboard shows only what the LakeWatch team has explicitly "
    "published. Figures come from satellite retrievals, derived indicators "
    "and recorded disaster alerts; nothing is predicted and proxy-derived "
    "values are flagged as unvalidated estimates. "
)


# ------------------------------------------------------------------ toggles
def publish_dataset(
    db: Session, *, dataset_id: int, is_public: bool, actor: User | None = None
) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError(f"Dataset {dataset_id} not found")
    dataset.is_public = is_public
    db.flush()
    return dataset


def publish_alert(
    db: Session, *, alert_id: int, is_public: bool, actor: User | None = None
) -> Alert:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise NotFoundError(f"Alert {alert_id} not found")
    alert.is_public = is_public
    db.flush()
    return alert


def publish_study_area(
    db: Session, *, area_id: int, is_public: bool, actor: User | None = None
) -> StudyArea:
    area = db.get(StudyArea, area_id)
    if area is None:
        raise NotFoundError(f"Study area {area_id} not found")
    area.is_public = is_public
    db.flush()
    return area


# ------------------------------------------------------------- area helpers
def _area_name(area: StudyArea | None) -> str | None:
    """Expose the study-area name only when that area itself is public."""
    return area.name if area is not None and area.is_public else None


# ------------------------------------------------------------------- reads
def list_public_datasets(
    db: Session, *, page: int = 1, size: int = 20
) -> tuple[list[Dataset], int]:
    stmt = select(Dataset).where(Dataset.is_public.is_(True))
    total = count_query(stmt, db)
    rows = list(
        db.execute(
            stmt.order_by(Dataset.created_at.desc(), Dataset.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        ).scalars()
    )
    return rows, total


def list_public_alerts(
    db: Session,
    *,
    severity: str | None = None,
    kind: str | None = None,
    status_filter: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[Alert], int]:
    stmt = select(Alert).where(Alert.is_public.is_(True))
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if kind:
        stmt = stmt.where(Alert.kind == kind)
    if status_filter:
        stmt = stmt.where(Alert.status == status_filter)
    total = count_query(stmt, db)
    rows = list(
        db.execute(
            stmt.order_by(Alert.first_seen_at.desc(), Alert.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        ).scalars()
    )
    return rows, total


def public_map(db: Session) -> dict[str, Any]:
    """GeoJSON FeatureCollection of *public* study areas.

    Per-area properties carry public counts only: published datasets and
    open/acknowledged published alerts grouped by severity.
    """
    areas = list(
        db.execute(
            select(StudyArea).where(StudyArea.is_public.is_(True)).order_by(StudyArea.name)
        ).scalars()
    )
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    features: list[dict[str, Any]] = []
    for area in areas:
        alerts = list(
            db.execute(
                select(Alert).where(
                    Alert.study_area_id == area.id,
                    Alert.is_public.is_(True),
                    Alert.status.in_(("open", "acknowledged")),
                )
            ).scalars()
        )
        by_severity: dict[str, int] = {}
        for a in alerts:
            by_severity[a.severity] = by_severity.get(a.severity, 0) + 1
        highest = (
            sorted(by_severity.items(), key=lambda kv: severity_order.get(kv[0], 3))[0][0]
            if by_severity
            else None
        )
        dataset_count = int(
            db.execute(
                select(func.count(Dataset.id)).where(
                    Dataset.study_area_id == area.id, Dataset.is_public.is_(True)
                )
            ).scalar_one()
        )
        features.append(
            {
                "type": "Feature",
                "id": area.id,
                "geometry": area.boundary_geojson,
                "properties": {
                    "id": area.id,
                    "name": area.name,
                    "description": area.description,
                    "public_dataset_count": dataset_count,
                    "active_public_alerts": len(alerts),
                    "by_severity": by_severity,
                    "highest_active_severity": highest,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "generated_at": datetime.now(UTC),
        "provenance": _PROVENANCE,
    }


def public_overview(db: Session) -> dict[str, Any]:
    dataset_count = int(
        db.execute(select(func.count(Dataset.id)).where(Dataset.is_public.is_(True))).scalar_one()
    )
    area_count = int(
        db.execute(select(func.count(StudyArea.id)).where(StudyArea.is_public.is_(True))).scalar_one()
    )
    alerts = list(db.execute(select(Alert).where(Alert.is_public.is_(True))).scalars())
    totals = PublicOverviewAlertTotals(total=len(alerts))
    for a in alerts:
        totals.by_severity[a.severity] = totals.by_severity.get(a.severity, 0) + 1
        totals.by_kind[a.kind] = totals.by_kind.get(a.kind, 0) + 1
        totals.by_status[a.status] = totals.by_status.get(a.status, 0) + 1

    coverage_start, coverage_end = None, None
    if dataset_count:
        coverage_start = db.execute(
            select(func.min(Dataset.start_date)).where(Dataset.is_public.is_(True))
        ).scalar_one()
        coverage_end = db.execute(
            select(func.max(Dataset.end_date)).where(Dataset.is_public.is_(True))
        ).scalar_one()

    return {
        "generated_at": utcnow(),
        "dataset_count": dataset_count,
        "study_area_count": area_count,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "alerts": totals,
        "provenance": _PROVENANCE,
    }

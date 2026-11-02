"""Threshold configuration with append-only version history.

No values here are authoritative Lake Malawi thresholds unless explicitly
marked ``approved`` with a citation - everything seeded starts as
``provisional`` and is labelled as such in the API/UI.
"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.database import count_query
from app.core.errors import ConflictError, NotFoundError
from app.models import Threshold, ThresholdVersion, User, utcnow
from app.schemas.admin import ThresholdCreate, ThresholdUpdate
from app.services import audit as audit_service


def _snapshot(t: Threshold) -> dict:
    return {
        "indicator_key": t.indicator_key,
        "indicator_name": t.indicator_name,
        "unit": t.unit,
        "operator": t.operator,
        "value_low": t.value_low,
        "value_high": t.value_high,
        "description": t.description,
        "justification": t.justification,
        "reference": t.reference,
        "approval_status": t.approval_status,
        "effective_from": t.effective_from.isoformat() if t.effective_from else None,
        "effective_to": t.effective_to.isoformat() if t.effective_to else None,
        "is_enabled": t.is_enabled,
        "version": t.version,
    }


def list_thresholds(
    db: Session,
    *,
    search: str | None = None,
    category: str | None = None,
    approval_status: str | None = None,
    enabled: bool | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[Threshold], int]:
    stmt = select(Threshold)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(Threshold.indicator_key.ilike(like), Threshold.indicator_name.ilike(like),
                Threshold.description.ilike(like), Threshold.reference.ilike(like))
        )
    if category:
        from app.models import IndicatorDefinition

        stmt = stmt.join(IndicatorDefinition, IndicatorDefinition.key == Threshold.indicator_key, isouter=True).where(
            IndicatorDefinition.category == category
        )
    if approval_status:
        stmt = stmt.where(Threshold.approval_status == approval_status)
    if enabled is not None:
        stmt = stmt.where(Threshold.is_enabled.is_(enabled))
    total = count_query(stmt, db)
    rows = (
        db.execute(
            stmt.options(joinedload(Threshold.versions))
            .order_by(Threshold.indicator_key.asc(), Threshold.id.desc())
            .limit(size)
            .offset((page - 1) * size)
        )
        .unique()
        .scalars()
        .all()
    )
    return list(rows), total


def get_threshold(db: Session, threshold_id: int) -> Threshold:
    row = db.execute(
        select(Threshold).options(joinedload(Threshold.versions)).where(Threshold.id == threshold_id)
    ).unique().scalar_one_or_none()
    if row is None:
        raise NotFoundError("Threshold not found", details={"id": threshold_id})
    return row


def _validate_against_others(db: Session, *, indicator_key: str, operator: str, exclude_id: int | None) -> None:
    existing = db.execute(
        select(Threshold).where(Threshold.indicator_key == indicator_key, Threshold.is_enabled.is_(True))
    ).scalars().all()
    clashing = [t for t in existing if t.id != exclude_id and t.operator == operator]
    if clashing and operator != "between":
        # enabled thresholds on the same indicator using the same operator would be ambiguous
        raise ConflictError(
            "An enabled threshold for this indicator with the same operator already exists",
            details={"conflicting_ids": [t.id for t in clashing]},
        )


def create_threshold(db: Session, *, payload: ThresholdCreate, actor: User) -> Threshold:
    _validate_against_others(
        db, indicator_key=payload.indicator_key, operator=payload.operator, exclude_id=None
    )
    t = Threshold(
        indicator_key=payload.indicator_key,
        indicator_name=payload.indicator_name,
        unit=payload.unit,
        operator=payload.operator,
        value_low=payload.value_low,
        value_high=payload.value_high,
        description=payload.description,
        justification=payload.justification,
        reference=payload.reference,
        approval_status=payload.approval_status,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        is_enabled=payload.is_enabled,
        version=1,
        created_by_id=actor.id,
    )
    db.add(t)
    db.flush()
    t.versions.append(
        ThresholdVersion(
            threshold_id=t.id,
            version=1,
            snapshot_json=_snapshot(t),
            change_note="Initial version",
            changed_by_id=actor.id,
            changed_by_email=actor.email,
        )
    )
    db.flush()
    audit_service.record(
        action="threshold.create",
        resource_type="threshold",
        resource_id=t.id,
        actor=actor,
        db=db,
        message=f"Created threshold for {t.indicator_key}",
        details={"snapshot": _snapshot(t)},
    )
    return t


def update_threshold(db: Session, *, payload: ThresholdUpdate, actor: User, t: Threshold) -> Threshold:
    data = payload.model_dump(exclude_unset=True)
    change_note = data.pop("change_note", "") or ""
    before = _snapshot(t)
    changed: dict = {}
    for field, value in data.items():
        if getattr(t, field) != value:
            setattr(t, field, value)
            changed[field] = value

    new_operator = changed.get("operator", t.operator)
    if changed:
        _validate_against_others(
            db, indicator_key=t.indicator_key, operator=new_operator, exclude_id=t.id
        )
        t.version += 1
        t.updated_at = utcnow()
        t.versions.append(
            ThresholdVersion(
                threshold_id=t.id,
                version=t.version,
                snapshot_json=_snapshot(t),
                change_note=change_note or ("Updated: " + ", ".join(sorted(changed))),
                changed_by_id=actor.id,
                changed_by_email=actor.email,
            )
        )
        db.flush()
        audit_service.record(
            action="threshold.update",
            resource_type="threshold",
            resource_id=t.id,
            actor=actor,
            db=db,
            message=f"Threshold {t.indicator_key} -> version {t.version}",
            details={"before": before, "after": _snapshot(t), "note": change_note},
        )
    return t


def delete_threshold(db: Session, *, actor: User, t: Threshold) -> None:
    info = {"indicator_key": t.indicator_key, "version": t.version}
    db.delete(t)
    db.flush()
    audit_service.record(
        action="threshold.delete",
        resource_type="threshold",
        resource_id=info["indicator_key"],
        actor=actor,
        db=db,
        message=f"Deleted threshold for {info['indicator_key']}",
        details=info,
    )

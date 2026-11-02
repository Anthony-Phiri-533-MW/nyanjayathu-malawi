"""Data-source configuration service (admin module) with connection testing."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import count_query
from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.models import Dataset, DataSource, User, utcnow
from app.schemas.admin import DataSourceCreate, DataSourceUpdate
from app.services import audit as audit_service
from app.services.spatial import parse_geojson_geometry


def _q(db: Session, *, search=None, category=None, provider_key=None, status=None, enabled=None, page=1, size=20):
    stmt = select(DataSource)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                DataSource.name.ilike(like),
                DataSource.dataset_name.ilike(like),
                DataSource.dataset_identifier.ilike(like),
                DataSource.description.ilike(like),
            )
        )
    if category:
        stmt = stmt.where(DataSource.category == category)
    if provider_key:
        stmt = stmt.where(DataSource.provider_key == provider_key)
    if status:
        stmt = stmt.where(DataSource.status == status)
    if enabled is not None:
        stmt = stmt.where(DataSource.is_enabled.is_(enabled))
    return stmt


def list_sources(db: Session, **filters) -> tuple[list[DataSource], int]:
    page = filters.pop("page", 1)
    size = filters.pop("size", 20)
    stmt = _q(db, **filters)
    total = count_query(stmt, db)
    rows = (
        db.execute(stmt.order_by(DataSource.id.asc()).limit(size).offset((page - 1) * size))
        .scalars()
        .all()
    )
    # dataset_count = genuinely retrieved data (distinct datasets from this source)
    counts = dict(
        db.execute(
            select(Dataset.data_source_id, func.count(func.distinct(Dataset.id)))
            .group_by(Dataset.data_source_id)
        ).all()
    )
    for r in rows:
        r._dataset_count = counts.get(r.id, 0)  # type: ignore[attr-defined]
    return list(rows), total


def dataset_count(ds: DataSource) -> int:
    return getattr(ds, "_dataset_count", 0) or 0


def get_source(db: Session, source_id: int) -> DataSource:
    row = db.execute(select(DataSource).where(DataSource.id == source_id)).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Data source not found", details={"id": source_id})
    return row


def _validate_variables(variables) -> list[dict] | None:
    if variables is None:
        return None
    if isinstance(variables, dict):
        return variables
    if not isinstance(variables, list):
        raise UnprocessableError("variables must be a list of descriptors")
    cleaned = []
    for v in variables:
        if not isinstance(v, dict) or not v.get("key"):
            raise UnprocessableError("each variable needs at least a 'key'")
        cleaned.append({k: v[k] for k in v if k in {"key", "label", "unit", "band", "wavelength_nm", "description"}})
    return cleaned


def create_source(db: Session, *, payload: DataSourceCreate, actor: User) -> DataSource:
    if payload.coverage_geojson:
        parse_geojson_geometry(payload.coverage_geojson, allowed=["Polygon", "MultiPolygon", "Point"])
    exists = db.execute(
        select(DataSource).where(
            DataSource.provider_key == payload.provider_key,
            DataSource.dataset_identifier == payload.dataset_identifier,
        )
    ).scalar_one_or_none()
    if exists is not None and payload.dataset_identifier:
        raise ConflictError("A source with this provider and dataset identifier already exists")

    from app.providers.registry import known_provider_keys

    if payload.provider_key not in known_provider_keys():
        raise UnprocessableError(
            f"No adapter is registered for provider '{payload.provider_key}'",
            details={"available": sorted(known_provider_keys())},
        )

    ds = DataSource(
        name=payload.name.strip(),
        provider_key=payload.provider_key,
        category=payload.category,
        dataset_name=payload.dataset_name,
        dataset_identifier=payload.dataset_identifier,
        description=payload.description,
        is_enabled=payload.is_enabled,
        coverage_geojson=payload.coverage_geojson,
        temporal_start=payload.temporal_start,
        temporal_end=payload.temporal_end,
        variables_json=_validate_variables(payload.variables),
        ingestion_config_json=payload.ingestion_config,
        auth_method=payload.auth_method,
        credential_ref=payload.credential_ref,
        status="configured",
        created_by_id=actor.id,
    )
    db.add(ds)
    db.flush()
    audit_service.record(
        action="data_source.create",
        resource_type="data_source",
        resource_id=ds.id,
        actor=actor,
        db=db,
        message=f"Created data source '{ds.name}'",
        details={"provider_key": ds.provider_key, "category": ds.category, "dataset_identifier": ds.dataset_identifier},
    )
    return ds


def update_source(db: Session, *, payload: DataSourceUpdate, actor: User, ds: DataSource) -> DataSource:
    data = payload.model_dump(exclude_unset=True)
    if data.get("coverage_geojson"):
        parse_geojson_geometry(data["coverage_geojson"], allowed=["Polygon", "MultiPolygon", "Point"])
    if "variables" in data:
        ds.variables_json = _validate_variables(data.pop("variables"))
    if "ingestion_config" in data:
        ds.ingestion_config_json = data.pop("ingestion_config")
    changed: dict = {}
    for field in (
        "name",
        "dataset_name",
        "dataset_identifier",
        "description",
        "is_enabled",
        "coverage_geojson",
        "temporal_start",
        "temporal_end",
        "auth_method",
        "credential_ref",
    ):
        if field in data and getattr(ds, field) != data[field]:
            setattr(ds, field, data[field])
            changed[field] = data[field]
    ds.updated_at = utcnow()
    db.flush()
    audit_service.record(
        action="data_source.update",
        resource_type="data_source",
        resource_id=ds.id,
        actor=actor,
        db=db,
        message=f"Updated data source '{ds.name}'",
        details={"changed": changed},
    )
    return ds


def delete_source(db: Session, *, actor: User, ds: DataSource) -> None:
    has_datasets = db.execute(
        select(func.count()).select_from(Dataset).where(Dataset.data_source_id == ds.id)
    ).scalar_one()
    if has_datasets:
        raise ConflictError(
            "Source has retrieved datasets; disable it instead of deleting "
            "(datasets keep their provenance)",
            details={"dataset_count": has_datasets},
        )
    name = ds.name
    db.delete(ds)
    db.flush()
    audit_service.record(
        action="data_source.delete",
        resource_type="data_source",
        resource_id=None,
        actor=actor,
        db=db,
        message=f"Deleted data source '{name}'",
        details={"name": name},
    )


def record_test_result(
    db: Session, *, ds: DataSource, ok: bool, message: str, actor: User, details: dict | None = None
) -> DataSource:
    now = datetime.now(UTC).replace(tzinfo=None)
    ds.last_test_at = now
    ds.last_test_status = "ok" if ok else "error"
    ds.last_test_message = message[:4000]
    ds.status = "verified" if ok else "failed"
    ds.updated_at = now
    db.flush()
    audit_service.record(
        action="data_source.test",
        resource_type="data_source",
        resource_id=ds.id,
        outcome="success" if ok else "failure",
        db=db,
        actor=actor,
        message=f"Connection test {'passed' if ok else 'failed'} for '{ds.name}': {message[:200]}",
        details=details,
    )
    return ds


def record_ingestion_outcome(db: Session, *, ds: DataSource, ok: bool, error: str | None = None) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    ds.last_ingestion_attempt_at = now
    if ok:
        ds.last_success_at = now
        ds.error_status = None
        ds.error_detail = None
        if ds.status in ("configured", "failed"):
            ds.status = "verified"
    else:
        ds.error_status = "ingestion_failed"
        ds.error_detail = (error or "")[:4000]
    ds.updated_at = now
    db.flush()

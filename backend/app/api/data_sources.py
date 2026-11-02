"""Admin: data-source configuration and connection tests."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.serializers import data_source_out, page_response
from app.core.database import get_db
from app.core.deps import CurrentUser, require_permissions
from app.providers import ProviderError
from app.schemas.admin import (
    ConnectionTestOut,
    DataSourceCreate,
    DataSourceOut,
    DataSourceUpdate,
)
from app.schemas.common import Page
from app.services import data_sources as service
from app.services.ingestion import _adapter_for

router = APIRouter(prefix="/admin/data-sources", tags=["admin: data sources"])

Read = Annotated[set[str], Depends(require_permissions("admin.data_sources.read"))]
Write = Annotated[set[str], Depends(require_permissions("admin.data_sources.write"))]
Test = Annotated[set[str], Depends(require_permissions("admin.data_sources.test"))]


@router.get("", response_model=Page[DataSourceOut])
def list_sources(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
    search: str | None = None,
    category: str | None = None,
    provider_key: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    enabled: bool | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> Page[DataSourceOut]:
    rows, total = service.list_sources(
        db,
        search=search,
        category=category,
        provider_key=provider_key,
        status=status_filter,
        enabled=enabled,
        page=page,
        size=size,
    )
    return page_response(
        [data_source_out(r, dataset_count=service.dataset_count(r)) for r in rows],
        total,
        page,
        size,
    )


@router.post("", response_model=DataSourceOut, status_code=status.HTTP_201_CREATED)
def create_source(
    payload: DataSourceCreate,
    actor: CurrentUser,
    _perms: Write,
    db: Annotated[Session, Depends(get_db)],
) -> DataSourceOut:
    source = service.create_source(db, payload=payload, actor=actor)
    db.commit()
    db.refresh(source)
    return data_source_out(source, dataset_count=0)


@router.get("/{source_id}", response_model=DataSourceOut)
def get_source(
    source_id: int,
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
) -> DataSourceOut:
    source = service.get_source(db, source_id)
    count = service.dataset_count(source)
    if count == 0:
        from sqlalchemy import func, select

        from app.models import Dataset

        count = db.execute(
            select(func.count()).select_from(Dataset).where(Dataset.data_source_id == source.id)
        ).scalar_one()
    return data_source_out(source, dataset_count=count)


@router.patch("/{source_id}", response_model=DataSourceOut)
def update_source(
    source_id: int,
    payload: DataSourceUpdate,
    actor: CurrentUser,
    _perms: Write,
    db: Annotated[Session, Depends(get_db)],
) -> DataSourceOut:
    source = service.get_source(db, source_id)
    updated = service.update_source(db, payload=payload, actor=actor, ds=source)
    db.commit()
    db.refresh(updated)
    return data_source_out(updated, dataset_count=service.dataset_count(updated))


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(
    source_id: int,
    actor: CurrentUser,
    _perms: Write,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    source = service.get_source(db, source_id)
    service.delete_source(db, actor=actor, ds=source)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{source_id}/test", response_model=ConnectionTestOut)
def test_source(
    source_id: int,
    actor: CurrentUser,
    _perms: Test,
    db: Annotated[Session, Depends(get_db)],
) -> ConnectionTestOut:
    source = service.get_source(db, source_id)
    started = datetime.now(UTC)
    try:
        adapter = _adapter_for(source)
        result = adapter.test_connection()
        ok, message, latency, details = result.ok, result.message, result.latency_ms, result.details
    except ProviderError as exc:
        ok, message, latency, details = False, str(exc), None, exc.details
    except Exception as exc:  # noqa: BLE001 - surfaced to the admin
        ok, message, latency, details = False, f"{type(exc).__name__}: {exc}", None, {}

    service.record_test_result(
        db, ds=source, ok=ok, message=message, actor=actor, details=details
    )
    db.commit()
    db.refresh(source)
    return ConnectionTestOut(
        source_id=source.id,
        status="verified" if ok else "failed",
        tested_at=datetime.now(UTC),
        message=message,
        latency_ms=latency,
        details={
            "duration_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
            **(details or {}),
        },
    )

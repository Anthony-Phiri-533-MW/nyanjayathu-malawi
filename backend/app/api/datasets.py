"""Research: dataset browsing, metadata and descriptive band statistics."""
from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.serializers import dataset_detail_out, dataset_out, page_response
from app.core.database import get_db
from app.core.deps import require_permissions
from app.core.enums import QUALITY_FLAGS
from app.schemas.common import Page
from app.schemas.research import DatasetDetailOut, DatasetOut
from app.services import datasets as service

router = APIRouter(prefix="/datasets", tags=["research: datasets"])

Read = Annotated[set[str], Depends(require_permissions("research.datasets.read"))]


def _parse_bbox(bbox: str | None) -> tuple[float, float, float, float] | None:
    if not bbox:
        return None
    try:
        parts = [float(p) for p in bbox.split(",")]
    except ValueError:
        raise ValueError("bbox must be 'minx,miny,maxx,maxy'") from None
    if len(parts) != 4:
        raise ValueError("bbox must be 'minx,miny,maxx,maxy'")
    return parts[0], parts[1], parts[2], parts[3]


@router.get("", response_model=Page[DatasetOut])
def list_datasets(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
    search: str | None = None,
    provider_key: str | None = None,
    category: str | None = None,
    kind: str | None = None,
    quality_flag: str | None = Query(default=None, pattern="^(VALID|LOW_QUALITY|INSUFFICIENT_COVERAGE|CLOUD_CONTAMINATED|MISSING_DATA|PROCESSING_FAILED|UNVALIDATED)$"),
    study_area_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    bbox: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> Page[DatasetOut]:
    rows, total = service.list_datasets(
        db,
        page=page,
        size=size,
        search=search,
        provider_key=provider_key,
        category=category,
        kind=kind,
        quality_flag=quality_flag,
        study_area_id=study_area_id,
        start_date=start_date,
        end_date=end_date,
        bbox=_parse_bbox(bbox),
    )
    return page_response([dataset_out(r) for r in rows], total, page, size)


@router.get("/quality-flags")
def quality_flags(_perms: Read) -> list[str]:
    return QUALITY_FLAGS


@router.get("/{dataset_id}", response_model=DatasetDetailOut)
def get_dataset(
    dataset_id: int,
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
    include_band_statistics: bool = False,
) -> DatasetDetailOut:
    dataset = service.get_dataset(db, dataset_id)
    statistics = service.band_statistics(dataset) if include_band_statistics else None
    return dataset_detail_out(
        dataset,
        assessments=service.quality_assessments(db, dataset),
        indicator_result_count=service.indicator_result_count(db, dataset),
        band_statistics=statistics,
    )

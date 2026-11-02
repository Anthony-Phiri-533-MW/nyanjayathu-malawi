"""Research: time-series assembly and period comparison."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_permissions
from app.schemas.research import ComparisonCreate, ComparisonOut, TimeSeriesOut
from app.services import analysis as service

router = APIRouter(tags=["research: analysis"])

Read = Annotated[set[str], Depends(require_permissions("research.indicators.read"))]
Compare = Annotated[set[str], Depends(require_permissions("research.compare.run"))]


@router.get("/timeseries", response_model=TimeSeriesOut)
def timeseries(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
    indicator_key: str = Query(min_length=3),
    study_area_id: int | None = None,
    dataset_ids: list[int] | None = Query(default=None),  # noqa: B008 (FastAPI dependency defaults are the documented pattern)
    start_date: date | None = None,
    end_date: date | None = None,
    aggregation: Literal["raw", "monthly", "annual"] = "raw",
) -> TimeSeriesOut:
    series = service.build_timeseries(
        db,
        indicator_key=indicator_key,
        study_area_id=study_area_id,
        dataset_ids=dataset_ids,
        start=start_date,
        end=end_date,
        aggregation=aggregation,
    )
    return TimeSeriesOut(**series)


@router.post("/compare", response_model=ComparisonOut)
def compare(
    payload: ComparisonCreate,
    _perms: Compare,
    db: Annotated[Session, Depends(get_db)],
) -> ComparisonOut:
    return ComparisonOut(**service.compare_periods(db, payload))

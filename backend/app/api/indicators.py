"""Research: indicator definitions, computation and result browsing."""
from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.serializers import (
    indicator_result_out,
    job_out,
    page_response,
)
from app.core.database import get_db
from app.core.deps import CurrentUser, require_permissions
from app.models import Dataset, IndicatorResult, StudyArea
from app.schemas.common import Page
from app.schemas.research import (
    IndicatorComputeCreate,
    IndicatorDefinitionOut,
    IndicatorResultOut,
    JobOut,
)
from app.services import indicators as service

router = APIRouter(prefix="/indicators", tags=["research: indicators"])

Read = Annotated[set[str], Depends(require_permissions("research.indicators.read"))]
Run = Annotated[set[str], Depends(require_permissions("research.processing.run"))]


@router.get("/definitions", response_model=list[IndicatorDefinitionOut])
def list_definitions(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
) -> list[IndicatorDefinitionOut]:
    return [
        IndicatorDefinitionOut.model_validate(row)
        for row in service.list_definitions(db)
    ]


@router.post("/compute", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def compute(
    payload: IndicatorComputeCreate,
    actor: CurrentUser,
    _perms: Run,
    db: Annotated[Session, Depends(get_db)],
) -> JobOut:
    job = service.start_indicator_compute(db, payload=payload, actor=actor)
    db.commit()
    db.refresh(job)
    return job_out(job)


@router.get("/results", response_model=Page[IndicatorResultOut])
def list_results(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
    indicator_key: str | None = None,
    study_area_id: int | None = None,
    dataset_id: int | None = None,
    quality_flag: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> Page[IndicatorResultOut]:
    rows, total = service.list_results(
        db,
        page=page,
        size=size,
        indicator_key=indicator_key,
        study_area_id=study_area_id,
        dataset_id=dataset_id,
        quality_flag=quality_flag,
        start=start_date,
        end=end_date,
    )
    area_names = _area_names(db, rows)
    dataset_names = _dataset_names(db, rows)
    return page_response(
        [
            indicator_result_out(
                r,
                study_area_name=area_names.get(r.study_area_id),
                dataset_title=dataset_names.get(r.dataset_id),
            )
            for r in rows
        ],
        total,
        page,
        size,
    )


@router.get("/results/{result_id}", response_model=IndicatorResultOut)
def get_result(
    result_id: int,
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
) -> IndicatorResultOut:
    row = service.get_result(db, result_id)
    return indicator_result_out(
        row,
        study_area_name=_area_names(db, [row]).get(row.study_area_id),
        dataset_title=_dataset_names(db, [row]).get(row.dataset_id),
    )


def _area_names(db: Session, rows: list[IndicatorResult]) -> dict[int, str]:
    ids = {r.study_area_id for r in rows if r.study_area_id}
    if not ids:
        return {}
    return {
        row.id: row.name
        for row in db.execute(select(StudyArea).where(StudyArea.id.in_(ids))).scalars()
    }


def _dataset_names(db: Session, rows: list[IndicatorResult]) -> dict[int, str]:
    ids = {r.dataset_id for r in rows if r.dataset_id}
    if not ids:
        return {}
    return {
        row.id: row.title
        for row in db.execute(select(Dataset).where(Dataset.id.in_(ids))).scalars()
    }

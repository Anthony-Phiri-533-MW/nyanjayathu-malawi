"""Research: study-area management."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.serializers import study_area_out
from app.core.database import get_db
from app.core.deps import CurrentUser, require_permissions
from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.models import Dataset, IndicatorResult, IngestionJob, StudyArea
from app.schemas.research import StudyAreaCreate, StudyAreaOut, StudyAreaUpdate
from app.services import audit as audit_service
from app.services.spatial import geom_bbox, parse_geojson_geometry

router = APIRouter(prefix="/study-areas", tags=["research: study areas"])

Read = Annotated[set[str], Depends(require_permissions("research.datasets.read"))]
Write = Annotated[set[str], Depends(require_permissions("research.processing.run"))]


def _get(db: Session, area_id: int) -> StudyArea:
    area = db.get(StudyArea, area_id)
    if area is None:
        raise NotFoundError("Study area not found", details={"id": area_id})
    return area


def _bbox(boundary: dict) -> tuple[float, float, float, float]:
    geom = parse_geojson_geometry(boundary, allowed=["Polygon", "MultiPolygon"])
    minx, miny, maxx, maxy = geom_bbox(geom)
    if maxx - minx <= 0 or maxy - miny <= 0:
        raise UnprocessableError("Study-area boundary has zero area")
    if not (-180 <= minx <= 180 and -180 <= maxx <= 180 and -90 <= miny <= 90 and -90 <= maxy <= 90):
        raise UnprocessableError("Study-area boundary must be in EPSG:4326 (longitude/latitude)")
    return minx, miny, maxx, maxy


@router.get("", response_model=list[StudyAreaOut])
def list_study_areas(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
) -> list[StudyAreaOut]:
    rows = (
        db.execute(
            select(StudyArea).order_by(StudyArea.is_default.desc(), StudyArea.name.asc())
        )
        .scalars()
        .all()
    )
    return [study_area_out(a) for a in rows]


@router.post("", response_model=StudyAreaOut, status_code=status.HTTP_201_CREATED)
def create_study_area(
    payload: StudyAreaCreate,
    actor: CurrentUser,
    _perms: Write,
    db: Annotated[Session, Depends(get_db)],
) -> StudyAreaOut:
    if db.execute(select(StudyArea).where(StudyArea.name == payload.name.strip())).scalar_one_or_none():
        raise ConflictError("A study area with this name already exists")
    minx, miny, maxx, maxy = _bbox(payload.boundary_geojson)
    area = StudyArea(
        name=payload.name.strip(),
        description=payload.description,
        boundary_geojson=payload.boundary_geojson,
        minx=minx,
        miny=miny,
        maxx=maxx,
        maxy=maxy,
        is_default=False,
        created_by_id=actor.id,
    )
    db.add(area)
    db.flush()
    db.commit()
    db.refresh(area)
    audit_service.record(
        action="study_area.create",
        resource_type="study_area",
        resource_id=area.id,
        actor=actor,
        message=f"Created study area '{area.name}'",
        details={"bbox": [minx, miny, maxx, maxy]},
    )
    return study_area_out(area)


@router.get("/{area_id}", response_model=StudyAreaOut)
def get_study_area(
    area_id: int,
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
) -> StudyAreaOut:
    return study_area_out(_get(db, area_id))


@router.patch("/{area_id}", response_model=StudyAreaOut)
def update_study_area(
    area_id: int,
    payload: StudyAreaUpdate,
    actor: CurrentUser,
    _perms: Write,
    db: Annotated[Session, Depends(get_db)],
) -> StudyAreaOut:
    area = _get(db, area_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        name = data["name"].strip()
        clash = db.execute(
            select(StudyArea).where(StudyArea.name == name, StudyArea.id != area.id)
        ).scalar_one_or_none()
        if clash:
            raise ConflictError("A study area with this name already exists")
        area.name = name
    if "description" in data and data["description"] is not None:
        area.description = data["description"]
    if data.get("boundary_geojson"):
        area.boundary_geojson = data["boundary_geojson"]
        area.minx, area.miny, area.maxx, area.maxy = _bbox(data["boundary_geojson"])
    db.flush()
    db.commit()
    db.refresh(area)
    audit_service.record(
        action="study_area.update",
        resource_type="study_area",
        resource_id=area.id,
        actor=actor,
        message=f"Updated study area '{area.name}'",
        details={"fields": sorted(data)},
    )
    return study_area_out(area)


@router.delete("/{area_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_study_area(
    area_id: int,
    actor: CurrentUser,
    _perms: Write,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    area = _get(db, area_id)
    if area.is_default:
        raise ConflictError("The default study area cannot be deleted")
    refs = {}
    for model, label in (
        (Dataset, "datasets"),
        (IngestionJob, "ingestion_jobs"),
        (IndicatorResult, "indicator_results"),
    ):
        count = db.execute(
            select(func.count()).select_from(model).where(model.study_area_id == area.id)
        ).scalar_one()
        if count:
            refs[label] = count
    if refs:
        raise ConflictError(
            "Study area is referenced by stored data; keep it for provenance",
            details=refs,
        )
    name = area.name
    db.delete(area)
    db.flush()
    db.commit()
    audit_service.record(
        action="study_area.delete",
        resource_type="study_area",
        resource_id=area_id,
        actor=actor,
        message=f"Deleted study area '{name}'",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

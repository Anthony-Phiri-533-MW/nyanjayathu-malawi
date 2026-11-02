"""Spatial helpers: geometry validation, bbox handling and PostGIS-aware
bounding-box queries.

Geometry is stored as GeoJSON (EPSG:4326) in TEXT columns so the application
runs identically on PostgreSQL and SQLite.  On PostgreSQL, where PostGIS is
available (the docker-compose database enables it), bbox filtering is pushed
down to the database with ``ST_Intersects``; otherwise the same predicate is
evaluated in-process with shapely.
"""
from __future__ import annotations

from collections.abc import Iterable

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import UnprocessableError

Bbox = tuple[float, float, float, float]  # minx, miny, maxx, maxy


def parse_geojson_geometry(geojson: dict, *, allowed: Iterable[str] | None = None) -> BaseGeometry:
    if not isinstance(geojson, dict) or "type" not in geojson:
        raise UnprocessableError("geometry must be a GeoJSON object")
    if allowed and geojson.get("type") not in tuple(allowed):
        raise UnprocessableError(f"geometry type must be one of {sorted(allowed)}")
    try:
        geom = shape(geojson)
    except Exception as exc:
        raise UnprocessableError(f"Invalid GeoJSON geometry: {exc}") from exc
    if geom.is_empty:
        raise UnprocessableError("geometry is empty")
    if not geom.is_valid:
        geom = geom.buffer(0)
        if geom.is_empty or not geom.is_valid:
            raise UnprocessableError("geometry is not valid")
    if geom.bounds[0] < -180 or geom.bounds[2] > 180 or geom.bounds[1] < -90 or geom.bounds[3] > 90:
        raise UnprocessableError("geometry coordinates must be WGS84 (EPSG:4326)")
    return geom


def geom_bbox(geom: BaseGeometry) -> Bbox:
    minx, miny, maxx, maxy = geom.bounds
    return (float(minx), float(miny), float(maxx), float(maxy))


def normalize_bbox(values: list[float] | tuple[float, ...]) -> Bbox:
    if len(values) != 4:
        raise UnprocessableError("bbox must contain 4 values: minx,miny,maxx,maxy")
    minx, miny, maxx, maxy = (float(v) for v in values)
    if minx > maxx or miny > maxy:
        raise UnprocessableError("bbox min values must not exceed max values")
    if minx < -180 or maxx > 180 or miny < -90 or maxy > 90:
        raise UnprocessableError("bbox must be in WGS84 (EPSG:4326)")
    return (minx, miny, maxx, maxy)


def postgis_available(db: Session) -> bool:
    from app.core.config import settings

    if settings.is_sqlite:
        return False
    try:
        row = db.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'postgis' LIMIT 1")
        ).first()
        return row is not None
    except Exception:
        db.rollback()
        return False


def bbox_geojson_filter(column, bbox: Bbox, db: Session):
    """Return a SQLAlchemy WHERE clause intersecting ``column`` (GeoJSON TEXT)
    with ``bbox``: PostGIS when available, no filter otherwise (caller falls
    back to in-process filtering)."""
    if postgis_available(db):
        minx, miny, maxx, maxy = bbox
        return text(
            "ST_Intersects(ST_SetSRID(ST_GeomFromGeoJSON(CAST(:gcol AS TEXT)),4326), "
            "ST_MakeEnvelope(:minx,:miny,:maxx,:maxy,4326))"
        ).bindparams(gcol=column, minx=minx, miny=miny, maxx=maxx, maxy=maxy)
    return None


def geojson_intersects(geojson: dict | None, bbox: Bbox) -> bool:
    if not geojson:
        return False
    try:
        geom = shape(geojson)
    except Exception:
        return False
    from shapely.geometry import box

    return geom.intersects(box(*bbox))


def union_geometry(geometries: list[BaseGeometry]) -> BaseGeometry:
    if not geometries:
        raise UnprocessableError("no geometries supplied")
    return unary_union(geometries)

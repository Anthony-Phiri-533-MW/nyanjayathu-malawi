"""Dataset browsing: filtering, detail assembly and descriptive band statistics.

Band statistics are *descriptive only* (count/min/max/mean/median/spread) and
are labelled as such; they are not validated products and are computed on a
downsampled window to bound memory.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import count_query
from app.core.errors import NotFoundError
from app.models import Dataset, IndicatorResult, QualityAssessment
from app.services.spatial import geojson_intersects

RASTER_FORMATS = ("geotiff", "tiff")


def get_dataset(db: Session, dataset_id: int) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError(f"Dataset {dataset_id} not found")
    return dataset


def list_datasets(
    db: Session,
    *,
    page: int = 1,
    size: int = 20,
    search: str | None = None,
    provider_key: str | None = None,
    category: str | None = None,
    kind: str | None = None,
    quality_flag: str | None = None,
    study_area_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> tuple[list[Dataset], int]:
    stmt = select(Dataset)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Dataset.title.ilike(like),
                Dataset.provider_key.ilike(like),
                Dataset.product_type.ilike(like),
            )
        )
    if provider_key:
        stmt = stmt.where(Dataset.provider_key == provider_key)
    if category:
        stmt = stmt.where(Dataset.category == category)
    if kind:
        stmt = stmt.where(Dataset.kind == kind)
    if quality_flag:
        stmt = stmt.where(Dataset.quality_flag == quality_flag)
    if study_area_id is not None:
        stmt = stmt.where(Dataset.study_area_id == study_area_id)
    if start_date is not None:
        stmt = stmt.where(or_(Dataset.end_date.is_(None), Dataset.end_date >= start_date))
    if end_date is not None:
        stmt = stmt.where(or_(Dataset.start_date.is_(None), Dataset.start_date <= end_date))

    if bbox is not None:
        rows = [
            d
            for d in db.execute(stmt.order_by(Dataset.created_at.desc(), Dataset.id.desc())).scalars()
            if d.coverage_geojson is None or geojson_intersects(d.coverage_geojson, bbox)
        ]
        offset = (page - 1) * size
        return rows[offset : offset + size], len(rows)

    total = count_query(stmt, db)
    offset = (page - 1) * size
    rows = list(
        db.execute(
            stmt.order_by(Dataset.created_at.desc(), Dataset.id.desc()).offset(offset).limit(size)
        ).scalars()
    )
    return rows, total


def quality_assessments(db: Session, dataset: Dataset) -> list[QualityAssessment]:
    return list(
        db.execute(
            select(QualityAssessment)
            .where(
                QualityAssessment.subject_type == "dataset",
                QualityAssessment.subject_id == dataset.id,
            )
            .order_by(QualityAssessment.created_at.desc(), QualityAssessment.id.desc())
        ).scalars()
    )


def indicator_result_count(db: Session, dataset: Dataset) -> int:
    return db.execute(
        select(func.count())
        .select_from(IndicatorResult)
        .where(IndicatorResult.dataset_id == dataset.id)
    ).scalar_one()


def _band_stats(values: np.ndarray) -> dict[str, Any]:
    finite = values[np.isfinite(values)]
    total = int(values.size)
    if finite.size == 0:
        return {
            "count": 0,
            "total": total,
            "nodata_fraction": 1.0,
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
            "std": None,
            "p05": None,
            "p95": None,
        }
    return {
        "count": int(finite.size),
        "total": total,
        "nodata_fraction": round(1.0 - finite.size / total, 6) if total else 1.0,
        "min": round(float(np.min(finite)), 6),
        "max": round(float(np.max(finite)), 6),
        "mean": round(float(np.mean(finite)), 6),
        "median": round(float(np.median(finite)), 6),
        "std": round(float(np.std(finite)), 6),
        "p05": round(float(np.percentile(finite, 5)), 6),
        "p95": round(float(np.percentile(finite, 95)), 6),
    }


def band_statistics(dataset: Dataset, *, max_dim: int = 1024) -> dict[str, Any]:
    """Descriptive statistics for one granule of a raster dataset."""
    if (dataset.format or "").lower() not in RASTER_FORMATS:
        return {
            "applicable": False,
            "reason": f"dataset format '{dataset.format}' does not support raster band statistics",
        }
    granules = (dataset.metadata_json or {}).get("granules") or []
    granule = next((g for g in granules if g.get("path") or g.get("bands")), None)
    if granule is None:
        return {"applicable": False, "reason": "dataset has no raster granules"}
    try:
        from app.processing.pipeline import load_granule

        reads = load_granule(dataset, granule, bbox=None, max_dim=max_dim)
    except Exception as exc:
        return {"applicable": True, "error": f"{type(exc).__name__}: {exc}"}

    bands = {}
    for name, read in sorted(reads.items()):
        bands[name] = _band_stats(np.asarray(read.data[0], dtype="float64"))
    return {
        "applicable": True,
        "granule_id": granule.get("id"),
        "max_dim": max_dim,
        "note": (
            "descriptive statistics over a downsampled read; not a validated product and "
            "not an area-weighted summary"
        ),
        "bands": bands,
    }

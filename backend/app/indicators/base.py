"""Shared toolkit for indicator computation.

Indicator computers read *observed* datasets (or composites derived from them),
compute a single documented quantity, and attach an explicit quality decision
plus provenance.  They never invent values: when a quantity cannot be computed
the result row stores ``value = NULL`` with a reason.
"""
from __future__ import annotations

import csv
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import numpy as np
from shapely.geometry.base import BaseGeometry
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import UnprocessableError
from app.models import Dataset, IndicatorDefinition, IndicatorResult, StudyArea, User
from app.processing import cloud_mask as cm
from app.processing import quality as qmod
from app.processing import water_mask as wm
from app.processing.io import RasterRead
from app.services.spatial import parse_geojson_geometry
from app.services.storage import absolute

log = logging.getLogger("lakewatch.indicators")

INDICATOR_ALGORITHM_VERSION = "1.0.0"
DATASET_KINDS = ("observed", "composite", "processed")
RASTER_FORMATS = ("geotiff", "tiff")


# ---------------------------------------------------------------- selection
@dataclass
class Selection:
    datasets: list[Dataset]
    study_area: StudyArea | None
    start: date | None = None
    end: date | None = None
    notes: list[str] = field(default_factory=list)

    def boundary(self) -> BaseGeometry | None:
        if self.study_area is None:
            return None
        return parse_geojson_geometry(self.study_area.boundary_geojson, allowed=["Polygon", "MultiPolygon"])


def dataset_capabilities(dataset: Dataset) -> set[str]:
    return set((dataset.metadata_json or {}).get("capabilities") or [])


def matches_requirements(dataset: Dataset, requires: Iterable[str] | None) -> bool:
    requires = list(requires or [])
    if not requires:
        return True
    kinds = [r for r in requires if r in DATASET_KINDS]
    caps = [r for r in requires if r not in DATASET_KINDS]
    if kinds and dataset.kind not in kinds:
        return False
    available = dataset_capabilities(dataset)
    return all(cap in available for cap in caps)


def select_datasets(
    db: Session,
    *,
    dataset_ids: list[int] | None = None,
    study_area_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    requires: Iterable[str] | None = None,
) -> Selection:
    """Resolve the datasets an indicator applies to, with date/area/capability filters."""
    if dataset_ids:
        rows = list(
            db.execute(select(Dataset).where(Dataset.id.in_(dataset_ids))).scalars()
        )
        missing = sorted(set(dataset_ids) - {d.id for d in rows})
        if missing:
            raise UnprocessableError(f"Unknown dataset id(s): {missing}")
        notes: list[str] = []
    else:
        rows = list(db.execute(select(Dataset).order_by(Dataset.created_at.asc())).scalars())
        notes = []

    study_area = db.get(StudyArea, study_area_id) if study_area_id else None

    selected: list[Dataset] = []
    for dataset in rows:
        if study_area is not None and dataset.study_area_id not in (None, study_area.id):
            continue
        d_start = dataset.start_date
        d_end = dataset.end_date or dataset.start_date
        if start is not None and d_end is not None and d_end < start:
            continue
        if end is not None and d_start is not None and d_start > end:
            continue
        if not matches_requirements(dataset, requires):
            continue
        selected.append(dataset)

    if study_area is None and selected:
        # keep the study-area context when the selection implies one
        implied = {d.study_area_id for d in selected if d.study_area_id}
        if len(implied) == 1:
            study_area = db.get(StudyArea, next(iter(implied)))
    return Selection(datasets=selected, study_area=study_area, start=start, end=end, notes=notes)


# ---------------------------------------------------------------- loading
@dataclass
class Timeline:
    dataset: Dataset
    granule: dict
    date: date | None
    reads: dict[str, RasterRead]


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text or text.lower() == "composite":
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def sensor_for(provider_key: str) -> str:
    from app.processing.pipeline import PROVIDER_SENSOR

    return PROVIDER_SENSOR.get(provider_key, provider_key)


def granule_max_dim(dataset: Dataset) -> int | None:
    cfg = (dataset.metadata_json or {}).get("ingestion_config") or {}
    if dataset.data_source is not None and dataset.data_source.ingestion_config_json:
        cfg = {**cfg, **(dataset.data_source.ingestion_config_json or {})}
    try:
        value = cfg.get("max_dim", 4096)
        return int(value) if value else None
    except (TypeError, ValueError):
        return 4096


def bbox_for(dataset: Dataset, study_area: StudyArea | None) -> tuple[float, float, float, float] | None:
    if study_area is not None:
        return (study_area.minx, study_area.miny, study_area.maxx, study_area.maxy)
    coverage = dataset.coverage_geojson
    if coverage:
        try:
            geom = parse_geojson_geometry(coverage)
            return tuple(geom.bounds)  # type: ignore[return-value]
        except Exception:
            return None
    return None


def load_timeline(
    selection: Selection,
    *,
    formats: tuple[str, ...] = RASTER_FORMATS,
    max_granules: int = 600,
    errors: list[dict[str, Any]] | None = None,
) -> list[Timeline]:
    """Load every readable raster granule in the selection, windowed to the AOI."""
    from app.processing.pipeline import load_granule

    out: list[Timeline] = []
    for dataset in selection.datasets:
        fmt = (dataset.format or "geotiff").lower()
        if fmt not in formats:
            continue
        bbox = bbox_for(dataset, selection.study_area)
        max_dim = granule_max_dim(dataset)
        for granule in (dataset.metadata_json or {}).get("granules") or []:
            try:
                reads = load_granule(dataset, granule, bbox=bbox, max_dim=max_dim)
            except Exception as exc:  # unreadable granule -> recorded, not fatal
                if errors is not None:
                    errors.append({"dataset_id": dataset.id, "granule": granule.get("id"), "error": str(exc)[:300]})
                continue
            observed = parse_date(granule.get("date")) or dataset.start_date
            out.append(Timeline(dataset=dataset, granule=granule, date=observed, reads=reads))
            if len(out) >= max_granules:
                out.sort(key=lambda t: (t.date or date.min, t.dataset.id))
                return out
    out.sort(key=lambda t: (t.date or date.min, t.dataset.id))
    return out


# ---------------------------------------------------------------- masks
def clear_mask_for(reads: dict[str, RasterRead], sensor: str) -> tuple[np.ndarray | None, str]:
    qa_read = reads.get("qa")
    if qa_read is None:
        return None, "none (no QA band in dataset)"
    qa = qa_read.data[0]
    if sensor == "sentinel2":
        return cm.s2_scl_clear_mask(qa), "Sentinel-2 SCL classes"
    if sensor == "landsat":
        return cm.landsat_qa_clear_mask(qa), "Landsat QA_PIXEL bits"
    if sensor == "modis":
        native = qa_read.band_names[0] if qa_read.band_names else ""
        if native in ("QC_1km", "QC_Day"):
            return cm.modis_lst_qc_clear_mask(qa), "MODIS LST QC_1km bits"
        return cm.modis_state_clear_mask(qa), "MODIS state QA bits"
    return None, f"none (no cloud rule for sensor '{sensor}')"


def inside_mask(ref: RasterRead, boundary: BaseGeometry | None) -> np.ndarray:
    if boundary is None:
        return np.ones((ref.data.shape[1], ref.data.shape[2]), dtype=bool)
    from app.processing.io import geometry_inside_mask

    return geometry_inside_mask(ref, boundary)


def water_mask_from(
    reads: dict[str, RasterRead],
    *,
    boundary: BaseGeometry | None,
    valid: np.ndarray,
    method: str = "mndwi",
    threshold: float = wm.DEFAULT_MNDWI_THRESHOLD,
) -> wm.WaterMaskResult | None:
    green = reads.get("green")
    swir = reads.get("swir1")
    nir = reads.get("nir")
    if green is None:
        return None
    if method == "mndwi" and swir is None:
        if nir is None:
            return None
        method = "ndwi"
    if method == "ndwi" and nir is None:
        return None
    return wm.water_mask(
        green.data[0],
        swir.data[0] if swir is not None and method == "mndwi" else None,
        nir.data[0] if nir is not None and method == "ndwi" else None,
        method=method,
        threshold=threshold,
        valid_mask=valid,
    )


def pixel_areas(ref: RasterRead) -> np.ndarray:
    from app.processing.io import pixel_area_m2

    return pixel_area_m2(ref.transform, ref.crs, (ref.data.shape[1], ref.data.shape[2]))


# ---------------------------------------------------------------- quality
@dataclass
class QualitySummary:
    decision: qmod.QualityDecision
    stats: qmod.MissingDataStats


def quality_for(
    *,
    valid: np.ndarray,
    inside: np.ndarray,
    cloud_fraction: float | None = None,
    unvalidated: bool = False,
    extra_flags: list[tuple[str, str]] | None = None,
) -> QualitySummary:
    stats = qmod.assess_missing(valid, inside)
    decision = qmod.evaluate_quality(
        coverage_fraction=stats.valid_fraction,
        cloud_fraction=cloud_fraction,
        missing=stats,
        unvalidated=unvalidated,
        extra_flags=extra_flags,
    )
    return QualitySummary(decision=decision, stats=stats)


def cloud_fraction_for(clear: np.ndarray | None, inside: np.ndarray) -> float | None:
    if clear is None:
        return None
    total = int(inside.sum())
    if not total:
        return None
    return float((inside & ~clear).sum()) / total


# ---------------------------------------------------------------- rows
def make_result(
    ctx: IndicatorContext,
    *,
    value: float | None,
    unit: str,
    observed_start: date,
    observed_end: date,
    quality: QualitySummary | None = None,
    temporal_resolution: str = "instant",
    spatial_resolution: str = "",
    dataset: Dataset | None = None,
    product_id: int | None = None,
    provenance: dict[str, Any] | None = None,
    parameters: dict[str, Any] | None = None,
    uncertainty: dict[str, Any] | None = None,
    extent: dict[str, Any] | None = None,
) -> IndicatorResult:
    decision = quality.decision if quality else None
    stats = quality.stats if quality else None
    return IndicatorResult(
        definition_id=ctx.definition.id,
        indicator_key=ctx.definition.key,
        study_area_id=ctx.selection.study_area.id if ctx.selection.study_area else None,
        dataset_id=dataset.id if dataset is not None else None,
        product_id=product_id,
        job_id=ctx.job_id,
        value=value,
        unit=unit,
        observed_start=observed_start,
        observed_end=observed_end,
        temporal_resolution=temporal_resolution,
        spatial_resolution=spatial_resolution,
        spatial_extent_geojson=extent,
        quality_flag=decision.flag if decision else "UNVALIDATED",
        quality_reason=decision.reason if decision else "",
        flag_reasons_json=(decision.reasons if decision else None),
        coverage_fraction=(stats.valid_fraction if stats else None),
        missing_fraction=(stats.missing_fraction if stats else None),
        uncertainty_json=uncertainty,
        provenance_json=provenance,
        parameters_json=parameters,
        created_by_id=ctx.actor.id if ctx.actor else None,
    )


def failed_result(
    ctx: IndicatorContext,
    *,
    reason: str,
    observed_start: date,
    observed_end: date,
    dataset: Dataset | None = None,
    coords: list[float] | None = None,
) -> IndicatorResult:
    stats = qmod.MissingDataStats(0, 0, 0, 0.0, 1.0)
    decision = qmod.evaluate_quality(missing=stats, processing_failed=True)
    extent = {"type": "Point", "coordinates": coords} if coords else None
    return make_result(
        ctx,
        value=None,
        unit=ctx.definition.unit,
        observed_start=observed_start,
        observed_end=observed_end,
        quality=QualitySummary(decision=decision, stats=stats),
        dataset=dataset,
        provenance={"reason": reason, "algorithm_version": INDICATOR_ALGORITHM_VERSION},
        extent=extent,
    )


# ---------------------------------------------------------------- tables
def csv_rows(path_rel: str) -> list[dict[str, Any]]:
    path = absolute(path_rel)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def csv_series(dataset: Dataset, column: str) -> list[tuple[date, float]]:
    """(date, value) pairs from a CSV granule; blanks are skipped, never zero-filled."""
    out: list[tuple[date, float]] = []
    for granule in (dataset.metadata_json or {}).get("granules") or []:
        path_rel = granule.get("path")
        if not path_rel:
            continue
        for row in csv_rows(path_rel):
            day = parse_date(row.get("date"))
            raw = row.get(column)
            if day is None or raw in (None, ""):
                continue
            try:
                out.append((day, float(raw)))
            except (TypeError, ValueError):
                continue
    out.sort(key=lambda item: item[0])
    return out


# ---------------------------------------------------------------- context
@dataclass
class IndicatorContext:
    db: Session
    definition: IndicatorDefinition
    selection: Selection
    params: dict[str, Any] = field(default_factory=dict)
    actor: User | None = None
    job_id: int | None = None
    progress: Callable[[float, str], None] = lambda _f, _m="": None

    @property
    def boundary(self) -> BaseGeometry | None:
        return self.selection.boundary()

    @property
    def unit(self) -> str:
        return self.definition.unit


def persist(db: Session, results: list[IndicatorResult]) -> list[IndicatorResult]:
    for row in results:
        db.add(row)
    db.flush()
    return results

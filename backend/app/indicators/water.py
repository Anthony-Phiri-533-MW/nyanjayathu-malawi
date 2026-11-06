"""Water-extent indicators (planimetric area, NOT water level)."""
from __future__ import annotations

from datetime import date
from math import sqrt
from typing import Any

import numpy as np
from pyproj import Transformer
from rasterio.features import shapes
from shapely import transform as transform_geometry
from shapely.geometry import mapping, shape
from shapely.ops import unary_union
from sqlalchemy import select

from app.core.errors import UnprocessableError
from app.indicators.base import (
    INDICATOR_ALGORITHM_VERSION,
    IndicatorContext,
    QualitySummary,
    clear_mask_for,
    cloud_fraction_for,
    failed_result,
    inside_mask,
    load_timeline,
    make_result,
    pixel_areas,
    quality_for,
    sensor_for,
    water_mask_from,
)
from app.models import Dataset, IndicatorResult
from app.processing import quality as qmod
from app.processing import water_mask as wm
from app.processing.io import RasterRead

METHOD_LABEL = {"mndwi": "MNDWI (Xu, 2006)", "ndwi": "NDWI (McFeeters, 1996)"}


def _water_extent_geometry(water_mask: np.ndarray, ref: RasterRead) -> dict[str, Any] | None:
    """Build a simplified WGS84 shoreline polygon from the classified pixels."""
    if not water_mask.any():
        return None

    pixel_area_m2 = float(np.nanmedian(pixel_areas(ref)))
    tolerance_m = max(sqrt(pixel_area_m2) * 0.6, 5.0)
    to_equal_area = Transformer.from_crs(ref.crs, "EPSG:6933", always_xy=True).transform
    to_wgs84 = Transformer.from_crs("EPSG:6933", "EPSG:4326", always_xy=True).transform
    mask = water_mask.astype(np.uint8)
    polygons = []

    for geometry, _value in shapes(mask, mask=water_mask, transform=ref.transform, connectivity=8):
        polygon = transform_geometry(shape(geometry), to_equal_area, interleaved=False)
        simplified = polygon.simplify(tolerance_m, preserve_topology=True)
        if not simplified.is_empty:
            polygons.append(simplified)

    if not polygons:
        return None

    dissolved = transform_geometry(unary_union(polygons), to_wgs84, interleaved=False)
    return mapping(dissolved)


def _dates(ctx: IndicatorContext, timeline) -> tuple[date, date]:
    start = timeline.date or timeline.dataset.start_date or ctx.selection.start
    end = timeline.date or timeline.dataset.end_date or ctx.selection.end
    today = date.today()
    return (start or today), (end or start or today)

def compute_water_extent(ctx: IndicatorContext) -> list[IndicatorResult]:
    method = str(ctx.params.get("method") or "mndwi")
    threshold = float(ctx.params.get("threshold", wm.DEFAULT_MNDWI_THRESHOLD))
    errors: list[dict[str, Any]] = []
    timelines = load_timeline(ctx.selection, errors=errors)
    if not timelines:
        detail = f" (first load error: {errors[0]['error']})" if errors else ""
        raise UnprocessableError(
            "No readable raster granules in the selection for water_extent" + detail
        )

    boundary = ctx.boundary
    results: list[IndicatorResult] = []
    n = len(timelines)
    for idx, timeline in enumerate(timelines):
        ctx.progress((idx + 0.5) / n, f"water extent {timeline.date or timeline.dataset.id}")
        reads = timeline.reads
        ref = reads.get("green")
        start, end = _dates(ctx, timeline)
        if ref is None:
            results.append(
                failed_result(
                    ctx,
                    reason=(
                        "dataset has no green band; water extent needs green plus SWIR1 (MNDWI) "
                        "or NIR (NDWI)"
                    ),
                    observed_start=start,
                    observed_end=end,
                    dataset=timeline.dataset,
                )
            )
            continue

        inside = inside_mask(ref, boundary)
        clear, cloud_method = clear_mask_for(reads, sensor_for(timeline.dataset.provider_key))
        cloud_fraction = cloud_fraction_for(clear, inside)

        valid = np.isfinite(ref.data[0]) & inside
        if clear is not None:
            valid &= clear

        mask_result = water_mask_from(
            reads, boundary=boundary, valid=valid, method=method, threshold=threshold
        )
        if mask_result is None:
            results.append(
                failed_result(
                    ctx,
                    reason=(
                        f"{method.upper()} requires "
                        + ("green + SWIR1" if method == "mndwi" else "green + NIR")
                        + " bands; the dataset does not provide them"
                    ),
                    observed_start=start,
                    observed_end=end,
                    dataset=timeline.dataset,
                )
            )
            continue

        usable = valid & mask_result.valid_mask
        if not usable.any():
            results.append(
                failed_result(
                    ctx,
                    reason="no valid pixels intersect the study-area boundary after raster and cloud masking",
                    observed_start=start,
                    observed_end=end,
                    dataset=timeline.dataset,
                )
            )
            continue

        areas = pixel_areas(ref)
        water_pixels = mask_result.water_mask & usable & inside
        area_km2 = float((water_pixels * areas[:, None]).sum()) / 1_000_000.0
        extent_geojson = _water_extent_geometry(water_pixels, ref)
        quality = quality_for(valid=usable, inside=inside, cloud_fraction=cloud_fraction)

        provenance = {
            "algorithm_version": INDICATOR_ALGORITHM_VERSION,
            "method": METHOD_LABEL.get(mask_result.method, mask_result.method),
            "threshold": mask_result.threshold,
            "threshold_note": "threshold is provisional and configurable; not calibrated for Lake Malawi",
            "cloud_mask": cloud_method,
            "pixel_area": "per-row geodesic area (geographic CRS)" if not ref.crs.is_projected else "projected pixel area",
            "dataset_id": timeline.dataset.id,
            "granule_id": timeline.granule.get("id"),
            "provider_key": timeline.dataset.provider_key,
            "water_pixels": int(water_pixels.sum()),
            "usable_pixels": int(usable.sum()),
            "notes": [
                "water extent is a planimetric area, not a water level",
            ],
        }
        results.append(
            make_result(
                ctx,
                value=round(area_km2, 3),
                unit="km²",
                observed_start=start,
                observed_end=end,
                quality=quality,
                temporal_resolution="instant",
                spatial_resolution=str(timeline.dataset.resolution_m or ""),
                dataset=timeline.dataset,
                provenance=provenance,
                parameters={"method": mask_result.method, "threshold": mask_result.threshold},
                extent=extent_geojson,
            )
        )
    ctx.progress(1.0, "water extent computed")
    return results


def compute_water_extent_change(ctx: IndicatorContext) -> list[IndicatorResult]:
    db = ctx.db
    stmt = select(IndicatorResult).where(IndicatorResult.indicator_key == "water_extent")
    if ctx.selection.study_area is not None:
        stmt = stmt.where(IndicatorResult.study_area_id == ctx.selection.study_area.id)
    stmt = stmt.order_by(IndicatorResult.observed_start.asc(), IndicatorResult.id.asc())
    rows = list(db.execute(stmt).scalars())

    if ctx.selection.datasets:
        allowed = {d.id for d in ctx.selection.datasets}
        rows = [r for r in rows if r.dataset_id in allowed]

    usable = [r for r in rows if r.value is not None and r.quality_flag in ("VALID", "LOW_QUALITY")]
    usable = [r for r in usable if ctx.selection.start is None or r.observed_end >= ctx.selection.start]
    usable = [r for r in usable if ctx.selection.end is None or r.observed_start <= ctx.selection.end]
    if len(usable) < 2:
        raise UnprocessableError(
            "water_extent_change needs at least two usable water_extent results "
            "(run water_extent first for at least two observation dates)"
        )

    results: list[IndicatorResult] = []
    for a, b in zip(usable, usable[1:], strict=False):
        if a.observed_start == b.observed_start and a.dataset_id == b.dataset_id:
            continue
        delta = float(b.value) - float(a.value)  # type: ignore[arg-type]
        flags: list[tuple[str, str]] = []
        if "LOW_QUALITY" in (a.quality_flag, b.quality_flag):
            flags.append(("LOW_QUALITY", "at least one observation was flagged LOW_QUALITY"))
        coverages = [x.coverage_fraction for x in (a, b) if x.coverage_fraction is not None]
        coverage = min(coverages) if coverages else None
        decision = qmod.evaluate_quality(coverage_fraction=coverage, extra_flags=flags)
        stats = qmod.MissingDataStats(
            total_pixels=0,
            valid_pixels=0,
            missing_pixels=0,
            valid_fraction=coverage if coverage is not None else 0.0,
            missing_fraction=(1.0 - coverage) if coverage is not None else 1.0,
        )
        provenance = {
            "algorithm_version": INDICATOR_ALGORITHM_VERSION,
            "from_result_id": a.id,
            "to_result_id": b.id,
            "from_observed_start": a.observed_start.isoformat(),
            "to_observed_start": b.observed_start.isoformat(),
            "from_value_km2": a.value,
            "to_value_km2": b.value,
            "notes": [
                "difference between two mapped water extents; it is not a water-level change",
                "pairs are formed from consecutive quality-passing water_extent results",
            ],
        }
        results.append(
            make_result(
                ctx,
                value=round(delta, 3),
                unit="km²",
                observed_start=b.observed_start,
                observed_end=b.observed_end,
                quality=QualitySummary(decision=decision, stats=stats),
                temporal_resolution="interval",
                dataset=ctx.db.get(Dataset, b.dataset_id) if b.dataset_id else None,
                provenance=provenance,
                parameters={"pair": [a.id, b.id]},
            )
        )
    ctx.progress(1.0, "water extent change computed")
    return results

"""Water-quality indicators.

Two of these are **proxies** (chlorophyll-a band ratio and NDTI turbidity):
they are unitless optical indices, are flagged ``UNVALIDATED`` and must never be
reported as concentrations.  Surface-water temperature is a measured thermal
quantity (Kelvin -> degrees Celsius with the documented source scaling already
applied at ingestion).

Every computer restricts statistics to *water* pixels inside the study area
that survived cloud masking; when no water pixels are usable no value is
invented - the result row stores ``value = NULL`` with a reason.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import numpy as np

from app.core.errors import UnprocessableError
from app.indicators.base import (
    INDICATOR_ALGORITHM_VERSION,
    IndicatorContext,
    clear_mask_for,
    cloud_fraction_for,
    failed_result,
    inside_mask,
    load_timeline,
    make_result,
    quality_for,
    sensor_for,
    water_mask_from,
)
from app.models import Dataset, IndicatorResult
from app.processing import water_mask as wm

PROXY_NOTES = [
    "optical proxy index: unitless, not a concentration",
    "not validated against in-situ measurements for Lake Malawi",
    "only clear water pixels are aggregated",
]


def _dates(ctx: IndicatorContext, timeline) -> tuple[date, date]:
    start = timeline.date or timeline.dataset.start_date or ctx.selection.start
    end = timeline.date or timeline.dataset.end_date or ctx.selection.end
    today = date.today()
    return (start or today), (end or start or today)


def _safe_ratio(red: np.ndarray, green: np.ndarray) -> np.ndarray:
    """Red / Green over pixels with a positive green reflectance."""
    r = np.asarray(red, "float64")
    g = np.asarray(green, "float64")
    out = np.full(r.shape, np.nan, dtype="float64")
    ok = np.isfinite(r) & np.isfinite(g) & (g > 1e-6)
    out[ok] = r[ok] / g[ok]
    return out.astype("float32")


def _describe(value: float, *, convert: Callable[[float], float] | None = None) -> float:
    return float(convert(value)) if convert else float(value)


def _optical_proxy(
    ctx: IndicatorContext,
    *,
    index_name: str,
    index_fn: Callable[[dict], np.ndarray],
    bands_needed: tuple[str, ...],
    unit: str,
    unvalidated: bool,
    notes: list[str],
    convert: Callable[[float], float] | None = None,
    conversion_note: str | None = None,
) -> list[IndicatorResult]:
    method = str(ctx.params.get("method") or "mndwi")
    threshold = float(ctx.params.get("threshold", wm.DEFAULT_MNDWI_THRESHOLD))
    errors: list[dict[str, Any]] = []
    timelines = load_timeline(ctx.selection, errors=errors)
    if not timelines:
        detail = f" (first load error: {errors[0]['error']})" if errors else ""
        raise UnprocessableError(
            f"No readable raster granules in the selection for {ctx.definition.key}" + detail
        )

    boundary = ctx.boundary
    results: list[IndicatorResult] = []
    n = len(timelines)
    for idx, timeline in enumerate(timelines):
        reads = timeline.reads
        ref = next((reads[b] for b in bands_needed if b in reads), None)
        start, end = _dates(ctx, timeline)
        ctx.progress((idx + 0.5) / n, f"{ctx.definition.key} {timeline.date or timeline.dataset.id}")

        missing = [b for b in bands_needed if b not in reads]
        if ref is None or missing:
            results.append(
                failed_result(
                    ctx,
                    reason=(
                        f"dataset is missing required band(s) {missing or list(bands_needed)} "
                        f"for {ctx.definition.key}"
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

        valid = np.ones((ref.data.shape[1], ref.data.shape[2]), dtype=bool)
        for band in bands_needed:
            valid &= np.isfinite(reads[band].data[0])
        valid &= inside
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
                        "water discrimination requires green + SWIR1 (MNDWI) or green + NIR "
                        "(NDWI) bands; the dataset does not provide them"
                    ),
                    observed_start=start,
                    observed_end=end,
                    dataset=timeline.dataset,
                )
            )
            continue

        usable = valid & mask_result.valid_mask
        water_pixels = usable & mask_result.water_mask
        n_water = int(water_pixels.sum())
        if n_water == 0:
            results.append(
                failed_result(
                    ctx,
                    reason=(
                        "no clear water pixels were identified in the study area for this "
                        "observation (cloud cover, no water or no valid retrieval)"
                    ),
                    observed_start=start,
                    observed_end=end,
                    dataset=timeline.dataset,
                )
            )
            continue

        index = index_fn(reads)
        values = np.asarray(index[water_pixels], dtype="float64")
        values = values[np.isfinite(values)]
        if values.size == 0:
            results.append(
                failed_result(
                    ctx,
                    reason=f"{index_name} was undefined for every clear water pixel",
                    observed_start=start,
                    observed_end=end,
                    dataset=timeline.dataset,
                )
            )
            continue

        raw_median = float(np.median(values))
        value = _describe(raw_median, convert=convert)
        quality = quality_for(
            valid=usable, inside=inside, cloud_fraction=cloud_fraction, unvalidated=unvalidated
        )
        provenance = {
            "algorithm_version": INDICATOR_ALGORITHM_VERSION,
            "index": index_name,
            "aggregation": "median over clear water pixels inside the study area",
            "bands_used": list(bands_needed),
            "water_mask_method": mask_result.method,
            "water_mask_threshold": mask_result.threshold,
            "water_mask_threshold_note": "threshold is provisional and configurable",
            "cloud_mask": cloud_method,
            "n_water_pixels": n_water,
            "dataset_id": timeline.dataset.id,
            "granule_id": timeline.granule.get("id"),
            "provider_key": timeline.dataset.provider_key,
            "notes": notes,
        }
        if conversion_note:
            provenance["unit_conversion"] = conversion_note
        results.append(
            make_result(
                ctx,
                value=round(value, 6),
                unit=unit,
                observed_start=start,
                observed_end=end,
                quality=quality,
                temporal_resolution="instant",
                spatial_resolution=str(timeline.dataset.resolution_m or ""),
                dataset=timeline.dataset,
                provenance=provenance,
                parameters={
                    "method": mask_result.method,
                    "threshold": mask_result.threshold,
                    "aggregation": "median",
                },
                uncertainty={
                    "n_pixels": int(values.size),
                    "p25": round(float(np.percentile(values, 25)), 6),
                    "p75": round(float(np.percentile(values, 75)), 6),
                    "std": round(float(np.std(values)), 6),
                },
                extent=timeline.dataset.coverage_geojson,
            )
        )
    ctx.progress(1.0, f"{ctx.definition.key} computed")
    return results


def compute_chlorophyll_a_proxy(ctx: IndicatorContext) -> list[IndicatorResult]:
    """Normalised red/green band ratio over clear water pixels (unitless)."""

    def index(reads: dict) -> np.ndarray:
        return _safe_ratio(reads["red"].data[0], reads["green"].data[0])

    return _optical_proxy(
        ctx,
        index_name="red/green reflectance ratio",
        index_fn=index,
        bands_needed=("red", "green"),
        unit=ctx.definition.unit,
        unvalidated=True,
        notes=PROXY_NOTES
        + [
            "band ratios respond to suspended solids and atmospheric residuals as well as "
            "chlorophyll-a",
        ],
    )


def compute_turbidity_proxy(ctx: IndicatorContext) -> list[IndicatorResult]:
    """NDTI = (Red - Green) / (Red + Green) over clear water pixels (unitless)."""

    def index(reads: dict) -> np.ndarray:
        return wm.ndti(reads["red"].data[0], reads["green"].data[0])

    return _optical_proxy(
        ctx,
        index_name="NDTI (normalised difference turbidity index)",
        index_fn=index,
        bands_needed=("red", "green"),
        unit=ctx.definition.unit,
        unvalidated=True,
        notes=PROXY_NOTES
        + [
            "NDTI (Lymburner et al., 2016) is a relative suspended-material indicator; "
            "positive values indicate higher sediment load",
        ],
    )


def _thermal_is_kelvin(dataset: Dataset, median: float) -> tuple[bool, str]:
    """Decide whether stored thermal values are Kelvin.

    Preference order: (1) the unit recorded at ingestion, (2) a defensible
    magnitude check (a lake surface in Kelvin is > 150; in Celsius it is not).
    """
    bands = (dataset.metadata_json or {}).get("bands") or {}
    if isinstance(bands, dict):
        for meta in bands.values():
            if isinstance(meta, dict) and str(meta.get("unit") or "").strip().upper() == "K":
                return True, "unit recorded at ingestion is K"
    if isinstance(dataset.bands_json, list):
        for rec in dataset.bands_json:
            if isinstance(rec, dict) and str(rec.get("unit") or "").strip().upper() == "K":
                return True, "unit recorded in dataset band metadata is K"
    if median > 150.0:
        return True, "values exceed 150 and are interpreted as Kelvin (magnitude check)"
    return False, "values below 150 are assumed to already be degrees Celsius"


def compute_surface_water_temperature(ctx: IndicatorContext) -> list[IndicatorResult]:
    def index(reads: dict) -> np.ndarray:
        return np.asarray(reads["thermal"].data[0], "float32")

    method = str(ctx.params.get("method") or "mndwi")
    threshold = float(ctx.params.get("threshold", wm.DEFAULT_MNDWI_THRESHOLD))
    errors: list[dict[str, Any]] = []
    timelines = load_timeline(ctx.selection, errors=errors)
    if not timelines:
        detail = f" (first load error: {errors[0]['error']})" if errors else ""
        raise UnprocessableError(
            "No readable raster granules in the selection for surface_water_temperature" + detail
        )

    boundary = ctx.boundary
    results: list[IndicatorResult] = []
    n = len(timelines)
    for idx, timeline in enumerate(timelines):
        reads = timeline.reads
        ref = reads.get("thermal")
        start, end = _dates(ctx, timeline)
        ctx.progress((idx + 0.5) / n, f"surface temperature {timeline.date or timeline.dataset.id}")
        if ref is None:
            results.append(
                failed_result(
                    ctx,
                    reason=(
                        "dataset has no thermal band; surface_water_temperature only applies to "
                        "products with a thermal infrared band (Landsat ST_B10, MODIS LST)"
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
                        "water discrimination requires green + SWIR1 (MNDWI) or green + NIR "
                        "(NDWI) bands; the dataset does not provide them"
                    ),
                    observed_start=start,
                    observed_end=end,
                    dataset=timeline.dataset,
                )
            )
            continue

        usable = valid & mask_result.valid_mask
        water_pixels = usable & mask_result.water_mask
        values = np.asarray(index(reads)[water_pixels], dtype="float64")
        values = values[np.isfinite(values)]
        if values.size == 0:
            results.append(
                failed_result(
                    ctx,
                    reason="no clear water pixels with a valid thermal retrieval",
                    observed_start=start,
                    observed_end=end,
                    dataset=timeline.dataset,
                )
            )
            continue

        raw_median = float(np.median(values))
        is_kelvin, conversion_reason = _thermal_is_kelvin(timeline.dataset, raw_median)
        if is_kelvin:
            values = values - 273.15
            raw_median = raw_median - 273.15
        quality = quality_for(valid=usable, inside=inside, cloud_fraction=cloud_fraction)
        provenance = {
            "algorithm_version": INDICATOR_ALGORITHM_VERSION,
            "aggregation": "median over clear water pixels inside the study area",
            "bands_used": ["thermal"],
            "water_mask_method": mask_result.method,
            "water_mask_threshold": mask_result.threshold,
            "cloud_mask": cloud_method,
            "n_water_pixels": int(water_pixels.sum()),
            "dataset_id": timeline.dataset.id,
            "granule_id": timeline.granule.get("id"),
            "provider_key": timeline.dataset.provider_key,
            "unit_conversion": (
                "Kelvin -> Celsius: T(degC) = T(K) - 273.15; " + conversion_reason
                if is_kelvin
                else "stored already in degrees Celsius; " + conversion_reason
            ),
            "notes": [
                "thermal band is coarser than the optical bands; the water mask is evaluated on "
                "the thermal grid",
                "skin/brightness temperature, not a bulk in-situ water temperature",
            ],
        }
        results.append(
            make_result(
                ctx,
                value=round(raw_median, 4),
                unit=ctx.definition.unit,
                observed_start=start,
                observed_end=end,
                quality=quality,
                temporal_resolution="instant",
                spatial_resolution=str(timeline.dataset.resolution_m or ""),
                dataset=timeline.dataset,
                provenance=provenance,
                parameters={
                    "method": mask_result.method,
                    "threshold": mask_result.threshold,
                    "aggregation": "median",
                },
                uncertainty={
                    "n_pixels": int(values.size),
                    "p25": round(float(np.percentile(values, 25)), 4),
                    "p75": round(float(np.percentile(values, 75)), 4),
                    "std": round(float(np.std(values)), 4),
                },
                extent=timeline.dataset.coverage_geojson,
            )
        )
    ctx.progress(1.0, "surface water temperature computed")
    return results

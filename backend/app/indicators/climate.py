"""Climate indicators: rainfall totals/anomalies and air-temperature summaries.

Rainfall may arrive as gridded rasters (CHIRPS daily GeoTIFF) or as point
time-series CSV (NASA POWER).  When both are present the provider with the most
daily coverage is used and the others are recorded as excluded, so two products
are never silently added together.  Air temperature is a NASA POWER point
series (2 m air temperature, not a lake-surface temperature).
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
from sqlalchemy import select

from app.core.errors import UnprocessableError
from app.indicators.base import (
    INDICATOR_ALGORITHM_VERSION,
    IndicatorContext,
    QualitySummary,
    bbox_for,
    dataset_capabilities,
    failed_result,
    granule_max_dim,
    inside_mask,
    make_result,
    parse_date,
    pixel_areas,
)
from app.models import Dataset, IndicatorResult
from app.processing import quality as qmod

PRECIP_COLUMNS = ("PRECTOTCORR", "precipitation", "precip", "rainfall")
TEMPERATURE_COLUMNS = ("T2M", "air_temperature", "T2M_MEAN", "temperature")
USABLE_FLAGS = ("VALID", "LOW_QUALITY")


# ---------------------------------------------------------------- helpers
def _csv_column(dataset: Dataset, preferred: tuple[str, ...]) -> str | None:
    columns: list[str] = []
    for granule in (dataset.metadata_json or {}).get("granules") or []:
        for col in granule.get("columns") or []:
            if col not in columns:
                columns.append(str(col))
    for candidate in preferred:
        if candidate in columns:
            return candidate
    for candidate in preferred:
        for col in columns:
            if col.lower() == candidate.lower():
                return col
    return None


def _raster_daily_value(dataset: Dataset, granule: dict, ctx: IndicatorContext) -> float | None:
    """Area-weighted mean of a daily raster over the study-area boundary."""
    from app.processing.pipeline import load_granule

    bbox = bbox_for(dataset, ctx.selection.study_area)
    reads = load_granule(dataset, granule, bbox=bbox, max_dim=granule_max_dim(dataset))
    if not reads:
        return None
    read = next(iter(reads.values()))
    data = read.data[0].astype("float64")
    valid = np.isfinite(data)
    if ctx.boundary is not None:
        inside = inside_mask(read, ctx.boundary)
    else:
        inside = np.ones(data.shape, dtype=bool)
    usable = valid & inside
    if not usable.any():
        return None
    areas = pixel_areas(read)
    weights = np.broadcast_to(areas[:, None], data.shape)
    total_weight = float(weights[usable].sum())
    if total_weight <= 0:
        return None
    return float((data[usable] * weights[usable]).sum() / total_weight)


def _csv_daily_values(dataset: Dataset, preferred: tuple[str, ...]) -> dict[date, float]:
    from app.indicators.base import csv_series

    column = _csv_column(dataset, preferred)
    if column is None:
        return {}
    return {day: value for day, value in csv_series(dataset, column)}


def _values_by_day(dataset: Dataset, ctx: IndicatorContext, columns: tuple[str, ...]) -> dict[date, float]:
    fmt = (dataset.format or "geotiff").lower()
    if fmt in ("csv", "json"):
        return _csv_daily_values(dataset, columns)
    out: dict[date, float] = {}
    for granule in (dataset.metadata_json or {}).get("granules") or []:
        day = parse_date(granule.get("date")) or dataset.start_date
        if day is None:
            continue
        try:
            value = _raster_daily_value(dataset, granule, ctx)
        except Exception:  # unreadable granule -> skipped, never zero-filled
            continue
        if value is None or not np.isfinite(value):
            continue
        out[day] = value
    return out


def _collect_groups(
    ctx: IndicatorContext, capability: str, columns: tuple[str, ...]
) -> tuple[str, dict[date, float], list[str], dict[str, int]]:
    """Pick the best-covered provider group; return (provider, values, excluded, counts)."""
    groups: dict[str, dict[date, float]] = {}
    raster_provider: dict[str, bool] = {}
    for dataset in ctx.selection.datasets:
        if capability not in dataset_capabilities(dataset):
            continue
        values = _values_by_day(dataset, ctx, columns)
        if values:
            groups.setdefault(dataset.provider_key, {}).update(values)
            raster_provider[dataset.provider_key] = raster_provider.get(
                dataset.provider_key, False
            ) or (dataset.format or "geotiff").lower() in ("geotiff", "tiff")
    if not groups:
        raise UnprocessableError(
            f"No readable {capability} observations in the selection; ingest a "
            f"{capability} data source first"
        )
    ranked = sorted(
        groups.items(),
        key=lambda item: (len(item[1]), raster_provider.get(item[0], False)),
        reverse=True,
    )
    provider, values = ranked[0]
    excluded = sorted(name for name, _ in ranked[1:])
    counts = {name: len(vals) for name, vals in groups.items()}
    return provider, values, excluded, counts


def _daily_span(selection, values: dict[date, float]) -> dict[date, float]:
    start, end = selection.start, selection.end
    out: dict[date, float] = {}
    for day, value in values.items():
        if start is not None and day < start:
            continue
        if end is not None and day > end:
            continue
        out[day] = value
    return out


def _availability(selection, days: list[date]) -> tuple[int, float, qmod.MissingDataStats]:
    if not days:
        expected = max(1, ((selection.end - selection.start).days + 1) if selection.start and selection.end else 1)
        stats = qmod.MissingDataStats(expected, 0, expected, 0.0, 1.0)
        return expected, 0.0, stats
    if selection.start and selection.end:
        expected = max(1, (selection.end - selection.start).days + 1)
    else:
        expected = len(days)
    expected = max(expected, len(days))
    availability = min(1.0, len(days) / expected)
    stats = qmod.MissingDataStats(
        total_pixels=expected,
        valid_pixels=len(days),
        missing_pixels=max(0, expected - len(days)),
        valid_fraction=availability,
        missing_fraction=max(0.0, 1.0 - availability),
    )
    return expected, availability, stats


def _decision(availability: float, stats: qmod.MissingDataStats, extra_flags=None) -> qmod.QualityDecision:
    return qmod.evaluate_quality(
        coverage_fraction=availability, missing=stats, extra_flags=extra_flags
    )


def _period_values(
    ctx: IndicatorContext, *, capability: str, columns: tuple[str, ...], aggregate: str
) -> dict[str, Any]:
    provider, values, excluded, counts = _collect_groups(ctx, capability, columns)
    values = _daily_span(ctx.selection, values)
    days = sorted(values)
    expected, availability, stats = _availability(ctx.selection, days)
    if not days:
        raise UnprocessableError(
            f"{capability} observations exist but none fall inside the requested period"
        )
    series = np.asarray([values[d] for d in days], dtype="float64")
    value = float(np.sum(series)) if aggregate == "sum" else float(np.mean(series))
    provenance = {
        "algorithm_version": INDICATOR_ALGORITHM_VERSION,
        "aggregation": (
            "sum of daily area-weighted study-area means"
            if aggregate == "sum"
            else "mean of daily study-area / point values"
        ),
        "provider_used": provider,
        "provider_day_counts": counts,
        "excluded_provider_keys": excluded,
        "exclusion_note": (
            "only the best-covered provider is used so products are not double-counted"
            if excluded
            else None
        ),
        "days_used": [d.isoformat() for d in days],
        "expected_days": expected,
        "availability_fraction": round(availability, 6),
        "daily_values": [[d.isoformat(), round(v, 6)] for d, v in zip(days, series, strict=False)][:400],
        "source_dataset_ids": sorted(
            {
                d.id
                for d in ctx.selection.datasets
                if d.provider_key == provider and capability in dataset_capabilities(d)
            }
        ),
    }
    return {
        "value": value,
        "start": days[0],
        "end": days[-1],
        "availability": availability,
        "stats": stats,
        "provenance": provenance,
        "excluded": excluded,
    }


def _baseline_rows(
    ctx: IndicatorContext, indicator_key: str, *, baseline_start: date | None, baseline_end: date | None
) -> list[IndicatorResult]:
    stmt = select(IndicatorResult).where(
        IndicatorResult.indicator_key == indicator_key,
        IndicatorResult.value.is_not(None),
        IndicatorResult.quality_flag.in_(USABLE_FLAGS),
    )
    if ctx.selection.study_area is not None:
        stmt = stmt.where(IndicatorResult.study_area_id == ctx.selection.study_area.id)
    if baseline_start is not None:
        stmt = stmt.where(IndicatorResult.observed_end >= baseline_start)
    if baseline_end is not None:
        stmt = stmt.where(IndicatorResult.observed_start <= baseline_end)
    return list(ctx.db.execute(stmt.order_by(IndicatorResult.observed_start.asc())).scalars())


def _parse_param_date(value: Any) -> date | None:
    return parse_date(value)


def _anomaly(
    ctx: IndicatorContext,
    *,
    indicator_key: str,
    series_key: str,
    aggregate: str,
) -> list[IndicatorResult]:
    capability = "precipitation" if series_key == "rainfall_summary" else "temperature"
    columns = PRECIP_COLUMNS if capability == "precipitation" else TEMPERATURE_COLUMNS
    period = _period_values(ctx, capability=capability, columns=columns, aggregate=aggregate)

    baseline_start = _parse_param_date(ctx.params.get("baseline_start"))
    baseline_end = _parse_param_date(ctx.params.get("baseline_end"))
    rows = [
        row
        for row in _baseline_rows(
            ctx, series_key, baseline_start=baseline_start, baseline_end=baseline_end
        )
        if not (
            row.observed_start == period["start"]
            and row.observed_end == period["end"]
        )
    ]
    if not rows:
        return [
            failed_result(
                ctx,
                reason=(
                    f"no usable '{series_key}' results exist for a baseline; compute "
                    f"{series_key} for a baseline period first or pass baseline_start/baseline_end"
                ),
                observed_start=period["start"],
                observed_end=period["end"],
            )
        ]

    baseline_values = np.asarray([float(r.value) for r in rows], dtype="float64")
    baseline = float(np.mean(baseline_values))
    value = float(period["value"]) - baseline

    extra: list[tuple[str, str]] = []
    if len(rows) < 2:
        extra.append(
            ("LOW_QUALITY", "baseline is a single existing result; the anomaly is not robust")
        )
    decision = _decision(period["availability"], period["stats"], extra_flags=extra)
    provenance = {
        "algorithm_version": INDICATOR_ALGORITHM_VERSION,
        "period_value": round(float(period["value"]), 6),
        "baseline_value": round(baseline, 6),
        "baseline_n": len(rows),
        "baseline_result_ids": [r.id for r in rows][:200],
        "baseline_start": baseline_start.isoformat() if baseline_start else None,
        "baseline_end": baseline_end.isoformat() if baseline_end else None,
        "baseline_method": (
            "mean of existing usable " + series_key + " results"
            + (" inside the requested baseline window" if baseline_start or baseline_end else " outside this period")
        ),
        "baseline_note": "this is not an official climatological normal",
        "period_sources": period["provenance"],
    }
    return [
        make_result(
            ctx,
            value=round(value, 4),
            unit=ctx.definition.unit,
            observed_start=period["start"],
            observed_end=period["end"],
            quality=QualitySummary(
                decision=decision, stats=period["stats"]
            ),
            temporal_resolution="period",
            provenance=provenance,
            parameters={
                "baseline_start": baseline_start.isoformat() if baseline_start else None,
                "baseline_end": baseline_end.isoformat() if baseline_end else None,
            },
        )
    ]


# ---------------------------------------------------------------- rainfall
def compute_rainfall_summary(ctx: IndicatorContext) -> list[IndicatorResult]:
    period = _period_values(
        ctx, capability="precipitation", columns=PRECIP_COLUMNS, aggregate="sum"
    )
    decision = _decision(period["availability"], period["stats"])
    return [
        make_result(
            ctx,
            value=round(float(period["value"]), 4),
            unit=ctx.definition.unit,
            observed_start=period["start"],
            observed_end=period["end"],
            quality=QualitySummary(decision=decision, stats=period["stats"]),
            temporal_resolution="period",
            provenance=period["provenance"],
            parameters={"aggregation": "sum"},
        )
    ]


def compute_rainfall_anomaly(ctx: IndicatorContext) -> list[IndicatorResult]:
    return _anomaly(
        ctx, indicator_key="rainfall_anomaly", series_key="rainfall_summary", aggregate="sum"
    )


# ---------------------------------------------------------------- temperature
def compute_temperature_summary(ctx: IndicatorContext) -> list[IndicatorResult]:
    period = _period_values(
        ctx, capability="temperature", columns=TEMPERATURE_COLUMNS, aggregate="mean"
    )
    decision = _decision(period["availability"], period["stats"])
    provenance = dict(period["provenance"])
    provenance["notes"] = [
        "NASA POWER 2 m air temperature at the study-area representative point",
        "this is air temperature, not lake-surface water temperature",
    ]
    return [
        make_result(
            ctx,
            value=round(float(period["value"]), 4),
            unit=ctx.definition.unit,
            observed_start=period["start"],
            observed_end=period["end"],
            quality=QualitySummary(decision=decision, stats=period["stats"]),
            temporal_resolution="period",
            provenance=provenance,
            parameters={"aggregation": "mean"},
        )
    ]


def compute_temperature_anomaly(ctx: IndicatorContext) -> list[IndicatorResult]:
    return _anomaly(
        ctx, indicator_key="temperature_anomaly", series_key="temperature_summary", aggregate="mean"
    )

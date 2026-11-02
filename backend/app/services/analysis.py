"""Time-series assembly and period-to-period comparison over indicator results.

Aggregations are descriptive (mean/median/min/max/sum of the stored result
values).  Comparisons are explicitly *not* causal and proxies stay unitless.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.indicators import definition_for
from app.models import Dataset, IndicatorResult, StudyArea
from app.schemas.research import ComparisonCreate, TimeSeriesPoint

QUALITY_PRIORITY = (
    "MISSING_DATA",
    "PROCESSING_FAILED",
    "INSUFFICIENT_COVERAGE",
    "CLOUD_CONTAMINATED",
    "LOW_QUALITY",
    "UNVALIDATED",
    "VALID",
)
EXCLUDED_FLAGS = ("MISSING_DATA", "PROCESSING_FAILED")


def worst_flag(flags: Iterable[str]) -> str:
    present = set(flags)
    for flag in QUALITY_PRIORITY:
        if flag in present:
            return flag
    return "UNVALIDATED"


def _title_cache(db: Session, rows: list[IndicatorResult]) -> dict[int, str]:
    ids = {r.dataset_id for r in rows if r.dataset_id}
    if not ids:
        return {}
    return {
        d.id: d.title
        for d in db.execute(select(Dataset).where(Dataset.id.in_(ids))).scalars()
    }


def _point(row: IndicatorResult, titles: dict[int, str]) -> dict[str, Any]:
    return {
        "date": row.observed_start,
        "value": row.value,
        "unit": row.unit,
        "quality_flag": row.quality_flag,
        "quality_reason": row.quality_reason,
        "result_id": row.id,
        "dataset_id": row.dataset_id,
        "dataset_title": titles.get(row.dataset_id) if row.dataset_id else None,
        "coverage_fraction": row.coverage_fraction,
    }


def _result_rows(
    db: Session,
    *,
    indicator_key: str,
    study_area_id: int | None = None,
    dataset_ids: list[int] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[IndicatorResult]:
    stmt = select(IndicatorResult).where(IndicatorResult.indicator_key == indicator_key)
    if study_area_id is not None:
        stmt = stmt.where(IndicatorResult.study_area_id == study_area_id)
    if dataset_ids:
        stmt = stmt.where(IndicatorResult.dataset_id.in_(dataset_ids))
    if start is not None:
        stmt = stmt.where(IndicatorResult.observed_start >= start)
    if end is not None:
        stmt = stmt.where(IndicatorResult.observed_start <= end)
    return list(
        db.execute(
            stmt.order_by(IndicatorResult.observed_start.asc(), IndicatorResult.id.asc())
        ).scalars()
    )


def _aggregate(values: list[float], how: str) -> float | None:
    if not values:
        return None
    arr = np.asarray(values, dtype="float64")
    if how == "mean":
        return float(np.mean(arr))
    if how == "median":
        return float(np.median(arr))
    if how == "min":
        return float(np.min(arr))
    if how == "max":
        return float(np.max(arr))
    if how == "sum":
        return float(np.sum(arr))
    raise ValueError(f"unsupported aggregation '{how}'")


def build_timeseries(
    db: Session,
    *,
    indicator_key: str,
    study_area_id: int | None = None,
    dataset_ids: list[int] | None = None,
    start: date | None = None,
    end: date | None = None,
    aggregation: str = "raw",
) -> dict[str, Any]:
    definition = definition_for(db, indicator_key)
    rows = _result_rows(
        db,
        indicator_key=indicator_key,
        study_area_id=study_area_id,
        dataset_ids=dataset_ids,
        start=start,
        end=end,
    )
    titles = _title_cache(db, rows)
    usable = [r for r in rows if r.value is not None and r.quality_flag not in EXCLUDED_FLAGS]
    excluded = len(rows) - len(usable)

    if aggregation == "raw":
        points = [_point(r, titles) for r in usable]
    elif aggregation in ("monthly", "annual"):
        buckets: dict[str, list[IndicatorResult]] = defaultdict(list)
        for row in usable:
            key = (
                f"{row.observed_start.year}-{row.observed_start.month:02d}"
                if aggregation == "monthly"
                else f"{row.observed_start.year}"
            )
            buckets[key].append(row)
        points = []
        for bucket in sorted(buckets):
            members = buckets[bucket]
            vals = [float(r.value) for r in members if r.value is not None]
            points.append(
                {
                    "date": members[0].observed_start,
                    "value": round(float(np.mean(vals)), 6) if vals else None,
                    "unit": definition.unit,
                    "quality_flag": worst_flag(r.quality_flag for r in members),
                    "quality_reason": (
                        f"mean of {len(vals)} {aggregation} result(s)"
                        + (
                            "; some members were flagged lower quality"
                            if any(r.quality_flag != members[0].quality_flag for r in members)
                            else ""
                        )
                    ),
                    "result_id": None,
                    "dataset_id": None,
                    "dataset_title": None,
                    "coverage_fraction": (
                        round(float(np.mean([r.coverage_fraction for r in members if r.coverage_fraction is not None])), 6)
                        if any(r.coverage_fraction is not None for r in members)
                        else None
                    ),
                }
            )
    else:
        raise ValueError(f"aggregation must be raw|monthly|annual (got '{aggregation}')")

    limitations = []
    if definition.is_proxy:
        limitations.append(
            f"'{indicator_key}' is an unvalidated proxy index; the series is relative only"
        )
    if excluded:
        limitations.append(
            f"{excluded} result(s) with no value or a failed/missing-data flag were omitted"
        )
    limitations.append(
        "values are stored indicator results; see each point's quality flag and provenance"
    )
    return {
        "indicator_key": definition.key,
        "indicator_name": definition.name,
        "unit": definition.unit,
        "study_area_id": study_area_id,
        "aggregation": aggregation,
        "date_from": rows[0].observed_start if rows else None,
        "date_to": rows[-1].observed_start if rows else None,
        "points": points,
        "excluded_points": excluded,
        "limitations": " ".join(limitations),
    }


def _side(
    db: Session,
    *,
    definition,
    period_start: date,
    period_end: date,
    aggregation: str,
    study_area_id: int,
    dataset_ids: list[int] | None,
) -> dict[str, Any]:
    rows = _result_rows(
        db,
        indicator_key=definition.key,
        study_area_id=study_area_id,
        dataset_ids=dataset_ids,
        start=period_start,
        end=period_end,
    )
    # only results fully contained in the window are attributable to the period
    contained = [r for r in rows if r.observed_end <= period_end]
    titles = _title_cache(db, contained)
    usable = [r for r in contained if r.value is not None and r.quality_flag not in EXCLUDED_FLAGS]
    values = [float(r.value) for r in usable if r.value is not None]
    value = _aggregate(values, aggregation)
    flag = worst_flag(r.quality_flag for r in usable) if usable else "MISSING_DATA"
    reasons = [r.quality_reason for r in usable if r.quality_reason and r.quality_flag != "VALID"]
    return {
        "period": {"start": period_start, "end": period_end},
        "value": round(value, 6) if value is not None else None,
        "unit": definition.unit,
        "quality_flag": flag,
        "quality_reason": (
            reasons[0][:300]
            if reasons
            else ("" if usable else "no stored indicator results fully inside this period")
        ),
        "sample_count": len(values),
        "excluded_count": len(contained) - len(usable),
        "points": [_point(r, titles) for r in usable],
    }


def compare_periods(db: Session, payload: ComparisonCreate) -> dict[str, Any]:
    study_area = db.get(StudyArea, payload.study_area_id)
    if study_area is None:
        raise NotFoundError(f"Study area {payload.study_area_id} not found")

    entries = []
    for key in payload.indicator_keys:
        definition = definition_for(db, key)
        side_a = _side(
            db,
            definition=definition,
            period_start=payload.period_a.start,
            period_end=payload.period_a.end,
            aggregation=payload.aggregation,
            study_area_id=payload.study_area_id,
            dataset_ids=payload.dataset_ids,
        )
        side_b = _side(
            db,
            definition=definition,
            period_start=payload.period_b.start,
            period_end=payload.period_b.end,
            aggregation=payload.aggregation,
            study_area_id=payload.study_area_id,
            dataset_ids=payload.dataset_ids,
        )
        compatible = (
            side_a["value"] is not None
            and side_b["value"] is not None
            and side_a["unit"] == side_b["unit"]
        )
        delta = (
            round(float(side_b["value"]) - float(side_a["value"]), 6)
            if compatible
            else None
        )
        delta_percent = None
        if compatible and side_a["value"] not in (None, 0):
            delta_percent = round(
                (float(side_b["value"]) - float(side_a["value"]))
                / abs(float(side_a["value"]))
                * 100.0,
                4,
            )
        notes = []
        if definition.is_proxy:
            notes.append(
                "unitless proxy index: compare relative direction/magnitude, not concentrations"
            )
        if key in ("water_extent", "water_extent_change"):
            notes.append("water extent is planimetric area, not a water-level measurement")
        if side_a["sample_count"] != side_b["sample_count"]:
            notes.append(
                f"samples differ between periods ({side_a['sample_count']} vs {side_b['sample_count']})"
            )
        if not compatible:
            notes.append("period values are missing or units are incompatible")
        entries.append(
            {
                "indicator_key": definition.key,
                "indicator_name": definition.name,
                "unit": definition.unit,
                "aggregation": payload.aggregation,
                "a": side_a,
                "b": side_b,
                "delta": delta,
                "delta_percent": delta_percent,
                "compatible": compatible,
                "notes": " ".join(notes),
            }
        )

    return {
        "study_area_id": study_area.id,
        "study_area_name": study_area.name,
        "aggregation": payload.aggregation,
        "entries": entries,
        "limitations": (
            "Period comparison aggregates stored indicator results; it is descriptive and not "
            "causal. Results are only counted when they fall fully inside each period, and "
            "missing/failed results are excluded from aggregates."
        ),
    }


def point_models(points: list[dict[str, Any]]) -> list[TimeSeriesPoint]:
    return [TimeSeriesPoint(**p) for p in points]

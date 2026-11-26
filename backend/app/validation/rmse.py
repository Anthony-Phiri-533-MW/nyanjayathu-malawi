"""Gauge validation and RMSE (Signature-Challenge Property 1).

Satellite-derived water level/extent is only trustworthy if it is checked
against ground truth.  These pure functions match each satellite estimate to
the nearest gauge (great-circle distance) and report the error statistics the
assignment asks for, chiefly RMSE = sqrt(mean((estimate - gauge)^2)).

All inputs are plain sequences of mappings so the functions are trivial to
unit-test without a database or rasters.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

_EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two WGS-84 points."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = rlat2 - rlat1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def rmse(predicted: Sequence[float], observed: Sequence[float]) -> float:
    """Root-mean-square error between two equal-length sequences."""
    if len(predicted) != len(observed):
        raise ValueError("predicted and observed must have equal length")
    if not predicted:
        raise ValueError("cannot compute RMSE of empty sequences")
    total = sum((float(p) - float(o)) ** 2 for p, o in zip(predicted, observed))
    return math.sqrt(total / len(predicted))


def mae(predicted: Sequence[float], observed: Sequence[float]) -> float:
    """Mean absolute error between two equal-length sequences."""
    if len(predicted) != len(observed):
        raise ValueError("predicted and observed must have equal length")
    if not predicted:
        raise ValueError("cannot compute MAE of empty sequences")
    return sum(abs(float(p) - float(o)) for p, o in zip(predicted, observed)) / len(predicted)


def bias(predicted: Sequence[float], observed: Sequence[float]) -> float:
    """Mean signed error (positive => estimate higher than gauge)."""
    if len(predicted) != len(observed):
        raise ValueError("predicted and observed must have equal length")
    if not predicted:
        raise ValueError("cannot compute bias of empty sequences")
    return sum(float(p) - float(o) for p, o in zip(predicted, observed)) / len(predicted)


def _nearest_gauge(point: Mapping[str, Any], gauges: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    return min(
        gauges,
        key=lambda g: haversine_km(point["lat"], point["lon"], g["lat"], g["lon"]),
    )


def validate_against_gauges(
    estimates: Sequence[Mapping[str, Any]],
    gauges: Sequence[Mapping[str, Any]],
    *,
    max_distance_km: float = 50.0,
) -> dict[str, Any]:
    """Match each estimate to the nearest gauge and report error statistics.

    Each *estimate* needs ``lat``, ``lon`` and ``value`` (satellite-derived,
    in metres).  Each *gauge* needs ``lat``, ``lon`` and ``elevation_m``
    (observed, in metres).  Estimates whose nearest gauge is farther than
    *max_distance_km* are skipped and counted, never silently matched.
    """
    if not gauges:
        raise ValueError("no gauges supplied")
    pairs: list[tuple[float, float]] = []
    skipped = 0
    for est in estimates:
        gauge = _nearest_gauge(est, gauges)
        dist = haversine_km(est["lat"], est["lon"], gauge["lat"], gauge["lon"])
        if dist > max_distance_km:
            skipped += 1
            continue
        pairs.append((float(est["value"]), float(gauge["elevation_m"])))
    if not pairs:
        raise ValueError("no estimate matched a gauge within the distance limit")
    predicted = [p for p, _ in pairs]
    observed = [o for _, o in pairs]
    return {
        "count": len(pairs),
        "skipped": skipped,
        "rmse": round(rmse(predicted, observed), 4),
        "mae": round(mae(predicted, observed), 4),
        "bias": round(bias(predicted, observed), 4),
        "unit": "m",
    }
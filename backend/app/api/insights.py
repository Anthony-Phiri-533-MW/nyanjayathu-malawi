"""Live demonstration of the design-pattern and signature-challenge deliverables.

These endpoints make the Adapter/Strategy catalogue and the four
Signature-Challenge properties reachable through the running HTTP API (not just
unit tests):

* ``GET  /insights/patterns``      - adapter + strategy catalogue from the
  design-pattern registry.
* ``POST /insights/index``         - run a registered ``IndexStrategy`` on
  supplied reflectance bands (Strategy pattern, live).
* ``POST /insights/validate-gauges``- Property 1: RMSE/MAE/bias vs gauges.
* ``POST /insights/unit-check``    - Property 2: metre/centimetre mix-up guard.
* ``POST /insights/risk-matrix``   - Property 3: threshold classification +
  confusion matrix scored against historical events.
* ``POST /insights/cloud-gap``     - Property 4: cloud masking + gap
  interpolation with an honest ``gap_interpolated`` flag.
"""
from __future__ import annotations

from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.deps import require_permissions
from app.core.errors import UnprocessableError
from app.pattern_registry import (
    get_strategy,
    known_adapter_keys,
    known_strategy_keys,
)
from app.validation import cloudgap, confusion, rmse, units

router = APIRouter(prefix="/insights", tags=["insights"])

Read = Annotated[set[str], Depends(require_permissions("research.indicators.read"))]


def _unprocessable(exc: Exception) -> UnprocessableError:
    return UnprocessableError(str(exc))


class IndexRequest(BaseModel):
    strategy_key: str
    bands: dict[str, list[list[float]]] = Field(
        ..., description="band name -> 2D array of reflectance values"
    )


class GaugeEstimate(BaseModel):
    lat: float
    lon: float
    value: float


class Gauge(BaseModel):
    lat: float
    lon: float
    elevation_m: float


class ValidateGaugesRequest(BaseModel):
    estimates: list[GaugeEstimate]
    gauges: list[Gauge]
    max_distance_km: float = 50.0


class UnitCheckRequest(BaseModel):
    value: float
    unit: str
    expected_value: float
    expected_unit: str


class RiskMatrixRequest(BaseModel):
    indicators: list[dict[str, Any]]
    events: list[dict[str, Any]]
    threshold: dict[str, Any]
    positive_hazard: str = "flood"


class CloudGapRequest(BaseModel):
    values: list[list[float]]
    cloud_mask: list[list[bool]]
    sensor: str = "S2_MPC"
    processing_version: str = "1.0.0"
    date: str


@router.get("/patterns")
def patterns(_perms: Read) -> dict[str, Any]:
    """The live design-pattern catalogue used by the application."""
    return {
        "adapters": known_adapter_keys(),
        "strategies": known_strategy_keys(),
    }


@router.post("/index")
def compute_index(payload: IndexRequest, _perms: Read) -> dict[str, Any]:
    try:
        strategy = get_strategy(payload.strategy_key)
    except KeyError as exc:
        raise _unprocessable(exc) from exc
    dataset = {k: np.asarray(v, dtype=float) for k, v in payload.bands.items()}
    try:
        result = strategy.compute(dataset)
    except KeyError as exc:
        raise UnprocessableError(
            f"missing band for strategy '{payload.strategy_key}'", details={"band": str(exc)}
        ) from exc
    return {"strategy": payload.strategy_key, **result}


@router.post("/validate-gauges")
def validate_gauges(payload: ValidateGaugesRequest, _perms: Read) -> dict[str, Any]:
    try:
        return rmse.validate_against_gauges(
            [e.model_dump() for e in payload.estimates],
            [g.model_dump() for g in payload.gauges],
            max_distance_km=payload.max_distance_km,
        )
    except ValueError as exc:
        raise _unprocessable(exc) from exc


@router.post("/unit-check")
def unit_check(payload: UnitCheckRequest, _perms: Read) -> dict[str, Any]:
    try:
        equal = units.compare_lengths(
            payload.value, payload.unit, payload.expected_value, payload.expected_unit
        )
        metres = units.to_metres(payload.value, payload.unit)
    except ValueError as exc:
        raise _unprocessable(exc) from exc
    return {
        "equal": equal,
        "value_in_metres": metres,
        "expected_in_metres": units.to_metres(payload.expected_value, payload.expected_unit),
        "message": "units agree" if equal else "unit mismatch detected (values differ in metres)",
    }


@router.post("/risk-matrix")
def risk_matrix(payload: RiskMatrixRequest, _perms: Read) -> dict[str, Any]:
    try:
        return confusion.score_events(
            payload.indicators,
            payload.events,
            payload.threshold,
            positive_hazard=payload.positive_hazard,
        )
    except (ValueError, KeyError) as exc:
        raise _unprocessable(exc) from exc


@router.post("/cloud-gap")
def cloud_gap(payload: CloudGapRequest, _perms: Read) -> dict[str, Any]:
    values = np.asarray(payload.values, dtype=float)
    mask = np.asarray(payload.cloud_mask, dtype=bool)
    if values.shape != mask.shape:
        raise UnprocessableError("values and cloud_mask must have the same shape")
    return cloudgap.apply_cloud_gap(
        values,
        mask,
        sensor=payload.sensor,
        processing_version=payload.processing_version,
        date=payload.date,
    )

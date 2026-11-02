"""Cross-sensor band standardisation (harmonisation support).

Honest scope: this module standardises *which* bands are compared (a common
canonical band grid) and can apply **user-supplied** linear gain/offset
adjustments.  It deliberately does NOT ship default cross-sensor coefficients:
matching CRSs or band names is not scientific harmonisation, and no
coefficients are hard-coded without a citable, validated source.  Where no
validated adjustment is configured, the identity transform is applied and the
run records ``harmonisation_applied: false`` so downstream results can be
labelled accordingly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

# canonical band name -> per-sensor native band names
BAND_GRID: dict[str, dict[str, list[str]]] = {
    "blue": {"sentinel2": ["B02"], "landsat": ["SR_B2", "B2"], "modis": ["sur_refl_b03"]},
    "green": {"sentinel2": ["B03"], "landsat": ["SR_B3", "B3"], "modis": ["sur_refl_b04"]},
    "red": {"sentinel2": ["B04"], "landsat": ["SR_B4", "B4"], "modis": ["sur_refl_b01"]},
    "nir": {"sentinel2": ["B08"], "landsat": ["SR_B5", "B5"], "modis": ["sur_refl_b02"]},
    "swir1": {"sentinel2": ["B11"], "landsat": ["SR_B6", "B6"], "modis": ["sur_refl_b06"]},
    "swir2": {"sentinel2": ["B12"], "landsat": ["SR_B7", "B7"], "modis": ["sur_refl_b07"]},
    "red_edge_1": {"sentinel2": ["B05"], "landsat": [], "modis": []},
    "qa": {
        "sentinel2": ["SCL"],
        "landsat": ["QA_PIXEL"],
        "modis": ["state_1km_16days", "sur_refl_state_1km", "QC_1km", "QC_500m_8days"],
    },
    "thermal": {"sentinel2": [], "landsat": ["ST_B10"], "modis": ["LST_1km"]},
    "precipitation": {"chirps": ["precip", "precipitation"], "nasa_power": ["PRECTOTCORR"]},
    "air_temperature": {"nasa_power": ["T2M"]},
    "water_level": {"sentinel3_sral": ["wat_meas"]},
}


@dataclass
class LinearAdjustment:
    """y = gain * x + offset (per canonical band)."""

    gains: dict[str, float] = field(default_factory=dict)
    offsets: dict[str, float] = field(default_factory=dict)
    reference: str = ""

    @property
    def applied(self) -> bool:
        return bool(self.gains or self.offsets)

    def as_dict(self) -> dict[str, Any]:
        return {
            "gains": self.gains,
            "offsets": self.offsets,
            "reference": self.reference,
            "applied": self.applied,
        }


def canonical_for_sensor(sensor: str, native_band: str) -> str | None:
    for canonical, per_sensor in BAND_GRID.items():
        if native_band in per_sensor.get(sensor, []):
            return canonical
    return None


def native_bands(sensor: str, canonical: str) -> list[str]:
    return list(BAND_GRID.get(canonical, {}).get(sensor, []))


def apply_linear_adjustment(
    arrays: dict[str, np.ndarray], adjustment: LinearAdjustment
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    if not adjustment.applied:
        return arrays, adjustment.as_dict()
    out: dict[str, np.ndarray] = {}
    for key, arr in arrays.items():
        gain = adjustment.gains.get(key)
        offset = adjustment.offsets.get(key, 0.0)
        if gain is None:
            out[key] = arr
        else:
            out[key] = (arr * gain + offset).astype(arr.dtype if arr.dtype.kind == "f" else "float32")
    return out, adjustment.as_dict()


def adjustment_from_config(cfg: dict[str, Any] | None) -> LinearAdjustment:
    if not cfg:
        return LinearAdjustment()
    if cfg.get("reference") and not cfg.get("gains") and not cfg.get("offsets"):
        raise ValueError("linear adjustment requires gains/offsets in addition to the reference")
    if not cfg.get("reference"):
        raise ValueError("a citable reference is required for cross-sensor linear adjustments")
    return LinearAdjustment(
        gains={k: float(v) for k, v in (cfg.get("gains") or {}).items()},
        offsets={k: float(v) for k, v in (cfg.get("offsets") or {}).items()},
        reference=str(cfg["reference"]),
    )

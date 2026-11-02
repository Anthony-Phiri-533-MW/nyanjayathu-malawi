"""Water masking with documented spectral indices.

* MNDWI  (Xu, 2006, IJRS):  (Green - SWIR1) / (Green + SWIR1)
* NDWI   (McFeeters, 1996): (Green - NIR) / (Green + NIR)

Default threshold 0.0 (MNDWI) is a common, documented choice and is treated
as *provisional* - it is configurable per run and recorded in provenance.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DEFAULT_MNDWI_THRESHOLD = 0.0
DEFAULT_NDWI_THRESHOLD = 0.0


def _safe_nd(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        denom = a + b
        out = np.where(np.isfinite(denom) & (np.abs(denom) > 1e-9), (a - b) / denom, np.nan)
    return out.astype("float32")


def mndwi(green: np.ndarray, swir1: np.ndarray) -> np.ndarray:
    return _safe_nd(np.asarray(green, "float32"), np.asarray(swir1, "float32"))


def ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    return _safe_nd(np.asarray(green, "float32"), np.asarray(nir, "float32"))


def ndti(red: np.ndarray, green: np.ndarray) -> np.ndarray:
    """Normalised difference turbidity index (Lymburner et al., 2016)."""
    return _safe_nd(np.asarray(red, "float32"), np.asarray(green, "float32"))


@dataclass
class WaterMaskResult:
    water_mask: np.ndarray        # True = water
    index: np.ndarray             # the computed index (NaN where undefined)
    valid_mask: np.ndarray        # pixels where index is defined
    water_fraction: float         # water pixels / valid pixels inside footprint
    method: str
    threshold: float


def water_mask(
    green: np.ndarray,
    swir1: np.ndarray | None = None,
    nir: np.ndarray | None = None,
    *,
    method: str = "mndwi",
    threshold: float = DEFAULT_MNDWI_THRESHOLD,
    valid_mask: np.ndarray | None = None,
) -> WaterMaskResult:
    if method == "mndwi":
        if swir1 is None:
            raise ValueError("MNDWI requires a SWIR1 band")
        index = mndwi(green, swir1)
        thr = threshold
    elif method == "ndwi":
        if nir is None:
            raise ValueError("NDWI requires a NIR band")
        index = ndwi(green, nir)
        thr = threshold
    else:
        raise ValueError(f"unknown water-mask method '{method}'")

    defined = np.isfinite(index)
    if valid_mask is not None:
        defined &= valid_mask
    water = (index > thr) & defined
    denom = int(defined.sum())
    water_fraction = float(water.sum()) / denom if denom else 0.0
    return WaterMaskResult(
        water_mask=water,
        index=index,
        valid_mask=defined,
        water_fraction=water_fraction,
        method=method,
        threshold=float(thr),
    )

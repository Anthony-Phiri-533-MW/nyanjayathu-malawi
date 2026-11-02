"""Cloud / cloud-shadow masking for supported optical sensors.

Documented sources of truth:

* Sentinel-2 L2A scene classification (SCL) band - ESA product spec:
  classes 3 (cloud shadow), 8/9 (cloud medium/high), 10 (thin cirrus) and
  11 (snow) are masked; 0/1 (nodata/saturated) are treated as unusable.
* Landsat Collection 2 QA_PIXEL bits - USGS: bit 1 dilated cloud, bit 2
  cirrus, bit 3 cloud, bit 4 cloud shadow, bit 5 snow are masked.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

S2_CLEAR_CLASSES = {2, 4, 5, 6, 7}          # dark, veg, bare, water, unclassified
S2_MASKED_CLASSES = {0, 1, 3, 8, 9, 10, 11}  # nodata, saturated, shadow, cloud, cirrus, snow

LANDSAT_QA_MASKED_BITS = (1, 2, 3, 4, 5)     # dilated, cirrus, cloud, shadow, snow


def modis_state_clear_mask(state: np.ndarray) -> np.ndarray:
    """MODIS surface-reflectance state QA (e.g. sur_refl_state_1km).

    Bits 0-1 cloud state (00 clear), bits 2-3 cloud shadow (00 none)
    - masked when either is non-zero (MODIS Collection 6.1 user guide).
    """
    s = np.rint(np.asarray(state)).astype("uint16")
    cloud_state = s & 0b11
    shadow = (s >> 2) & 0b11
    return (cloud_state == 0) & (shadow == 0)


def modis_lst_qc_clear_mask(qc: np.ndarray) -> np.ndarray:
    """MODIS LST QC band (QC_1km, Collection 6.1).

    Bits 0-1 data quality (00 = good), bits 2-3 cloud state
    (00/01 = clear, 10/11 = cloudy/mixed -> masked).  Conservative: only
    good-quality, clear pixels are treated as usable.
    """
    q = np.rint(np.asarray(qc)).astype("uint16")
    good_quality = (q & 0b11) == 0
    cloud = (q >> 2) & 0b11
    clear = cloud <= 0b01
    return good_quality & clear



@dataclass
class CloudMaskResult:
    clear_mask: np.ndarray        # True = usable pixel
    cloud_fraction: float         # fraction of in-footprint pixels masked (0..1)
    method: str
    detail: dict


def s2_scl_clear_mask(scl: np.ndarray) -> np.ndarray:
    """True where the SCL value is a usable, cloud-free class."""
    scl_i = np.rint(np.asarray(scl)).astype("int16")
    clear = np.isin(scl_i, sorted(S2_CLEAR_CLASSES))
    return clear


def landsat_qa_clear_mask(qa: np.ndarray) -> np.ndarray:
    """True where the QA_PIXEL value has none of the cloud-related bits set."""
    qa_u = np.rint(np.asarray(qa)).astype("uint16")
    mask_bits = 0
    for bit in LANDSAT_QA_MASKED_BITS:
        mask_bits |= 1 << bit
    clear = (qa_u & mask_bits) == 0
    # also drop fill (bit 0)
    clear &= (qa_u & 1) == 0
    return clear


def assess_cloud_fraction(clear_mask: np.ndarray, footprint: np.ndarray | None = None) -> float:
    """Fraction of footprint pixels that are NOT clear."""
    if footprint is None:
        footprint = np.ones_like(clear_mask, dtype=bool)
    total = int(footprint.sum())
    if total == 0:
        return 1.0
    return float((footprint & ~clear_mask).sum()) / total


def apply_cloud_mask(data: np.ndarray, clear_mask: np.ndarray) -> np.ndarray:
    """Set non-clear pixels to NaN across a (bands, rows, cols) array."""
    out = data.copy()
    out[:, ~clear_mask] = np.nan
    return out


def clear_mask_for_sensor(sensor: str, qa_arrays: dict[str, np.ndarray]) -> tuple[np.ndarray | None, str]:
    """Dispatch to the sensor-appropriate mask given available QA bands."""
    if sensor == "sentinel2" and "scl" in qa_arrays:
        return s2_scl_clear_mask(qa_arrays["scl"]), "s2_scl"
    if sensor in ("landsat", "landsat89") and "qa_pixel" in qa_arrays:
        return landsat_qa_clear_mask(qa_arrays["qa_pixel"]), "landsat_qa_pixel"
    return None, "none"

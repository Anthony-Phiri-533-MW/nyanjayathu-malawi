"""Cloud masking, gap interpolation and flagging (Signature-Challenge Property 4).

Cloudy scenes must be masked; the resulting gaps are interpolated and *flagged*
so an interpolated value is never presented as an observation.  The functions
here are pure NumPy and fully unit-testable:

* :func:`interpolate_gaps` – inverse-distance-weighted fill of masked cells.
* :func:`apply_cloud_gap`   – returns the filled array, the interpolated mask
  and a provenance/flag record that marks the result as gap-filled.
"""
from __future__ import annotations

from typing import Any

import numpy as np


def interpolate_gaps(
    values: np.ndarray,
    valid_mask: np.ndarray,
    *,
    max_neighbours: int = 8,
) -> tuple[np.ndarray, np.ndarray]:
    """Fill invalid cells by inverse-distance weighting of valid neighbours.

    ``values`` is a 2-D array; ``valid_mask`` is True where a real observation
    exists.  Returns ``(filled, interpolated_mask)`` where ``interpolated_mask``
    is True exactly on the cells that were filled (so callers can flag them).
    Cells with no valid neighbour remain ``NaN`` and are *not* marked as
    interpolated – a gap with no support stays an honest gap.
    """
    data = np.asarray(values, dtype=float).copy()
    valid = np.asarray(valid_mask, dtype=bool)
    filled = data.copy()
    interpolated = np.zeros_like(valid)
    if valid.all() or not valid.any():
        return filled, interpolated
    valid_coords = np.argwhere(valid)
    invalid_coords = np.argwhere(~valid)
    vy = valid_coords[:, 0].astype(float)
    vx = valid_coords[:, 1].astype(float)
    vval = data[valid]
    for iy, ix in invalid_coords:
        d2 = (vy - iy) ** 2 + (vx - ix) ** 2
        order = np.argsort(d2)[:max_neighbours]
        weights = 1.0 / np.maximum(d2[order], 1e-6)
        filled[iy, ix] = float(np.sum(weights * vval[order]) / np.sum(weights))
        interpolated[iy, ix] = True
    return filled, interpolated


def apply_cloud_gap(
    values: np.ndarray,
    cloud_mask: np.ndarray,
    *,
    sensor: str,
    processing_version: str,
    date: str,
) -> dict[str, Any]:
    """Mask clouds, interpolate the gaps and return a flagged result.

    ``cloud_mask`` is True where a pixel is cloud-affected.  The returned dict
    always carries ``gap_interpolated`` (bool array as nested list) and a
    ``quality_flag`` of ``CLOUD_CONTAMINATED`` when any gap was filled, so the
    value is never silently shown as a clean observation.
    """
    valid = ~np.asarray(cloud_mask, dtype=bool)
    filled, interpolated = interpolate_gaps(values, valid)
    any_gap = bool(interpolated.any())
    return {
        "values": filled.tolist(),
        "gap_interpolated": interpolated.tolist(),
        "gap_interpolated_count": int(interpolated.sum()),
        "quality_flag": "CLOUD_CONTAMINATED" if any_gap else "VALID",
        "is_observation": not any_gap,
        "provenance": {
            "sensor": sensor,
            "processing_version": processing_version,
            "date": date,
            "unit": "m",
        },
    }

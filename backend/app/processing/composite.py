"""Temporal compositing (nodata-aware) built on xarray."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import xarray as xr

from app.processing.io import RasterRead

COMPOSITE_METHODS = ("median", "mean", "max", "min", "sum", "count", "percentile")


@dataclass
class CompositeResult:
    data: np.ndarray            # (bands, rows, cols) or (rows, cols) for single band
    valid_count: np.ndarray     # (rows, cols) number of contributing observations
    coverage: np.ndarray        # (rows, cols) valid_count / n_times
    method: str
    dates: list[str]
    grid: RasterRead            # reference grid (transform/crs/bounds)


def _stack(reads: list[RasterRead]) -> xr.DataArray:
    ref = reads[0]
    for r in reads[1:]:
        if r.shape != ref.shape or r.crs != ref.crs or not np.allclose(r.transform[:6], ref.transform[:6]):
            raise ValueError("all inputs must share one grid before compositing (run align_to_grid first)")
    stack = np.stack([r.data for r in reads], axis=0)          # (t, b, y, x)
    da = xr.DataArray(
        stack,
        dims=("time", "band", "y", "x"),
        coords={"y": np.arange(stack.shape[2]), "x": np.arange(stack.shape[3])},
    )
    return da


def temporal_composite(
    reads: list[RasterRead],
    *,
    method: str = "median",
    percentile: float = 75.0,
    dates: list[str] | None = None,
) -> CompositeResult:
    """Composite aligned windowed reads along time.

    NaN (nodata/cloud-masked) pixels are skipped with ``skipna=True``;
    ``valid_count`` records how many observations contributed per pixel so
    coverage can be reported alongside the result.
    """
    if not reads:
        raise ValueError("no inputs to composite")
    if method not in COMPOSITE_METHODS:
        raise ValueError(f"method must be one of {COMPOSITE_METHODS}")
    if len(reads) == 1 and method != "count":
        data = reads[0].data
        valid_count = np.isfinite(data).sum(axis=0)
        n = 1
        return CompositeResult(
            data=data,
            valid_count=valid_count.astype("int32"),
            coverage=(valid_count / n).astype("float32"),
            method=f"{method} (single input)",
            dates=dates or [],
            grid=reads[0],
        )

    da = _stack(reads)
    valid_count = da.notnull().sum(dim="time")
    if method == "median":
        comp = da.median(dim="time", skipna=True)
    elif method == "mean":
        comp = da.mean(dim="time", skipna=True)
    elif method == "max":
        comp = da.max(dim="time", skipna=True)
    elif method == "min":
        comp = da.min(dim="time", skipna=True)
    elif method == "sum":
        comp = da.sum(dim="time", skipna=True)
    elif method == "count":
        comp = valid_count
    else:
        comp = da.quantile(percentile / 100.0, dim="time", skipna=True)

    data = np.asarray(comp.values, dtype="float32")
    vc = np.asarray(valid_count.values)
    # all-NaN pixels -> NaN (not 0)
    data = np.where(vc == 0, np.nan, data)
    return CompositeResult(
        data=data,
        valid_count=vc.astype("int32"),
        coverage=(vc / len(reads)).astype("float32"),
        method=method,
        dates=dates or [],
        grid=reads[0],
    )

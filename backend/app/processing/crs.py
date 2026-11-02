"""CRS handling, resampling and grid alignment."""
from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.warp import Resampling as _R  # noqa: F401  (alias kept for API clarity)
from rasterio.warp import calculate_default_transform, reproject

from app.processing.io import RasterRead

RESAMPLING_METHODS: dict[str, Resampling] = {
    "nearest": Resampling.nearest,
    "bilinear": Resampling.bilinear,
    "cubic": Resampling.cubic,
    "average": Resampling.average,
    "mode": Resampling.mode,
    "max": Resampling.max,
    "min": Resampling.min,
    "med": Resampling.med,
}

# Default: continuous/reflective data -> bilinear; categorical/flags -> nearest
DEFAULT_RESAMPLING: dict[str, str] = {"reflectance": "bilinear", "categorical": "nearest", "continuous": "bilinear"}


def reproject_read(read: RasterRead, dst_crs: str | CRS, *, resampling: str = "bilinear") -> RasterRead:
    """Reproject a windowed read into another CRS (default transform)."""
    dst_crs = CRS.from_user_input(dst_crs)
    if read.crs == dst_crs:
        return read
    method = RESAMPLING_METHODS.get(resampling, Resampling.bilinear)
    transform, width, height = calculate_default_transform(
        read.crs, dst_crs, read.data.shape[2], read.data.shape[1], *read.bounds
    )
    dst = np.full((read.data.shape[0], height, width), np.nan, dtype="float32")
    reproject(
        source=read.data,
        destination=dst,
        src_transform=read.transform,
        src_crs=read.crs,
        src_nodata=np.nan,
        dst_transform=transform,
        dst_crs=dst_crs,
        dst_nodata=np.nan,
        resampling=method,
        num_threads=2,
    )
    valid = np.isfinite(dst).all(axis=0)
    return replace(
        read,
        data=dst,
        valid_mask=valid,
        transform=transform,
        crs=dst_crs,
        bounds=(transform.c, transform.f + height * transform.e, transform.c + width * transform.a, transform.f),
    )


def resample_to_resolution(
    read: RasterRead, target_res_m: float, *, resampling: str = "bilinear"
) -> RasterRead:
    """Resample to a target resolution (metres, projected CRS assumed)."""
    if read.crs is None or not read.crs.is_projected:
        raise ValueError("resample_to_resolution requires a projected CRS; reproject first")
    cur = abs(read.transform.a)
    if abs(cur - target_res_m) < 1e-6:
        return read
    method = RESAMPLING_METHODS.get(resampling, Resampling.bilinear)
    scale = cur / target_res_m
    width = max(1, int(round(read.data.shape[2] * scale)))
    height = max(1, int(round(read.data.shape[1] * scale)))
    a_sign = 1.0 if read.transform.a >= 0 else -1.0
    e_sign = -1.0 if read.transform.e < 0 else 1.0   # keep north-up/south-up orientation
    transform = rasterio.Affine(a_sign * target_res_m, 0.0, read.transform.c, 0.0, e_sign * target_res_m, read.transform.f)
    dst = np.full((read.data.shape[0], height, width), np.nan, dtype="float32")
    reproject(
        source=read.data,
        destination=dst,
        src_transform=read.transform,
        src_crs=read.crs,
        src_nodata=np.nan,
        dst_transform=transform,
        dst_crs=read.crs,
        dst_nodata=np.nan,
        resampling=method,
    )
    return replace(read, data=dst, valid_mask=np.isfinite(dst).all(axis=0), transform=transform)


def align_to_grid(read: RasterRead, reference: RasterRead, *, resampling: str = "bilinear") -> RasterRead:
    """Resample ``read`` onto the grid (CRS/transform/shape) of ``reference``.

    Used to co-register bands of different native resolutions (e.g. Sentinel-2
    10 m vs 20 m bands) onto one common analysis grid.
    """
    return warp_to_grid(
        read,
        dst_crs=reference.crs,
        dst_transform=reference.transform,
        width=reference.shape[1],
        height=reference.shape[0],
        resampling=resampling,
    )


def warp_to_grid(
    read: RasterRead,
    *,
    dst_crs: CRS,
    dst_transform,
    width: int,
    height: int,
    resampling: str = "bilinear",
) -> RasterRead:
    """Warp a read onto an explicit target grid."""
    if (
        read.crs == dst_crs
        and np.allclose(tuple(read.transform)[:6], tuple(dst_transform)[:6])
        and read.shape == (height, width)
    ):
        return read
    method = RESAMPLING_METHODS.get(resampling, Resampling.bilinear)
    dst = np.full((read.data.shape[0], height, width), np.nan, dtype="float32")
    reproject(
        source=read.data,
        destination=dst,
        src_transform=read.transform,
        src_crs=read.crs,
        src_nodata=np.nan,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        dst_nodata=np.nan,
        resampling=method,
    )
    t = dst_transform
    return replace(
        read,
        data=dst,
        valid_mask=np.isfinite(dst).all(axis=0),
        transform=t,
        crs=dst_crs,
        bounds=(t.c, t.f + height * t.e, t.c + width * t.a, t.f),
    )


def union_grid(reads: list[RasterRead]) -> tuple[CRS, rasterio.Affine, int, int]:
    """Common grid covering every input: coarsest resolution, union extent."""
    from rasterio.warp import transform_bounds

    if not reads:
        raise ValueError("no inputs")
    crs0 = reads[0].crs
    if any(r.crs != crs0 for r in reads):
        target_crs = CRS.from_epsg(4326)
        res = max(max(abs(r.transform.a), abs(r.transform.e)) for r in reads) / 111320.0
    else:
        target_crs = crs0
        res = max(max(abs(r.transform.a), abs(r.transform.e)) for r in reads)
    bounds_list = [transform_bounds(r.crs, target_crs, *r.bounds) for r in reads]
    minx = min(b[0] for b in bounds_list)
    miny = min(b[1] for b in bounds_list)
    maxx = max(b[2] for b in bounds_list)
    maxy = max(b[3] for b in bounds_list)
    width = max(1, int(math.ceil((maxx - minx) / res)))
    height = max(1, int(math.ceil((maxy - miny) / res)))
    transform = rasterio.Affine(res, 0.0, minx, 0.0, -res, maxy)
    return target_crs, transform, width, height


def choose_grid_resolution(reads: list[RasterRead]) -> float:
    """Common analysis grid = coarsest input resolution (no false precision)."""
    if not reads:
        raise ValueError("no reads supplied")
    return max(max(abs(r.transform.a), abs(r.transform.e)) for r in reads)

"""Memory-efficient raster I/O helpers built on rasterio.

All reads are windowed (``rasterio.windows``) against a WGS84 bounding box so
only the pixels covering the study area are materialised in memory; remote
``/vsicurl/`` paths are supported for Cloud-Optimized GeoTIFFs (HTTP range
requests).  ``iter_blocks`` supports block-wise processing of large local
files without loading them whole.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import Affine
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds, intersection
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

DEFAULT_OUT_DTYPE = "float32"


@dataclass
class RasterRead:
    """Result of a windowed read."""

    data: np.ndarray                 # (bands, rows, cols)
    band_names: list[str]
    crs: CRS
    transform: Affine
    nodata: float | None
    valid_mask: np.ndarray            # (rows, cols) True where data is usable
    bounds: tuple[float, float, float, float]
    path: str = ""
    tags: dict[str, Any] = field(default_factory=dict)

    @property
    def shape(self) -> tuple[int, int]:
        return (self.data.shape[1], self.data.shape[2])

    @property
    def res(self) -> tuple[float, float]:
        return (abs(self.transform.a), abs(self.transform.e))


def is_remote(path: str | Path) -> bool:
    return str(path).startswith(("/vsicurl/", "/vsicurl", "http://", "https://"))


def as_vsi(path: str | Path) -> str:
    """Normalise an http(s) URL to GDAL's /vsicurl/ form."""
    s = str(path)
    if s.startswith(("http://", "https://")):
        return "/vsicurl/" + s
    return s


def bbox_window(src: rasterio.io.DatasetReader, bbox_wgs84: tuple[float, float, float, float]) -> Window:
    """WGS84 bbox -> integer window in the raster's own CRS (boundless-safe)."""
    minx, miny, maxx, maxy = bbox_wgs84
    left, bottom, right, top = transform_bounds("EPSG:4326", src.crs, minx, miny, maxx, maxy, densify_pts=21)
    win = from_bounds(left, bottom, right, top, transform=src.transform)
    # intersect with the dataset extent; pad by 1 px to avoid edge clipping
    full = Window(0, 0, src.width, src.height)
    try:
        win = intersection(win, full)
    except Exception:
        return full
    if win.width <= 0 or win.height <= 0:
        return full
    win = win.round_offsets().round_lengths()
    win = Window(
        col_off=max(0, int(win.col_off)),
        row_off=max(0, int(win.row_off)),
        width=min(int(win.width) + 2, src.width),
        height=min(int(win.height) + 2, src.height),
    )
    return win


def read_window(
    path: str | Path,
    *,
    bbox_wgs84: tuple[float, float, float, float] | None = None,
    indexes: list[int] | None = None,
    band_names: list[str] | None = None,
    out_dtype: str | None = None,
    resampling: Resampling = Resampling.bilinear,
    max_dim: int | None = None,
) -> RasterRead:
    """Windowed (masked) read of a local or remote raster.

    ``max_dim`` downsamples the read so neither dimension exceeds it (GDAL
    uses overviews when present) - this bounds memory for large scenes.
    Missing/nodata pixels are represented as NaN; output is always float32.
    """
    vsi = as_vsi(path) if not Path(str(path)).exists() else str(path)
    with rasterio.open(vsi) as src:
        window = bbox_window(src, bbox_wgs84) if bbox_wgs84 else Window(0, 0, src.width, src.height)
        indexes = indexes or list(range(1, src.count + 1))
        out_shape = None
        if max_dim and (window.height > max_dim or window.width > max_dim):
            scale = max_dim / max(window.height, window.width)
            out_shape = (
                max(1, int(round(window.height * scale))),
                max(1, int(round(window.width * scale))),
            )
        data = src.read(
            indexes,
            window=window,
            masked=True,
            out_dtype=out_dtype or DEFAULT_OUT_DTYPE,
            boundless=True,
            fill_value=src.nodata if src.nodata is not None else 0,
            out_shape=out_shape,
            resampling=resampling,
        )
        if data.ndim == 2:
            data = data[np.newaxis, ...]
        arr = np.ma.filled(data.astype(out_dtype or DEFAULT_OUT_DTYPE), np.nan)
        if not np.issubdtype(np.dtype(out_dtype or DEFAULT_OUT_DTYPE), np.floating):
            arr = arr.astype("float32")
        valid = np.isfinite(arr).all(axis=0)
        names = band_names or [
            (src.descriptions[i - 1] or f"band_{i}") if i - 1 < len(src.descriptions) else f"band_{i}"
            for i in indexes
        ]
        if out_shape:
            out_transform = _scaled_transform(src, window, out_shape)
        else:
            out_transform = src.window_transform(window)
        width = out_shape[1] if out_shape else int(window.width)
        height = out_shape[0] if out_shape else int(window.height)
        b = rasterio.transform.array_bounds(height, width, out_transform)
        tags = dict(src.tags())
        return RasterRead(
            data=arr,
            band_names=[str(n or "band") for n in names],
            crs=src.crs,
            transform=out_transform,
            nodata=src.nodata,
            valid_mask=valid,
            bounds=(float(b[0]), float(b[1]), float(b[2]), float(b[3])),
            path=str(path),
            tags=tags,
        )


def _scaled_transform(src, window: Window, out_shape: tuple[int, int]) -> Affine:
    """Transform for a window read that was downsampled to out_shape."""
    t = src.window_transform(window)
    yscale = out_shape[0] / max(1, window.height)
    xscale = out_shape[1] / max(1, window.width)
    return Affine(t.a * xscale, t.b * xscale, t.c, t.d * yscale, t.e * yscale, t.f)


def bounds_intersection(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> tuple[float, float, float, float] | None:
    minx = max(a[0], b[0])
    miny = max(a[1], b[1])
    maxx = min(a[2], b[2])
    maxy = min(a[3], b[3])
    if minx >= maxx or miny >= maxy:
        return None
    return (minx, miny, maxx, maxy)


def _is_int(dtype: str | None) -> bool:
    return dtype is not None and np.issubdtype(np.dtype(dtype), np.integer)


def read_metadata(path: str | Path) -> dict[str, Any]:
    vsi = as_vsi(path) if not Path(str(path)).exists() else str(path)
    with rasterio.open(vsi) as src:
        b = src.bounds
        return {
            "crs": src.crs.to_string() if src.crs else None,
            "width": src.width,
            "height": src.height,
            "count": src.count,
            "dtype": src.dtypes[0],
            "nodata": src.nodata,
            "resolution_m": abs(src.transform.a),
            "bounds": [b.left, b.bottom, b.right, b.top],
            "bounds_wgs84": list(transform_bounds(src.crs, "EPSG:4326", *b.bounds)) if src.crs else None,
            "band_names": [src.descriptions[i] or f"band_{i + 1}" for i in range(src.count)],
        }


def write_geotiff(
    path: str | Path,
    data: np.ndarray,
    *,
    transform: Affine,
    crs: CRS | str,
    nodata: float | None = np.nan,
    band_names: list[str] | None = None,
    tags: dict[str, Any] | None = None,
    dtype: str = "float32",
    compress: str = "deflate",
) -> Path:
    """Write a (bands, rows, cols) array as a tiled, compressed GeoTIFF."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(data, dtype=dtype)
    if arr.ndim == 2:
        arr = arr[np.newaxis, ...]
    profile = {
        "driver": "GTiff",
        "height": arr.shape[1],
        "width": arr.shape[2],
        "count": arr.shape[0],
        "dtype": dtype,
        "crs": crs,
        "transform": transform,
        "nodata": nodata,
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
        "compress": compress,
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr)
        if band_names:
            for i, name in enumerate(band_names, start=1):
                if i <= arr.shape[0]:
                    dst.set_band_description(i, str(name)[:255])
        if tags:
            dst.update_tags(**{k: str(v)[:1000] for k, v in tags.items()})
    return path


def iter_blocks(
    path: str | Path,
    *,
    bbox_wgs84: tuple[float, float, float, float] | None = None,
    block_size: int = 1024,
    indexes: list[int] | None = None,
) -> Iterator[tuple[Window, np.ndarray]]:
    """Yield (window, data) blocks for streaming statistics over large rasters."""
    vsi = as_vsi(path) if not Path(str(path)).exists() else str(path)
    with rasterio.open(vsi) as src:
        window = bbox_window(src, bbox_wgs84) if bbox_wgs84 else Window(0, 0, src.width, src.height)
        indexes = indexes or list(range(1, src.count + 1))
        for row_off in range(int(window.row_off), int(window.row_off + window.height), block_size):
            for col_off in range(int(window.col_off), int(window.col_off + window.width), block_size):
                h = min(block_size, int(window.row_off + window.height) - row_off)
                w = min(block_size, int(window.col_off + window.width) - col_off)
                bw = Window(col_off, row_off, w, h)
                data = src.read(indexes, window=bw, masked=True, boundless=True, fill_value=0)
                yield bw, data


def geometry_inside_mask(read: RasterRead, geometry: BaseGeometry, *, all_touched: bool = False) -> np.ndarray:
    """Boolean mask (rows, cols) of pixels whose centre falls inside ``geometry``."""
    geom = _project_geometry(geometry, read.crs)
    return ~geometry_mask(
        [mapping(geom)],
        out_shape=(read.data.shape[1], read.data.shape[2]),
        transform=read.transform,
        all_touched=all_touched,
        invert=False,
    )


def clip_to_geometry(
    read: RasterRead,
    geometry: BaseGeometry,
    *,
    all_touched: bool = False,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Mask ``data`` outside ``geometry`` (in the raster CRS).

    Returns (masked_data, inside_mask, inside_fraction).
    """
    inside = geometry_inside_mask(read, geometry, all_touched=all_touched)
    data = read.data.copy()
    data[:, ~inside] = np.nan
    valid = read.valid_mask & inside
    frac = float(inside.sum()) / max(1, inside.size)
    return data, valid, frac


def _project_geometry(geometry: BaseGeometry, dst_crs: CRS) -> BaseGeometry:
    import geopandas as gpd

    gdf = gpd.GeoSeries([geometry], crs="EPSG:4326")
    return gdf.to_crs(dst_crs).iloc[0]


def pixel_area_m2(transform: Affine, crs: CRS, shape_hw: tuple[int, int]) -> np.ndarray:
    """Per-row pixel area in m².

    Projected CRS with metre units: constant.  Geographic CRS: computed with a
    geodesic approximation per row (area varies with latitude).
    """
    rows, cols = shape_hw
    if crs is None:
        raise ValueError("raster CRS is required to compute pixel areas")
    if crs.is_projected and crs.linear_units and crs.linear_units.lower() in ("metre", "meter", "m"):
        return np.full((rows,), abs(transform.a * transform.e), dtype="float64")
    from pyproj import Geod

    geod = Geod(ellps="WGS84")
    areas = np.empty((rows,), dtype="float64")
    lon = transform.c
    dx = transform.a
    dy = abs(transform.e)
    for r in range(rows):
        lat = transform.f + (r + 0.5) * dy  # transform.e negative for north-up
        if transform.e > 0:  # south-up
            lat = transform.f + (r + 0.5) * transform.e
        _, _, width_m = geod.inv(lon, lat, lon + dx, lat)
        _, _, height_m = geod.inv(lon, lat, lon, lat + dy)
        areas[r] = abs(width_m * height_m)
    return areas


def human_bytes(n: int | float | None) -> str:
    if not n:
        return "0 B"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def safe_log10(data: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.log10(np.where(data > 0, data, np.nan))

"""Shared asset-retrieval helpers used by provider adapters.

Two retrieval strategies are supported:

* **Windowed raster fetch** - open the source (local file or remote COG via
  GDAL ``/vsicurl/``), read only the pixels covering the study-area bounding
  box (bounded by ``max_dim``), apply the provider's *documented* scale/offset
  so stored values are physical units, and write a local GeoTIFF.
* **Plain download** - for non-raster assets (netCDF, JSON, CSV) and
  compressed bundles (``.tif.gz``), with SHA-256 checksums for provenance.

Documented scaling constants live with each adapter (ESA/USGS/MODIS product
specifications); they are recorded on the stored product so the conversion is
always auditable.
"""
from __future__ import annotations

import gzip
import hashlib
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import numpy as np
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds

from app.processing.io import read_window, write_geotiff
from app.providers.base import ProviderError

_RESAMPLING = {
    "nearest": Resampling.nearest,
    "bilinear": Resampling.bilinear,
    "cubic": Resampling.cubic,
    "average": Resampling.average,
}


@dataclass(frozen=True)
class AssetRule:
    """How one provider asset is converted into a stored band.

    ``scale``/``offset`` follow the provider's documented linear scaling
    (stored = DN * scale + offset).  Classification / QA bands use
    ``resampling="nearest"`` so class values survive downsampling.
    """

    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""
    label: str = ""
    description: str = ""
    resampling: str = "bilinear"
    qa: bool = False
    canonical: str = ""          # expected canonical band name (informational)


def _safe_url_for_error(url: str) -> str:
    parts = urlsplit(url)
    safe_query = "[redacted]" if parts.query else ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, safe_query, ""))


def download_file(
    client: httpx.Client,
    url: str,
    dest: Path,
    *,
    attempts: int = 3,
    progress_cb=None,
) -> tuple[int, str]:
    """Download ``url`` to ``dest`` with retries.

    Returns ``(size_bytes, sha256)``.  Raises ProviderError on HTTP errors or
    exhausted retries.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise ProviderError(
                        f"HTTP {resp.status_code} while downloading {_safe_url_for_error(url)[:220]}"
                    )
                h = hashlib.sha256()
                size = 0
                with dest.open("wb") as fh:
                    for chunk in resp.iter_bytes(256 * 1024):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        h.update(chunk)
                        size += len(chunk)
                        if progress_cb:
                            progress_cb(size)
                return size, h.hexdigest()
        except ProviderError:
            raise
        except (httpx.HTTPError, OSError) as exc:  # network hiccups are retried
            last_error = exc
            if attempt < attempts:
                time.sleep(0.8 * attempt)
    raise ProviderError(f"download failed after {attempts} attempts: {last_error}")


def head_status(client: httpx.Client, url: str, *, attempts: int = 2) -> int | None:
    """HEAD a URL; returns the status code, or None when the network failed."""
    for attempt in range(1, attempts + 1):
        try:
            resp = client.head(url)
            return resp.status_code
        except httpx.HTTPError:
            if attempt < attempts:
                time.sleep(0.6 * attempt)
    return None


def gunzip(src_gz: Path, dest: Path) -> int:
    """Decompress ``src_gz`` to ``dest``; returns decompressed size."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(src_gz, "rb") as fin, dest.open("wb") as fout:
        shutil.copyfileobj(fin, fout)
    return dest.stat().st_size


def ground_resolution_m(transform, crs, lat_ref: float | None = None) -> tuple[float | None, str]:
    """Pixel size in metres (or the source CRS unit).

    Projected CRS with metre units: exact pixel size.  Geographic CRS: ground
    sample distance at ``lat_ref`` (approximation, labelled as such).
    """
    if crs is None:
        return None, "unknown (source has no CRS)"
    dx = abs(transform.a)
    try:
        if crs.is_projected and (crs.linear_units or "").lower() in ("metre", "meter", "m"):
            return dx, "projected-CRS pixel size"
    except Exception:
        pass
    from pyproj import Geod

    geod = Geod(ellps="WGS84")
    lat = float(lat_ref or 0.0)
    _, _, dx_m = geod.inv(transform.c, lat, transform.c + dx, lat)
    return float(dx_m), f"ground pixel size at latitude {lat:.2f} deg (approximation)"


def fetch_raster_band(
    source: str,
    dest: Path,
    *,
    native_name: str,
    bbox: tuple[float, float, float, float],
    rule: AssetRule,
    max_dim: int | None = 2048,
    lat_ref: float | None = None,
    extra_tags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Windowed, scaled read of one single-band raster -> local GeoTIFF.

    Returns a metadata dict for provenance/band records.
    """
    resampling = _RESAMPLING.get(rule.resampling, Resampling.bilinear)
    read = read_window(
        source,
        bbox_wgs84=bbox,
        indexes=[1],
        band_names=[native_name],
        max_dim=max_dim,
        resampling=resampling,
    )
    if read.crs is None:
        raise ProviderError(f"source raster '{native_name}' has no CRS; cannot store reliably")
    data = read.data
    if rule.scale != 1.0 or rule.offset != 0.0:
        data = (data.astype("float32") * rule.scale + rule.offset).astype("float32")
    tags = {
        "source_native_band": native_name,
        "scale_applied": str(rule.scale),
        "offset_applied": str(rule.offset),
        "source_unit": rule.unit or "",
    }
    if extra_tags:
        tags.update({k: str(v) for k, v in extra_tags.items()})
    write_geotiff(
        dest,
        data,
        transform=read.transform,
        crs=read.crs,
        nodata=np.nan,
        band_names=[native_name],
        tags=tags,
    )
    res_m, res_note = ground_resolution_m(read.transform, read.crs, lat_ref=lat_ref)
    bbox_wgs84 = list(transform_bounds(read.crs, "EPSG:4326", *read.bounds))
    height, width = int(read.data.shape[1]), int(read.data.shape[2])
    return {
        "crs": read.crs.to_string(),
        "resolution_m": res_m,
        "resolution_note": res_note,
        "bounds_wgs84": [float(v) for v in bbox_wgs84],
        "shape": [width, height],
        "native_resolution_source": abs(read.transform.a),
        "source_scale": rule.scale,
        "source_offset": rule.offset,
    }

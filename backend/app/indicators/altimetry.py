"""Satellite-altimetry water level.

Values come from the ingested altimetry product unchanged: nothing is
synthesised, interpolated or rescaled.  The reader locates the water-level
variable inside an HDF5/netCDF4 product (root group or any nested group),
applies the product's own ``_FillValue``/``missing_value`` masking, keeps
measurements inside the study area when track coordinates are available, and
reports the median with its spread.  The reference datum is copied from the
source product so a reader can see exactly what the level is relative to.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from app.core.errors import UnprocessableError
from app.indicators.base import (
    INDICATOR_ALGORITHM_VERSION,
    IndicatorContext,
    QualitySummary,
    failed_result,
    make_result,
    parse_date,
)
from app.models import IndicatorResult
from app.processing import quality as qmod
from app.services.storage import absolute

LEVEL_HINTS = ("water_surface_height", "water_level", "water_height", "wat_meas", "ssh", "height", "elevation", "altitude")
EXCLUDE_HINTS = (
    "quality", "flag", "error", "correction", "std", "count", "number", "time", "lat", "lon",
    "backscatter", "sig0", "wind", "wave", "range", "orbit", "cycle", "pass", "doppler", "dummy",
    "depth", "bathymetry", "geoid", "tide", "solid_earth", "pole", "instrument",
)
METRE_UNITS = ("m", "meter", "meters", "metre", "metres")


@dataclass
class ArrayInfo:
    name: str
    values: np.ndarray
    attrs: dict[str, Any]


def _decode(value: Any) -> Any:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", "ignore")
        except Exception:
            return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray) and value.size == 1:
        return _decode(value.reshape(-1)[0])
    return value


def _attrs_dict(attrs) -> dict[str, Any]:
    return {str(k): _decode(v) for k, v in dict(attrs).items()}


def _read_arrays(path: Path) -> tuple[list[ArrayInfo], dict[str, Any]]:
    """Read every numeric array (and its attributes) from a netCDF/HDF5 file."""
    arrays: list[ArrayInfo] = []
    global_attrs: dict[str, Any] = {}
    try:
        import h5py

        with h5py.File(path, "r") as fh:
            global_attrs = _attrs_dict(fh.attrs)

            def visit(name: str, obj) -> None:  # noqa: ANN001 - h5py callback
                if isinstance(obj, h5py.Dataset) and obj.size and obj.size <= 50_000_000:
                    try:
                        data = np.asarray(obj[()])
                    except Exception:
                        return
                    if data.dtype.kind in ("f", "i", "u"):
                        arrays.append(ArrayInfo(name=name, values=data, attrs=_attrs_dict(obj.attrs)))

            fh.visititems(visit)
    except Exception:
        arrays = []

    if not arrays:
        import xarray as xr

        with xr.open_dataset(path) as ds:  # type: ignore[union-attr]
            global_attrs = _attrs_dict(getattr(ds, "attrs", {}) or {})
            for name, var in ds.variables.items():
                data = np.asarray(var.values)
                if data.dtype.kind in ("f", "i", "u") and data.size:
                    arrays.append(
                        ArrayInfo(name=str(name), values=data, attrs=_attrs_dict(var.attrs))
                    )
    return arrays, global_attrs


def _leaf(name: str) -> str:
    return name.rsplit("/", 1)[-1].lower()


def _score_level(info: ArrayInfo) -> int:
    leaf = _leaf(info.name)
    if any(hint in leaf for hint in EXCLUDE_HINTS) and leaf not in ("wat_meas", "ssh", "height"):
        return -1
    units = str(info.attrs.get("units") or "").strip().lower()
    if units and units not in METRE_UNITS + ("cm", "mm", "km"):
        return -1
    score = 0
    if "water" in leaf:
        score += 4
    if leaf in ("wat_meas", "ssh"):
        score += 6
    for hint in LEVEL_HINTS:
        if hint in leaf:
            score += 2
            break
    standard = str(info.attrs.get("standard_name") or "").lower()
    if "sea_surface_height" in standard or "water_surface_height" in standard:
        score += 4
    if units in METRE_UNITS:
        score += 1
    if np.issubdtype(info.values.dtype, np.floating):
        score += 1
    return score


def _coordinate_arrays(
    arrays: list[ArrayInfo], level_shape: tuple[int, ...]
) -> tuple[np.ndarray | None, np.ndarray | None]:
    lat_candidates = [a for a in arrays if _leaf(a.name) in ("lat", "latitude", "nav_lat")]
    lon_candidates = [a for a in arrays if _leaf(a.name) in ("lon", "longitude", "nav_lon")]
    if not lat_candidates or not lon_candidates:
        return None, None
    n = int(np.prod(level_shape))

    def locate(cands: list[ArrayInfo]) -> np.ndarray | None:
        for arr in cands:
            if arr.values.shape == level_shape:
                return np.asarray(arr.values, dtype="float64").reshape(-1)
        for arr in cands:
            flat = np.asarray(arr.values, dtype="float64").reshape(-1)
            if flat.size == n:
                return flat
        for arr in cands:
            if arr.values.ndim == 1 and level_shape and arr.values.shape[0] == level_shape[-1]:
                reps = n // arr.values.shape[0]
                return np.tile(np.asarray(arr.values, dtype="float64"), reps)
        return None

    return locate(lat_candidates), locate(lon_candidates)


def _apply_fill(values: np.ndarray, attrs: dict[str, Any]) -> np.ndarray:
    data = np.asarray(values, dtype="float64").astype("float64", copy=True)
    for key in ("_FillValue", "missing_value", "fill_value"):
        if key in attrs:
            try:
                fill = float(np.asarray(attrs[key]).reshape(-1)[0])
            except Exception:
                continue
            data[data == fill] = np.nan
    # common sentinel values used by altimetry products
    for sentinel in (2147483647.0, -2147483648.0, 999999.0, -9999.0, 9999.0):
        data[data == sentinel] = np.nan
    data[~np.isfinite(data)] = np.nan
    data[np.abs(data) > 10_000] = np.nan
    return data


def _inside_boundary(lats: np.ndarray, lons: np.ndarray, ctx: IndicatorContext) -> np.ndarray:
    boundary = ctx.boundary
    if boundary is None or lats.size == 0:
        return np.ones(lats.shape, dtype=bool)
    try:
        from shapely import contains_xy

        return np.asarray(contains_xy(boundary, lons, lats), dtype=bool)
    except Exception:
        from shapely.geometry import Point

        return np.array([boundary.contains(Point(x, y)) for x, y in zip(lons, lats, strict=False)], dtype=bool)


def _read_granule_levels(
    path: Path, ctx: IndicatorContext
) -> dict[str, Any] | None:
    arrays, global_attrs = _read_arrays(path)
    scored = sorted(
        ((_score_level(a), a) for a in arrays),
        key=lambda item: item[0],
        reverse=True,
    )
    scored = [(s, a) for s, a in scored if s > 0]
    if not scored:
        return {
            "error": "no water-level variable found",
            "variables": [a.name for a in arrays][:40],
        }

    _, level = scored[0]
    values = _apply_fill(level.values, level.attrs)
    finite = np.isfinite(values)
    lats, lons = _coordinate_arrays(arrays, level.values.shape)
    inside = np.ones(values.shape, dtype=bool)
    if lats is not None and lons is not None and lats.size == values.size:
        lats = lats.reshape(values.shape)
        lons = lons.reshape(values.shape)
        inside = _inside_boundary(lats, lons, ctx)
        finite &= inside
    usable = values[finite]
    if usable.size == 0:
        return {
            "error": "the water-level variable has no usable values inside the study area",
            "variable": level.name,
            "n_total": int(values.size),
            "n_finite": int(np.isfinite(values).sum()),
        }

    datum = (
        level.attrs.get("datum")
        or level.attrs.get("reference_datum")
        or level.attrs.get("geoid")
        or global_attrs.get("datum")
        or global_attrs.get("reference_datum")
        or "not stated in the product"
    )
    units = str(level.attrs.get("units") or "").strip()
    if units and units.lower() not in METRE_UNITS:
        return {
            "error": f"unsupported water-level units '{units}' (expected metres)",
            "variable": level.name,
        }
    lon_out = lat_out = None
    if lats is not None and lons is not None and lats.size == values.size:
        lon_out = float(np.median(lons.reshape(values.shape)[finite]))
        lat_out = float(np.median(lats.reshape(values.shape)[finite]))
    return {
        "variable": level.name,
        "values": usable,
        "n_total": int(values.size),
        "n_finite": int(np.isfinite(values).sum()),
        "n_inside": int(inside.sum()),
        "datum": str(datum),
        "units": units or "m",
        "lon": lon_out,
        "lat": lat_out,
        "spatial_filter": lats is not None and lons is not None,
    }


def compute_water_level_altimetry(ctx: IndicatorContext) -> list[IndicatorResult]:
    results: list[IndicatorResult] = []
    datasets = list(ctx.selection.datasets)
    if not datasets:
        raise UnprocessableError(
            "No datasets selected for water_level_altimetry; ingest a satellite-altimetry "
            "data source first"
        )

    n = len(datasets)
    any_granule = False
    for idx, dataset in enumerate(datasets):
        ctx.progress((idx + 0.5) / n, f"altimetry {dataset.id}")
        granules = (dataset.metadata_json or {}).get("granules") or []
        for granule in granules:
            any_granule = True
            granule_bands = granule.get("bands") or {}
            path_rel = (
                granule_bands.get("wat_meas")
                or granule_bands.get("water_level")
                or next(iter(granule_bands.values()), None)
                or granule.get("path")
            )
            observed = parse_date(granule.get("date")) or dataset.start_date
            start = observed or ctx.selection.start or date.today()
            end = observed or dataset.end_date or start
            if not path_rel:
                results.append(
                    failed_result(
                        ctx,
                        reason="altimetry granule has no stored file path",
                        observed_start=start,
                        observed_end=end,
                        dataset=dataset,
                    )
                )
                continue
            path = absolute(path_rel)
            if not path.exists():
                results.append(
                    failed_result(
                        ctx,
                        reason=f"altimetry file is missing from storage: {path_rel}",
                        observed_start=start,
                        observed_end=end,
                        dataset=dataset,
                    )
                )
                continue
            try:
                info = _read_granule_levels(path, ctx)
            except Exception as exc:  # unreadable product
                info = {"error": f"{type(exc).__name__}: {exc}"}
            if info is None or "values" not in info:
                reason = (info or {}).get("error", "unreadable altimetry product")
                extra = ""
                if info and info.get("variables"):
                    extra = f" (variables seen: {', '.join(info['variables'])})"
                results.append(
                    failed_result(
                        ctx,
                        reason=f"{reason}{extra}",
                        observed_start=start,
                        observed_end=end,
                        dataset=dataset,
                    )
                )
                continue

            values = np.asarray(info["values"], dtype="float64")
            value = float(np.median(values))
            n_total = int(info["n_total"])
            n_finite = int(info["n_finite"])
            coverage = n_finite / n_total if n_total else 0.0
            stats = qmod.MissingDataStats(
                total_pixels=n_total,
                valid_pixels=int(values.size),
                missing_pixels=max(0, n_total - int(values.size)),
                valid_fraction=coverage,
                missing_fraction=max(0.0, 1.0 - coverage),
            )
            extra_flags: list[tuple[str, str]] = []
            if values.size < 3:
                extra_flags.append(
                    ("LOW_QUALITY", f"only {values.size} valid altimetry measurement(s) in this product")
                )
            decision = qmod.evaluate_quality(
                coverage_fraction=coverage, missing=stats, extra_flags=extra_flags
            )
            provenance = {
                "algorithm_version": INDICATOR_ALGORITHM_VERSION,
                "aggregation": "median of valid water-level measurements",
                "source_variable": info["variable"],
                "source_datum": info["datum"],
                "source_units": info["units"],
                "n_total_values": n_total,
                "n_finite_values": n_finite,
                "n_used_values": int(values.size),
                "study_area_filter_applied": bool(info["spatial_filter"]),
                "dataset_id": dataset.id,
                "granule_id": granule.get("id"),
                "provider_key": dataset.provider_key,
                "notes": [
                    "values are copied from the product; no interpolation or rescaling",
                    "datum is whatever the source product states; check consistency before differencing",
                ],
            }
            results.append(
                make_result(
                    ctx,
                    value=round(value, 4),
                    unit=ctx.definition.unit,
                    observed_start=start,
                    observed_end=end,
                    quality=QualitySummary(decision=decision, stats=stats),
                    temporal_resolution="instant (overpass)",
                    spatial_resolution=str(dataset.resolution_m or ""),
                    dataset=dataset,
                    provenance=provenance,
                    parameters={"aggregation": "median"},
                    uncertainty={
                        "n_values": int(values.size),
                        "p25": round(float(np.percentile(values, 25)), 4),
                        "p75": round(float(np.percentile(values, 75)), 4),
                        "std": round(float(np.std(values)), 4),
                    },
                    extent=(
                        {"type": "Point", "coordinates": [info["lon"], info["lat"]]}
                        if info.get("lon") is not None and info.get("lat") is not None
                        else dataset.coverage_geojson
                    ),
                )
            )

    if not any_granule:
        raise UnprocessableError(
            "the selected datasets contain no altimetry granules; ingest a satellite-altimetry "
            "data source (e.g. Sentinel-3 SRAL) first"
        )
    ctx.progress(1.0, "water level computed")
    return results

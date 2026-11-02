"""Preprocessing pipeline: executes a sequence of registered operations on
one dataset (single observation) or several datasets (temporal composite),
recording a ProcessingRun per operation and persisting output DataProducts.

Memory discipline: inputs are windowed to the study-area bounding box and
bounded by the source's ``ingestion_config.max_dim``; temporal composites
stack one band at a time; nothing loads whole continental rasters.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, UnprocessableError
from app.models import DataProduct, Dataset, ProcessingRun, QualityAssessment, StudyArea, User, utcnow
from app.processing import cloud_mask as cm
from app.processing import crs as crs_ops
from app.processing import harmonize as hz
from app.processing import quality as qmod
from app.processing import water_mask as wm
from app.processing.composite import temporal_composite
from app.processing.io import RasterRead, clip_to_geometry, read_window, write_geotiff
from app.processing.registry import PROCESSING_OPERATIONS
from app.services.spatial import parse_geojson_geometry
from app.services.storage import file_checksum, relative

log = logging.getLogger("lakewatch.pipeline")

ALGORITHM_VERSION = "1.0.0"

PROVIDER_SENSOR = {
    "sentinel2_mpc": "sentinel2",
    "landsat_mpc": "landsat",
    "modis_mpc": "modis",
    "modis_lst_mpc": "modis",
    "chirps": "chirps",
    "nasa_power": "nasa_power",
    "sentinel3_sral": "sentinel3_sral",
}

# canonical order for stacked product bands
BAND_ORDER = [
    "blue", "green", "red", "nir", "swir1", "swir2", "red_edge_1",
    "thermal", "precipitation", "air_temperature", "water_level",
    "qa", "mndwi", "ndwi", "water_mask",
]


def band_sort_key(name: str) -> tuple[int, str]:
    try:
        return (BAND_ORDER.index(name), name)
    except ValueError:
        return (len(BAND_ORDER), name)


def granules_of(dataset: Dataset) -> list[dict]:
    meta = dataset.metadata_json or {}
    return list(meta.get("granules") or [])


def sensor_for(dataset: Dataset) -> str:
    return PROVIDER_SENSOR.get(dataset.provider_key, dataset.provider_key)


def _aoi_bbox(dataset: Dataset, study_area: StudyArea | None) -> tuple[float, float, float, float] | None:
    if study_area is not None:
        return (study_area.minx, study_area.miny, study_area.maxx, study_area.maxy)
    if dataset.coverage_geojson:
        try:
            geom = parse_geojson_geometry(dataset.coverage_geojson)
            return (geom.bounds[0], geom.bounds[1], geom.bounds[2], geom.bounds[3])
        except Exception:
            return None
    return None


def load_granule(
    dataset: Dataset,
    granule: dict,
    *,
    bbox: tuple[float, float, float, float] | None,
    max_dim: int | None,
) -> dict[str, RasterRead]:
    """Load one granule's bands windowed to ``bbox``, co-registered onto the
    coarsest band grid (no false precision from mixing native resolutions).

    Multi-band products (e.g. temporal composites written as one GeoTIFF) use
    ``granule["band_indexes"]`` mapping a canonical band name to its 1-based
    band index in that file.
    """
    out: dict[str, RasterRead] = {}
    sensor = sensor_for(dataset)
    band_indexes = granule.get("band_indexes")
    if granule.get("path") and isinstance(band_indexes, dict) and band_indexes:
        for canonical, index in band_indexes.items():
            resampling = Resampling.nearest if canonical == "qa" else Resampling.bilinear
            read = read_window(
                granule["path"],
                bbox_wgs84=bbox,
                indexes=[int(index)],
                band_names=[str(canonical)],
                max_dim=max_dim,
                resampling=resampling,
            )
            out[str(canonical)] = read
        ref = max(out.values(), key=lambda r: max(abs(r.transform.a), abs(r.transform.e)))
        for key, read in list(out.items()):
            out[key] = crs_ops.align_to_grid(read, ref)
        return out

    if granule.get("path"):
        read = read_window(
            granule["path"],
            bbox_wgs84=bbox,
            band_names=[granule.get("band") or dataset.metadata_json.get("primary_variable") or "value"],
            max_dim=max_dim,
        )
        out[read.band_names[0]] = read
        return out

    for native, path in (granule.get("bands") or {}).items():
        try:
            read = read_window(path, bbox_wgs84=bbox, band_names=[native], max_dim=max_dim)
        except Exception as exc:
            raise UnprocessableError(
                f"Failed to read band '{native}' of granule '{granule.get('id')}': {exc}"
            ) from exc
        canonical = hz.canonical_for_sensor(sensor, native) or native
        if canonical in out:  # e.g. two QA bands mapping to the same canonical key
            canonical = native
        out[canonical] = read

    if not out:
        raise UnprocessableError(f"granule '{granule.get('id')}' has no readable bands")
    # co-register onto the coarsest band grid
    ref = max(out.values(), key=lambda r: max(abs(r.transform.a), abs(r.transform.e)))
    for key, read in list(out.items()):
        out[key] = crs_ops.align_to_grid(read, ref)
    return out


def load_observations(
    datasets: list[Dataset],
    *,
    study_area: StudyArea | None,
    granule_id: str | None = None,
    limit: int | None = None,
) -> tuple[list[dict[str, RasterRead]], list[str], list[tuple[Dataset, dict]]]:
    """Return (band-maps per observation, dates, source (dataset, granule) pairs)."""
    observations: list[dict[str, RasterRead]] = []
    dates: list[str] = []
    sources: list[tuple[Dataset, dict]] = []
    for dataset in datasets:
        if dataset.format in ("json", "csv"):
            # raster pipeline only supports GeoTIFF-backed datasets
            raise UnprocessableError(
                f"Dataset '{dataset.title}' is {dataset.format} time-series data; "
                "raster processing operations do not apply - use indicator computation instead"
            )
        bbox = _aoi_bbox(dataset, study_area)
        max_dim = _max_dim(dataset)
        for granule in granules_of(dataset):
            if granule_id and granule.get("id") != granule_id:
                continue
            obs = load_granule(dataset, granule, bbox=bbox, max_dim=max_dim)
            observations.append(obs)
            dates.append(str(granule.get("date") or ""))
            sources.append((dataset, granule))
            if limit and len(observations) >= limit:
                return observations, dates, sources
    if not observations:
        raise NotFoundError("No matching raster granules found for the selection")
    return observations, dates, sources


def _max_dim(dataset: Dataset) -> int | None:
    cfg = (dataset.metadata_json or {}).get("ingestion_config") or {}
    if dataset.data_source and dataset.data_source.ingestion_config_json:
        cfg = {**cfg, **(dataset.data_source.ingestion_config_json or {})}
    value = cfg.get("max_dim", 2048)
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return 2048


@dataclass
class PipelineState:
    observations: list[dict[str, RasterRead]]          # band key -> read (1 band each)
    dates: list[str]
    sources: list[tuple[Dataset, dict]]
    sensor: str
    study_area: StudyArea | None
    boundary: Any = None                               # shapely geometry (EPSG:4326)
    cloud_fraction: float | None = None
    valid_fraction: float | None = None
    run_metrics: list[dict] = field(default_factory=list)

    @property
    def primary_dataset(self) -> Dataset:
        return self.sources[0][0]


def _inside_mask(read: RasterRead, boundary) -> np.ndarray:
    from pyproj import Transformer
    from rasterio.features import geometry_mask
    from shapely.geometry import mapping
    from shapely.ops import transform as shp_transform

    transformer = Transformer.from_crs("EPSG:4326", read.crs, always_xy=True)
    geom = shp_transform(transformer.transform, boundary)
    return ~geometry_mask(
        [mapping(geom)],
        out_shape=(read.data.shape[1], read.data.shape[2]),
        transform=read.transform,
        invert=False,
    )


def _stack_bands(state: PipelineState) -> tuple[np.ndarray, list[str]]:
    """Stack the first observation's bands into (bands, y, x)."""
    obs = state.observations[0]
    keys = sorted(obs.keys(), key=band_sort_key)
    arrs = [obs[k].data[0] for k in keys]
    shapes = {a.shape for a in arrs}
    if len(shapes) != 1:
        raise UnprocessableError("bands are not on a common grid; run clip/align first")
    return np.stack(arrs, axis=0), keys


def _write_product(
    db: Session,
    *,
    state: PipelineState,
    op: str,
    params: dict,
    metrics: dict,
    job_id: int | None,
    actor: User | None,
    output_name: str,
    source_quality: str,
    source_quality_reason: str,
    workdir,
) -> DataProduct:
    data, keys = _stack_bands(state)
    first = state.observations[0][keys[0]]
    date_label = state.dates[0] if state.dates and state.dates[0] else "composite"
    band_names = [k if len(keys) == 1 else f"{k}" for k in keys]

    import rasterio

    if first.crs:
        b = rasterio.transform.array_bounds(first.data.shape[1], first.data.shape[2], first.transform)
        bbox_4326 = list(transform_bounds(first.crs, "EPSG:4326", *b))
    else:
        bbox_4326 = None

    fname = f"{output_name or op}_{date_label}".replace(" ", "_")
    fname = "".join(c if c.isalnum() or c in "-._" else "_" for c in fname)[:120]
    path = workdir / f"{fname}.tif"
    write_geotiff(
        path,
        data,
        transform=first.transform,
        crs=first.crs,
        nodata=np.nan,
        band_names=band_names,
        tags={
            "operation": op,
            "params": str(params)[:500],
            "sensor": state.sensor,
            "dates": ",".join(d for d in state.dates if d)[:500],
            "algorithm_version": ALGORITHM_VERSION,
            "units": "scaled source units (reflectance/flag/value as stored)",
        },
        dtype="float32",
    )
    product = DataProduct(
        processing_run_id=None,
        kind="raster",
        name=f"{output_name or PROCESSING_OPERATIONS[op]['label']} ({date_label})",
        description=PROCESSING_OPERATIONS[op]["description"],
        format="geotiff",
        file_path=relative(path),
        crs=first.crs.to_string() if first.crs else None,
        bbox_geojson=(
            {"type": "Polygon", "coordinates": [[
                [bbox_4326[0], bbox_4326[1]], [bbox_4326[2], bbox_4326[1]],
                [bbox_4326[2], bbox_4326[3]], [bbox_4326[0], bbox_4326[3]],
                [bbox_4326[0], bbox_4326[1]],
            ]]} if bbox_4326 else None
        ),
        resolution_m=abs(first.transform.a),
        size_bytes=path.stat().st_size,
        checksum=file_checksum(path),
        metadata_json={
            "bands": band_names,
            "dates": state.dates,
            "source_dataset_ids": sorted({d.id for d, _ in state.sources}),
            "source_granule_ids": [g.get("id") for _, g in state.sources],
            "operation": op,
            "params": params,
            "algorithm_version": ALGORITHM_VERSION,
            "sensor": state.sensor,
        },
        quality_flag=source_quality,
        created_at=utcnow(),
    )
    db.add(product)
    db.flush()
    return product


# --- operations --------------------------------------------------------------
OpFn = Callable[[PipelineState, dict], tuple[PipelineState, dict, bool]]
OPERATORS: dict[str, OpFn] = {}


def op_(name: str):
    def deco(fn: OpFn) -> OpFn:
        OPERATORS[name] = fn
        return fn

    return deco


@op_("validate")
def _op_validate(state: PipelineState, params: dict) -> tuple[PipelineState, dict, bool]:
    obs = state.observations[0]
    first = next(iter(obs.values()))
    issues: list[str] = []
    if first.crs is None:
        issues.append("input has no CRS defined")
    if not obs:
        issues.append("no bands readable")
    if state.boundary is not None:
        from shapely.geometry import box

        try:
            b4326 = transform_bounds(first.crs, "EPSG:4326", *first.bounds)
        except Exception:
            b4326 = tuple(first.bounds)
        if not box(*b4326).intersects(state.boundary):
            issues.append("input footprint does not intersect the study area")
    if issues:
        raise UnprocessableError("Input validation failed", details={"issues": issues})
    metrics = {
        "bands": sorted(obs.keys(), key=band_sort_key),
        "crs": first.crs.to_string() if first.crs else None,
        "resolution_m": abs(first.transform.a),
        "shape": [first.data.shape[1], first.data.shape[2]],
        "granules_checked": len(state.sources),
        "issues": [],
    }
    return state, metrics, False


@op_("clip")
def _op_clip(state: PipelineState, params: dict) -> tuple[PipelineState, dict, bool]:
    if state.boundary is None:
        raise UnprocessableError("clip requires a study area with a boundary geometry")
    inside_fracs = []
    for _i, obs in enumerate(state.observations):
        for key, read in list(obs.items()):
            data, valid, frac = clip_to_geometry(read, state.boundary, all_touched=bool(params.get("all_touched", False)))
            obs[key] = RasterRead(
                data=data,
                band_names=read.band_names,
                crs=read.crs,
                transform=read.transform,
                nodata=np.nan,
                valid_mask=valid,
                bounds=read.bounds,
                path=read.path,
                tags=read.tags,
            )
        inside_fracs.append(frac)
    return state, {"inside_fraction": round(float(np.mean(inside_fracs)), 6)}, True


@op_("reproject")
def _op_reproject(state: PipelineState, params: dict) -> tuple[PipelineState, dict, bool]:
    dst_crs = params.get("dst_crs") or "EPSG:4326"
    resampling = params.get("resampling") or "bilinear"
    for obs in state.observations:
        for key, read in list(obs.items()):
            obs[key] = crs_ops.reproject_read(read, dst_crs, resampling=resampling)
    first = next(iter(state.observations[0].values()))
    return state, {"dst_crs": dst_crs, "resampling": resampling,
                   "resolution_m": abs(first.transform.a)}, True


@op_("resample")
def _op_resample(state: PipelineState, params: dict) -> tuple[PipelineState, dict, bool]:
    target = params.get("resolution_m")
    if not target:
        raise UnprocessableError("resample requires params.resolution_m")
    resampling = params.get("resampling") or "bilinear"
    for obs in state.observations:
        for key, read in list(obs.items()):
            obs[key] = crs_ops.resample_to_resolution(read, float(target), resampling=resampling)
    return state, {"resolution_m": float(target), "resampling": resampling}, True


@op_("cloud_mask")
def _op_cloud_mask(state: PipelineState, params: dict) -> tuple[PipelineState, dict, bool]:
    sensor = state.sensor
    fractions = []
    for obs in state.observations:
        qa_read = obs.get("qa")
        if qa_read is None:
            raise UnprocessableError(
                f"cloud_mask requires a QA band for sensor '{sensor}' "
                "(Sentinel-2 SCL, Landsat QA_PIXEL or MODIS state/QC band)"
            )
        qa = qa_read.data[0]
        if sensor == "sentinel2":
            clear = cm.s2_scl_clear_mask(qa)
        elif sensor == "landsat":
            clear = cm.landsat_qa_clear_mask(qa)
        elif sensor == "modis":
            native = qa_read.band_names[0]
            clear = cm.modis_lst_qc_clear_mask(qa) if native == "QC_1km" else cm.modis_state_clear_mask(qa)
        else:
            raise UnprocessableError(f"no cloud-mask rule implemented for sensor '{sensor}'")
        footprint = np.isfinite(np.stack([r.data[0] for r in obs.values()])).any(axis=0)
        frac = cm.assess_cloud_fraction(clear, footprint)
        fractions.append(frac)
        for key, read in list(obs.items()):
            if key == "qa":
                continue
            data = read.data.copy()
            data[0, ~clear] = np.nan
            obs[key] = RasterRead(
                data=data, band_names=read.band_names, crs=read.crs, transform=read.transform,
                nodata=np.nan, valid_mask=np.isfinite(data).all(axis=0), bounds=read.bounds,
                path=read.path, tags=read.tags,
            )
    cloud_fraction = float(np.mean(fractions)) if fractions else None
    state.cloud_fraction = cloud_fraction
    return state, {"cloud_fraction": round(cloud_fraction, 6) if cloud_fraction is not None else None,
                   "method": "sensor QA (SCL/QA_PIXEL/state/QC)"}, True


@op_("water_mask")
def _op_water_mask(state: PipelineState, params: dict) -> tuple[PipelineState, dict, bool]:
    method = params.get("method") or "mndwi"
    threshold = float(params.get("threshold", wm.DEFAULT_MNDWI_THRESHOLD))
    fracs = []
    for obs in state.observations:
        green = obs.get("green")
        swir = obs.get("swir1")
        nir = obs.get("nir")
        if green is None or (method == "mndwi" and swir is None) or (method == "ndwi" and nir is None):
            raise UnprocessableError(
                f"water_mask via {method.upper()} requires green + {'SWIR1' if method == 'mndwi' else 'NIR'} bands"
            )
        result = wm.water_mask(
            green.data[0],
            swir.data[0] if swir is not None else None,
            nir.data[0] if nir is not None else None,
            method=method,
            threshold=threshold,
            valid_mask=green.valid_mask,
        )
        fracs.append(result.water_fraction)
        ref = green
        obs[method] = RasterRead(
            data=result.index[np.newaxis, ...].astype("float32"),
            band_names=[method], crs=ref.crs, transform=ref.transform, nodata=np.nan,
            valid_mask=result.valid_mask, bounds=ref.bounds, path="", tags={},
        )
        mask_arr = np.where(result.valid_mask, result.water_mask.astype("float32"), np.nan)
        obs["water_mask"] = RasterRead(
            data=mask_arr[np.newaxis, ...], band_names=["water_mask"], crs=ref.crs,
            transform=ref.transform, nodata=np.nan, valid_mask=result.valid_mask,
            bounds=ref.bounds, path="", tags={},
        )
    return state, {
        "method": method, "threshold": threshold,
        "water_fraction": round(float(np.mean(fracs)), 6) if fracs else None,
        "threshold_note": "threshold is provisional and configurable",
    }, True


@op_("harmonize")
def _op_harmonize(state: PipelineState, params: dict) -> tuple[PipelineState, dict, bool]:
    try:
        adjustment = hz.adjustment_from_config(params)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
    for obs in state.observations:
        arrays = {k: r.data for k, r in obs.items()}
        adjusted, info = hz.apply_linear_adjustment(arrays, adjustment)
        for k, arr in adjusted.items():
            read = obs[k]
            obs[k] = RasterRead(
                data=arr, band_names=read.band_names, crs=read.crs, transform=read.transform,
                nodata=np.nan, valid_mask=np.isfinite(arr).all(axis=0), bounds=read.bounds,
                path=read.path, tags=read.tags,
            )
    info = adjustment.as_dict()
    if not adjustment.applied:
        info["note"] = (
            "No validated cross-sensor coefficients supplied - identity transform applied; "
            "cross-sensor comparisons remain indicative only."
        )
    return state, info, True


@op_("temporal_composite")
def _op_composite(state: PipelineState, params: dict) -> tuple[PipelineState, dict, bool]:
    if len(state.observations) < 2:
        raise UnprocessableError(
            "temporal_composite needs at least two observations/dates "
            f"(got {len(state.observations)}); select multiple datasets or granules"
        )
    method = params.get("method") or "median"
    percentile = float(params.get("percentile", 75.0))
    only_band = params.get("band") or ""

    # union grid across dates for each band key present in the first observation
    band_keys = sorted(state.observations[0].keys(), key=band_sort_key)
    if only_band:
        band_keys = [k for k in band_keys if k == only_band] or band_keys

    composite_obs: dict[str, RasterRead] = {}
    coverage_summary = {}
    for key in band_keys:
        reads = []
        for obs in state.observations:
            r = obs.get(key)
            if r is None:
                continue
            reads.append(r)
        if not reads:
            continue
        # align every date onto the union grid of this band
        target_crs, transform, width, height = crs_ops.union_grid(reads)
        aligned = [
            crs_ops.warp_to_grid(r, dst_crs=target_crs, dst_transform=transform, width=width, height=height)
            for r in reads
        ]
        comp = temporal_composite(aligned, method=method, percentile=percentile, dates=state.dates)
        composite_obs[key] = RasterRead(
            data=comp.data if comp.data.ndim == 3 else comp.data[np.newaxis, ...],
            band_names=[key], crs=target_crs, transform=transform, nodata=np.nan,
            valid_mask=np.isfinite(comp.data if comp.data.ndim == 3 else comp.data[np.newaxis, ...]).all(axis=0),
            bounds=reads[0].bounds, path="", tags={"dates": ",".join(d for d in state.dates if d)},
        )
        coverage_summary[key] = {
            "mean_coverage": round(float(np.nanmean(comp.coverage)), 6),
            "min_coverage": round(float(np.nanmin(comp.coverage)), 6),
        }

    if not composite_obs:
        raise UnprocessableError("no bands available to composite")
    state.observations = [composite_obs]
    state.dates = [f"composite of {len(state.dates)} dates"]
    return state, {
        "method": method,
        "percentile": percentile if method == "percentile" else None,
        "n_observations": len(state.sources),
        "coverage": coverage_summary,
    }, True


@op_("missing_data")
def _op_missing(state: PipelineState, params: dict) -> tuple[PipelineState, dict, bool]:
    per_band = {}
    worst_valid = 1.0
    for key, read in state.observations[0].items():
        valid = np.isfinite(read.data[0])
        if state.boundary is not None:
            inside = _inside_mask(read, state.boundary)
            stats = qmod.assess_missing(valid, inside)
        else:
            stats = qmod.assess_missing(valid)
        per_band[key] = stats.as_dict()
        worst_valid = min(worst_valid, stats.valid_fraction)
    state.valid_fraction = worst_valid
    return state, {"valid_fraction_worst_band": round(worst_valid, 6), "bands": per_band}, False


@op_("quality_flags")
def _op_quality(state: PipelineState, params: dict) -> tuple[PipelineState, dict, bool]:
    obs = state.observations[0]
    first = next(iter(obs.values()))
    valid = np.isfinite(first.data[0])
    if state.boundary is not None:
        inside = _inside_mask(first, state.boundary)
        stats = qmod.assess_missing(valid, inside)
    else:
        stats = qmod.assess_missing(valid)
    coverage = stats.valid_fraction if stats.total_pixels else 0.0
    decision = qmod.evaluate_quality(
        coverage_fraction=coverage,
        cloud_fraction=state.cloud_fraction,
        missing=stats,
        unvalidated=False,
    )
    state.valid_fraction = coverage
    metrics = {
        "flag": decision.flag,
        "reason": decision.reason,
        "flags": decision.all_flags,
        "reasons": decision.reasons,
        "details": decision.details,
    }
    return state, metrics, False


def run_pipeline(
    db: Session,
    *,
    dataset_ids: list[int],
    operations: list[str],
    params: dict,
    actor: User | None,
    job_id: int | None = None,
    output_name: str = "",
    study_area_id: int | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Execute the requested operation sequence.

    Returns a summary dict; raises UnprocessableError on validation failures
    (the job layer records the failure + audit entry).
    """
    datasets = [db.get(Dataset, i) for i in dataset_ids]
    missing = [i for i, d in zip(dataset_ids, datasets, strict=False) if d is None]
    if missing:
        raise NotFoundError(f"Datasets not found: {missing}")
    datasets = [d for d in datasets if d is not None]

    study_area = None
    boundary = None
    if study_area_id:
        study_area = db.get(StudyArea, study_area_id)
    elif datasets[0].study_area_id:
        study_area = db.get(StudyArea, datasets[0].study_area_id)
    if study_area is not None:
        boundary = parse_geojson_geometry(study_area.boundary_geojson, allowed=["Polygon", "MultiPolygon"])

    composite_mode = "temporal_composite" in operations
    if composite_mode:
        observations, dates, sources = load_observations(datasets, study_area=study_area)
    else:
        observations, dates, sources = load_observations(
            datasets, study_area=study_area, granule_id=params.get("granule_id"), limit=1
        )

    state = PipelineState(
        observations=observations,
        dates=dates,
        sources=sources,
        sensor=sensor_for(datasets[0]),
        study_area=study_area,
        boundary=boundary,
    )

    from app.services.storage import new_workspace

    workdir = new_workspace("processed")
    source_quality = datasets[0].quality_flag or "UNVALIDATED"
    source_quality_reason = datasets[0].quality_reason or ""

    run_ids: list[int] = []
    product_ids: list[int] = []
    final_product_id: int | None = None
    summary_ops: dict[str, dict] = {}
    n = len(operations)

    for idx, op_name in enumerate(operations):
        spec = PROCESSING_OPERATIONS.get(op_name)
        if spec is None:
            raise UnprocessableError(f"Unknown operation '{op_name}'")
        fn = OPERATORS.get(op_name)
        if fn is None:
            raise UnprocessableError(f"Operation '{op_name}' has no implementation")

        spec_params = {p["name"]: params.get(p["name"], p.get("default")) for p in spec["params"]}
        run = ProcessingRun(
            operation=op_name,
            # store full effective params (operation-specific values + run-level selection)
            params_json={
                "operation_params": spec_params,
                "granule_id": params.get("granule_id"),
                "study_area_id": study_area.id if study_area else None,
            },
            algorithm_version=ALGORITHM_VERSION,
            input_dataset_ids_json=[d.id for d in datasets],
            job_id=job_id,
            status="running",
            requested_by_id=actor.id if actor else None,
            started_at=utcnow(),
        )
        db.add(run)
        db.flush()
        run_ids.append(run.id)
        op_params = spec_params

        try:
            state, metrics, changed = fn(state, op_params)
        except Exception as exc:
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"[:4000]
            run.finished_at = utcnow()
            db.commit()
            raise

        run.status = "succeeded"
        run.metrics_json = metrics
        run.finished_at = utcnow()

        product: DataProduct | None = None
        if spec["writes_product"] and changed:
            product = _write_product(
                db,
                state=state,
                op=op_name,
                params=op_params,
                metrics=metrics,
                job_id=job_id,
                actor=actor,
                output_name=output_name,
                source_quality=source_quality,
                source_quality_reason=source_quality_reason,
                workdir=workdir,
            )
            product_ids.append(product.id)
            final_product_id = product.id
            run.output_product_id = product.id

        if op_name == "quality_flags" and product is None and run_ids:
            # attach the assessment to the most recent product (or the dataset)
            last_product = db.get(DataProduct, final_product_id) if final_product_id else None
            if last_product is not None:
                last_product.quality_flag = metrics["flag"]
                qa = QualityAssessment(
                    subject_type="product",
                    subject_id=last_product.id,
                    rule_version=metrics["details"]["rule_version"],
                    flag=metrics["flag"],
                    reason=metrics["reason"],
                    coverage_fraction=metrics["details"].get("coverage_fraction"),
                    missing_fraction=(metrics["details"].get("missing") or {}).get("missing_fraction"),
                    cloud_fraction=metrics["details"].get("cloud_fraction"),
                    details_json=metrics,
                    created_at=utcnow(),
                )
                db.add(qa)

        summary_ops[op_name] = metrics
        db.commit()
        if progress:
            progress((idx + 1) / n, f"{op_name} completed")

    return {
        "run_ids": run_ids,
        "product_ids": product_ids,
        "final_product_id": final_product_id,
        "operations": summary_ops,
        "input_dataset_ids": [d.id for d in datasets],
        "n_observations": len(observations),
        "dates": [d for d in dates if d],
        "sensor": state.sensor,
        "algorithm_version": ALGORITHM_VERSION,
        "output_dir": str(workdir),
    }

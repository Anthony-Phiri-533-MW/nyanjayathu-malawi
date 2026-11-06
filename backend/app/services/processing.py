"""Processing orchestration: enqueue preprocessing runs and register their
output products as derived datasets so indicators can consume them.

A successful raster product becomes a ``Dataset`` (kind ``composite`` for
temporal composites, otherwise ``processed``) whose granule points at the
product GeoTIFF plus a ``band_indexes`` map.  That makes derived products
first-class inputs for indicator computation and export, with the processing
run ids recorded as provenance.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from sqlalchemy import select

from app.core.errors import NotFoundError, UnprocessableError
from app.models import DataProduct, Dataset, StudyArea, User, utcnow
from app.schemas.research import ProcessingRunCreate
from app.services import audit as audit_service
from app.services.ingestion import dataset_capabilities
from app.services.jobs import JobContext, enqueue, register_handler

DERIVED_BANDS_LABEL = "derived band"
BAND_UNITS = {
    "blue": "reflectance",
    "green": "reflectance",
    "red": "reflectance",
    "nir": "reflectance",
    "swir1": "reflectance",
    "swir2": "reflectance",
    "red_edge_1": "reflectance",
    "thermal": "K",
    "precipitation": "mm",
    "air_temperature": "°C",
    "water_level": "m",
    "qa": "code",
    "mndwi": "index",
    "ndwi": "index",
    "water_mask": "binary",
}


def _params_hash(params: dict[str, Any], output_name: str) -> str:
    payload = json.dumps({"params": params, "output_name": output_name}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _raster_readiness_issues(datasets: list[Dataset]) -> list[str]:
    """Datasets whose granules are not raster-reprocessable.

    Sentinel-3 SRAL granules are netCDF point measurements — raster
    preprocessing operations (validate/clip/composites/…) cannot apply, and
    attempting one previously surfaced as an opaque
    ``rasterio.errors.RasterioIOError`` retried to exhaustion.  Altimetry
    datasets belong in *indicator* computation (``water_level_altimetry``).
    """
    issues: list[str] = []
    for dataset in datasets:
        granules = ((dataset.metadata_json or {}).get("granules")) or []
        paths = [
            str(path)
            for granule in granules
            for path in (granule.get("bands") or {}).values()
            if isinstance(path, str)
        ]
        if paths and all(p.endswith(".nc") for p in paths):
            issues.append(
                f"Dataset {dataset.id} ('{dataset.title}') stores netCDF point "
                "measurements, not rasters; raster preprocessing does not apply. "
                "Compute the water_level_altimetry indicator on it instead."
            )
    return issues


def start_processing(
    db,
    *,
    payload: ProcessingRunCreate,
    actor: User,
    study_area_id: int | None = None,
) -> Any:
    datasets = list(
        db.execute(select(Dataset).where(Dataset.id.in_(payload.dataset_ids))).scalars()
    )
    missing = sorted(set(payload.dataset_ids) - {d.id for d in datasets})
    if missing:
        raise NotFoundError(f"Datasets not found: {missing}")

    readiness = _raster_readiness_issues(datasets)
    if readiness:
        raise UnprocessableError(
            "Some selected datasets cannot be preprocessed with raster "
            "operations",
            details={"issues": readiness},
        )

    if study_area_id is None:
        implied = {d.study_area_id for d in datasets if d.study_area_id}
        study_area_id = next(iter(implied)) if len(implied) == 1 else None
    if study_area_id is not None and db.get(StudyArea, study_area_id) is None:
        raise NotFoundError(f"Study area {study_area_id} not found")

    dedupe = (
        "processing:"
        + ",".join(str(i) for i in sorted(payload.dataset_ids))
        + ":"
        + ",".join(payload.operations)
        + ":"
        + _params_hash(payload.params, payload.output_name)
    )
    job = enqueue(
        db,
        kind="processing",
        params={
            "dataset_ids": payload.dataset_ids,
            "operations": payload.operations,
            "params": payload.params,
            "output_name": payload.output_name,
            "study_area_id": study_area_id,
        },
        requested_by_id=actor.id,
        dedupe_key=dedupe[:200],
    )
    db.flush()
    audit_service.record(
        action="processing.request",
        resource_type="job",
        resource_id=job.id,
        actor=actor,
        db=db,
        message=(
            f"Requested processing {payload.operations} on dataset(s) "
            f"{payload.dataset_ids}"
        ),
        details={"dataset_ids": payload.dataset_ids, "operations": payload.operations},
    )
    return job


def _band_records(bands: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "key": name,
            "label": name,
            "unit": BAND_UNITS.get(name, ""),
            "scale": 1.0,
            "offset": 0.0,
            "description": (
                "QA/flag band (integer codes stored as float, nearest-resampled)"
                if name == "qa"
                else f"{DERIVED_BANDS_LABEL} from a processing run"
            ),
        }
        for name in bands
    ]


def dataset_from_product(
    db,
    *,
    product: DataProduct,
    operations: list[str],
    input_datasets: list[Dataset],
    study_area_id: int | None,
    actor: User | None,
) -> Dataset:
    """Persist a derived ``Dataset`` describing a processing product."""
    meta = product.metadata_json or {}
    bands = [str(b) for b in (meta.get("bands") or [])]
    if not bands:
        raise UnprocessableError(
            f"product {product.id} has no band metadata; cannot register a derived dataset"
        )
    source = input_datasets[0] if input_datasets else None
    provider_key = source.provider_key if source else "derived"
    category = source.category if source else "derived"
    from app.processing.pipeline import PROVIDER_SENSOR

    sensor = PROVIDER_SENSOR.get(provider_key, provider_key)
    capabilities = dataset_capabilities({name: {} for name in bands}, sensor)

    starts = [d.start_date for d in input_datasets if d.start_date]
    ends = [d.end_date or d.start_date for d in input_datasets if d.start_date]
    start_date: date | None = min(starts) if starts else None
    end_date: date | None = max(ends) if ends else None

    is_composite = "temporal_composite" in operations
    if is_composite:
        dates = [d for d in (meta.get("dates") or []) if d]
        # dates may include "composite of N dates"; keep only ISO dates
        iso_dates = []
        for value in dates:
            try:
                iso_dates.append(date.fromisoformat(str(value)[:10]))
            except ValueError:
                continue
        if iso_dates:
            start_date, end_date = min(iso_dates), max(iso_dates)

    granule_date = end_date.isoformat() if end_date else None
    metadata_json = {
        "granules": [
            {
                "id": f"product:{product.id}",
                "date": granule_date,
                "path": product.file_path,
                "band_indexes": {name: idx + 1 for idx, name in enumerate(bands)},
            }
        ],
        "bands": {
            name: {
                "crs": product.crs,
                "resolution_m": product.resolution_m,
                "unit": "reflectance",
                "label": name,
                "scale": 1.0,
                "offset": 0.0,
            }
            for name in bands
        },
        "capabilities": capabilities,
        "provider": provider_key,
        "derived": True,
        "product_id": product.id,
        "processing_run_ids": meta.get("run_ids") or [],
        "operations": operations,
        "source_dataset_ids": [d.id for d in input_datasets],
        "source_granule_ids": meta.get("source_granule_ids") or [],
        "period": {
            "start": start_date.isoformat() if start_date else None,
            "end": end_date.isoformat() if end_date else None,
        },
        "ingestion_config": (source.metadata_json or {}).get("ingestion_config", {})
        if source
        else {},
        "primary_variable": bands[0] if len(bands) == 1 else None,
    }
    provenance_json = {
        "kind": "derived",
        "product_id": product.id,
        "product_format": product.format,
        "processing_operations": operations,
        "algorithm_version": meta.get("algorithm_version"),
        "source_dataset_ids": [d.id for d in input_datasets],
        "source_granule_ids": meta.get("source_granule_ids") or [],
        "derived_at": utcnow().isoformat(),
        "notes": [
            "derived product - not a raw observation",
            "inherits source quality flagging; run quality_flags for a per-product assessment",
        ],
    }

    dataset = Dataset(
        title=product.name[:300],
        provider_key=provider_key,
        category=category,
        product_type=("temporal composite" if is_composite else "processed product")[:80],
        kind="composite" if is_composite else "processed",
        is_raw=False,
        data_source_id=source.data_source_id if source else None,
        ingestion_job_id=None,
        study_area_id=study_area_id,
        start_date=start_date,
        end_date=end_date,
        crs=product.crs,
        resolution_m=product.resolution_m,
        bands_json=_band_records(bands),
        coverage_geojson=product.bbox_geojson,
        format=product.format or "geotiff",
        file_path=product.file_path,
        size_bytes=product.size_bytes,
        checksum=product.checksum,
        metadata_json=metadata_json,
        provenance_json=provenance_json,
        quality_flag=product.quality_flag or "UNVALIDATED",
        quality_reason="derived product; see the processing run and source dataset quality",
        created_by_id=actor.id if actor else None,
    )
    db.add(dataset)
    db.flush()
    return dataset


@register_handler("processing")
def handle_processing_job(ctx: JobContext) -> dict:
    from app.processing.pipeline import run_pipeline

    params = ctx.params
    dataset_ids = [int(i) for i in params.get("dataset_ids") or []]
    operations = [str(o) for o in params.get("operations") or []]
    if not dataset_ids or not operations:
        raise UnprocessableError("processing job is missing dataset_ids or operations")

    summary = run_pipeline(
        ctx.db,
        dataset_ids=dataset_ids,
        operations=operations,
        params=dict(params.get("params") or {}),
        actor=ctx.actor,
        job_id=ctx.job.id,
        output_name=str(params.get("output_name") or ""),
        study_area_id=params.get("study_area_id"),
        progress=ctx.progress,
    )

    dataset_id: int | None = None
    product_id = summary.get("final_product_id")
    if product_id:
        product = ctx.db.get(DataProduct, product_id)
        inputs = [
            d
            for d in (ctx.db.get(Dataset, i) for i in dataset_ids)
            if d is not None
        ]
        if product is not None and product.format == "geotiff":
            derived = dataset_from_product(
                ctx.db,
                product=product,
                operations=operations,
                input_datasets=inputs,
                study_area_id=params.get("study_area_id"),
                actor=ctx.actor,
            )
            dataset_id = derived.id
            summary["derived_dataset_id"] = dataset_id
            summary["derived_dataset_kind"] = derived.kind
            ctx.db.commit()

    audit_service.record(
        action="processing.complete",
        resource_type="job",
        resource_id=ctx.job.id,
        actor=ctx.actor,
        message=f"Processing completed: {', '.join(operations)}",
        details={
            "run_ids": summary.get("run_ids"),
            "product_ids": summary.get("product_ids"),
            "derived_dataset_id": dataset_id,
        },
    )
    return summary

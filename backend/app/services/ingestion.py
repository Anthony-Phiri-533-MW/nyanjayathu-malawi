"""Ingestion orchestration: discover items via a provider adapter, fetch them
into storage, and record one ``Dataset`` per retrieved item.

One dataset per item keeps provenance, quality assessment and date filtering
unambiguous (e.g. one Sentinel-2 scene, one CHIRPS day, one POWER chunk).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, UnprocessableError
from app.models import Dataset, DataSource, IngestionJob, StudyArea, User
from app.providers import IngestParams, ProviderError, get_adapter, known_provider_keys
from app.providers.base import ProviderAdapter
from app.schemas.research import IngestionJobCreate
from app.services import audit as audit_service
from app.services import data_sources as data_sources_service
from app.services.jobs import JobContext, enqueue, register_handler
from app.services.storage import new_workspace

log = logging.getLogger("lakewatch.ingestion")

CAPABILITY_CANONICALS = {
    "optical": {"blue", "green", "red", "nir", "swir1", "swir2", "red_edge_1"},
    "optical_qa": {"qa"},
    "thermal": {"thermal"},
    "precipitation": {"precipitation"},
    "temperature": {"air_temperature"},
    "altimetry": {"water_level"},
}


def _slug(value: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-._" else "_" for c in (value or "item"))
    return keep.strip("._")[:80] or "item"


def _adapter_for(ds: DataSource) -> ProviderAdapter:
    config: dict[str, Any] = {}
    if ds.dataset_identifier:
        config["collection"] = ds.dataset_identifier
    if ds.dataset_name:
        config["dataset_name"] = ds.dataset_name
    if ds.ingestion_config_json:
        config.update(ds.ingestion_config_json)
    try:
        return get_adapter(ds.provider_key, config=config)
    except ProviderError as exc:
        raise UnprocessableError(
            f"No adapter is registered for provider '{ds.provider_key}'",
            details={"available": known_provider_keys()},
        ) from exc


def sensor_for(provider_key: str) -> str:
    from app.processing.pipeline import PROVIDER_SENSOR

    return PROVIDER_SENSOR.get(provider_key, provider_key)


def dataset_capabilities(bands: dict[str, Any], sensor: str) -> list[str]:
    from app.processing import harmonize as hz

    canonicals = {hz.canonical_for_sensor(sensor, native) or native for native in bands}
    return [cap for cap, keys in CAPABILITY_CANONICALS.items() if canonicals & keys]


def requested_variables(ds: DataSource, explicit: list[str] | None) -> list[str]:
    if explicit:
        return [str(v) for v in explicit if v]
    stored = ds.variables_json
    if isinstance(stored, list):
        keys = [str(v.get("key")) for v in stored if isinstance(v, dict) and v.get("key")]
        if keys:
            return keys
    return []


def start_ingestion(db: Session, *, payload: IngestionJobCreate, actor: User | None) -> tuple[Any, IngestionJob]:
    """Create a pending ingestion job (+ its IngestionJob record)."""
    ds = db.get(DataSource, payload.data_source_id)
    if ds is None:
        raise NotFoundError("Data source not found", details={"id": payload.data_source_id})
    if not ds.is_enabled:
        raise UnprocessableError(
            f"Data source '{ds.name}' is disabled; enable it in the admin module first"
        )
    sa = db.get(StudyArea, payload.study_area_id)
    if sa is None:
        raise NotFoundError("Study area not found", details={"id": payload.study_area_id})

    variables = requested_variables(ds, payload.variables)
    dedupe = (
        f"ingestion:{ds.id}:{sa.id}:{payload.start_date.isoformat()}:"
        f"{payload.end_date.isoformat()}:{','.join(sorted(variables))}"
    )
    job = enqueue(
        db,
        kind="ingestion",
        params={
            "data_source_id": ds.id,
            "data_source_name": ds.name,
            "study_area_id": sa.id,
            "start_date": payload.start_date.isoformat(),
            "end_date": payload.end_date.isoformat(),
            "variables": variables,
        },
        requested_by_id=actor.id if actor else None,
        dedupe_key=dedupe,
    )
    db.flush()
    existing = db.execute(
        select(IngestionJob).where(IngestionJob.job_id == job.id)
    ).scalar_one_or_none()
    if existing is not None:
        return job, existing
    ing = IngestionJob(
        job_id=job.id,
        data_source_id=ds.id,
        study_area_id=sa.id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        variables_json=variables,
        discovered_count=0,
        stored_count=0,
    )
    db.add(ing)
    db.flush()
    audit_service.record(
        action="ingestion.request",
        resource_type="ingestion_job",
        resource_id=ing.id,
        actor=actor,
        db=db,
        message=(
            f"Requested ingestion from '{ds.name}' for {sa.name} "
            f"({payload.start_date} to {payload.end_date})"
        ),
        details={"data_source_id": ds.id, "variables": variables, "job_id": job.id},
    )
    return job, ing


def _first_band_meta(bands: dict[str, Any], key: str) -> Any:
    for meta in bands.values():
        if meta.get(key) is not None:
            return meta[key]
    return None


def _coverage_polygon(bounds_wgs84: list[float] | None):
    if not bounds_wgs84 or len(bounds_wgs84) != 4:
        return None
    minx, miny, maxx, maxy = bounds_wgs84
    if minx == maxx or miny == maxy:
        return None
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [minx, miny],
                [maxx, miny],
                [maxx, maxy],
                [minx, maxy],
                [minx, miny],
            ]
        ],
    }


def _record_dataset(db: Session, *, ing: IngestionJob, ds: DataSource, sa: StudyArea, adapter: ProviderAdapter, artifact, actor: User | None) -> Dataset:
    meta = dict(artifact.metadata or {})
    bands: dict[str, Any] = dict(meta.get("bands") or {})
    sensor = sensor_for(ds.provider_key)
    from app.processing import harmonize as hz

    band_records = []
    for native, binfo in bands.items():
        canonical = hz.canonical_for_sensor(sensor, native) or native
        note_bits = [f"canonical band: {canonical}"]
        if binfo.get("resolution_note"):
            note_bits.append(str(binfo["resolution_note"]))
        if binfo.get("source_scale") not in (None, 1.0) or binfo.get("source_offset") not in (None, 0.0):
            note_bits.append(
                f"source DN scaling applied at retrieval: x{binfo.get('source_scale')} "
                f"{'+' if (binfo.get('source_offset') or 0) >= 0 else ''}{binfo.get('source_offset')}"
            )
        elif binfo.get("source_scale") == 1.0:
            note_bits.append("stored values are as published (no scaling)")
        band_records.append(
            {
                "key": native,
                "label": binfo.get("label") or canonical,
                "unit": binfo.get("unit") or "",
                "scale": 1.0,
                "offset": 0.0,
                "description": "; ".join(note_bits),
            }
        )

    coverage = _coverage_polygon(_first_band_meta(bands, "bounds_wgs84"))
    if coverage is None and meta.get("sample_point"):
        lon, lat = meta["sample_point"]
        coverage = {"type": "Point", "coordinates": [float(lon), float(lat)]}

    capabilities = dataset_capabilities(bands, sensor)
    primary_variable = meta.get("primary_variable")
    if not primary_variable and len(bands) == 1:
        primary_variable = next(iter(bands))

    metadata_json = {
        "granules": meta.get("granules") or [],
        "bands": bands,
        "capabilities": capabilities,
        "provider": adapter.key,
        "product_type": adapter.product_type,
        "collection": meta.get("collection"),
        "item_id": artifact.item.asset_id,
        "scene_bbox": meta.get("scene_bbox"),
        "source_urls": meta.get("source_urls"),
        "sample_point": meta.get("sample_point"),
        "fill_value": meta.get("fill_value"),
        "fill_value_note": meta.get("fill_value_note"),
        "date_range": meta.get("date_range"),
        "raw_path": meta.get("raw_path"),
        "source_bundle_bytes": meta.get("source_bundle_bytes"),
        "source_checksum_sha256": meta.get("source_checksum_sha256"),
        "resolution_note": _first_band_meta(bands, "resolution_note"),
        "qa_asset_added": meta.get("qa_asset_added"),
        "max_dim": meta.get("max_dim"),
        "ingestion_config": ds.ingestion_config_json or {},
        "primary_variable": primary_variable,
    }
    provenance_json = {
        "provider_key": ds.provider_key,
        "provider_label": adapter.label,
        "adapter_status": adapter.adapter_status,
        "data_source_id": ds.id,
        "data_source_name": ds.name,
        "dataset_identifier": ds.dataset_identifier,
        "item_id": artifact.item.asset_id,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "requested_by": actor.email if actor else None,
        "ingestion_job_id": ing.id,
        "source_urls": meta.get("source_urls") or {},
        "scaling_applied_at_retrieval": {
            native: {
                "scale": binfo.get("source_scale"),
                "offset": binfo.get("source_offset"),
                "stored_unit": binfo.get("unit"),
            }
            for native, binfo in bands.items()
        },
        "windowed_to_bbox": [sa.minx, sa.miny, sa.maxx, sa.maxy],
        "max_dim": meta.get("max_dim"),
        "checksum_sha256": artifact.checksum,
        "notes": [
            "Raw ingested observation: no validation or quality flag has been applied yet.",
            "Stored values are physical units where a documented source scaling exists.",
        ],
    }

    dataset = Dataset(
        title=f"{ds.name} - {artifact.item.title}"[:300],
        provider_key=ds.provider_key,
        category=ds.category,
        product_type=(adapter.product_type or "")[:80],
        kind="observed",
        is_raw=True,
        data_source_id=ds.id,
        ingestion_job_id=ing.id,
        study_area_id=sa.id,
        start_date=artifact.item.start_date,
        end_date=artifact.item.end_date,
        crs=_first_band_meta(bands, "crs"),
        resolution_m=_first_band_meta(bands, "resolution_m"),
        bands_json=band_records,
        coverage_geojson=coverage,
        format=meta.get("format") or "geotiff",
        file_path=artifact.path,
        size_bytes=artifact.size_bytes,
        checksum=artifact.checksum,
        metadata_json=metadata_json,
        provenance_json=provenance_json,
        quality_flag="UNVALIDATED",
        quality_reason="raw ingested observation - quality flags are produced by processing runs",
        created_by_id=actor.id if actor else None,
    )
    db.add(dataset)
    db.flush()
    return dataset


def run_ingestion(
    db: Session,
    *,
    ing: IngestionJob,
    job_id: int | None = None,
    actor: User | None = None,
    progress=None,
) -> dict[str, Any]:
    """Execute an ingestion job.  ``progress`` receives (fraction, message)."""
    ds = ing.data_source
    sa = ing.study_area
    adapter = _adapter_for(ds)
    cfg = dict(ds.ingestion_config_json or {})
    variables = list(ing.variables_json or []) if isinstance(ing.variables_json, list) else []

    def report(fraction: float, message: str = "") -> None:
        if progress:
            progress(max(0.0, min(1.0, fraction)), message)

    bbox = (sa.minx, sa.miny, sa.maxx, sa.maxy)
    dest_root = new_workspace("raw")
    params = IngestParams(
        bbox=bbox,
        start_date=ing.start_date,
        end_date=ing.end_date,
        variables=variables,
        study_area_id=sa.id,
        dest_dir=dest_root,
        max_items=int(cfg.get("max_items") or 60),
        extra={
            "max_dim": int(cfg.get("max_dim") or 2048),
            "ingestion_config": cfg,
        },
    )

    report(0.02, "discovering items")
    try:
        items = adapter.discover(params)
    except ProviderError as exc:
        data_sources_service.record_ingestion_outcome(db, ds=ds, ok=False, error=str(exc))
        db.commit()
        raise
    ing.discovered_count = len(items)
    db.flush()
    db.commit()
    if not items:
        data_sources_service.record_ingestion_outcome(
            db, ds=ds, ok=False, error="no items discovered for the requested selection"
        )
        db.commit()
        raise ProviderError(
            "No items discovered for the requested date range/study area "
            "(try a wider range or check the data source configuration)"
        )

    dataset_ids: list[int] = []
    errors: list[dict[str, str]] = []
    n = len(items)
    for idx, item in enumerate(items):
        base = 0.05 + 0.9 * (idx / n)
        span = 0.9 / n
        params.dest_dir = dest_root / f"{idx:03d}_{_slug(item.asset_id)}"

        def sub_progress(fraction: float, message: str = "", _base=base, _span=span) -> None:
            report(_base + _span * max(0.0, min(1.0, fraction)), message)

        try:
            artifact = adapter.fetch(params, item, sub_progress)
            dataset = _record_dataset(db, ing=ing, ds=ds, sa=sa, adapter=adapter, artifact=artifact, actor=actor)
            dataset_ids.append(dataset.id)
            ing.stored_count = len(dataset_ids)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - per-item boundary, job continues
            db.rollback()
            log.warning("Ingestion item %s failed: %s", item.asset_id, exc)
            errors.append({"item": item.asset_id, "error": f"{type(exc).__name__}: {exc}"[:600]})
            if params.dest_dir is not None:
                import shutil

                shutil.rmtree(params.dest_dir, ignore_errors=True)
            report(base + span, f"item failed: {item.asset_id}")

    ok = bool(dataset_ids)
    data_sources_service.record_ingestion_outcome(
        db,
        ds=ds,
        ok=ok,
        error=None if ok else (errors[0]["error"] if errors else "no datasets stored"),
    )
    db.commit()

    result = {
        "discovered": ing.discovered_count,
        "stored": len(dataset_ids),
        "failed": len(errors),
        "dataset_ids": dataset_ids,
        "errors": errors[:20],
        "data_source_id": ds.id,
        "study_area_id": sa.id,
        "date_range": [ing.start_date.isoformat(), ing.end_date.isoformat()],
    }
    if not ok:
        raise ProviderError(
            f"Ingestion stored no datasets ({len(errors)} item error(s)); first error: "
            f"{errors[0]['error'] if errors else 'unknown'}"
        )
    report(1.0, f"stored {len(dataset_ids)} dataset(s)")
    return result


@register_handler("ingestion")
def handle_ingestion_job(ctx: JobContext) -> dict:
    ing = ctx.db.execute(
        select(IngestionJob).where(IngestionJob.job_id == ctx.job.id)
    ).scalar_one_or_none()
    if ing is None:
        raise UnprocessableError("Ingestion record for this job is missing")
    return run_ingestion(ctx.db, ing=ing, job_id=ctx.job.id, actor=ctx.actor, progress=ctx.progress)

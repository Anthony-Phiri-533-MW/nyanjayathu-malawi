"""Export jobs: CSV / JSON / GeoJSON tables and GeoTIFF copies.

Exports are asynchronous (one ``ExportJob`` row per queued job) and always
written below the storage ``exports`` area.  Raster exports copy the stored
GeoTIFF unchanged; tabular exports contain the documented result/metadata
columns used by the UI.
"""
from __future__ import annotations

import csv
import json
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import count_query
from app.core.errors import NotFoundError, UnprocessableError
from app.models import DataProduct, Dataset, ExportJob, IndicatorResult, User
from app.schemas.research import ComparisonCreate, ExportCreate, PeriodWindow
from app.services import analysis
from app.services import audit as audit_service
from app.services import datasets as datasets_service
from app.services.jobs import JobContext, enqueue, register_handler
from app.services.storage import (
    file_checksum,
    new_workspace,
    relative,
    resolve_stored_file,
    sanitize_filename,
)

EXPORT_RESOURCES = ("datasets", "indicator_results", "timeseries", "comparison", "raster")
EXPORT_FORMATS = ("csv", "json", "geojson", "geotiff")
EXTENSIONS = {"csv": "csv", "json": "json", "geojson": "geojson", "geotiff": "tif"}


def _iso(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def start_export(db: Session, *, payload: ExportCreate, actor: User) -> tuple[Any, ExportJob]:
    filters = dict(payload.filters or {})
    if payload.resource == "timeseries" and not filters.get("indicator_key"):
        raise UnprocessableError("timeseries exports require filters.indicator_key")
    if payload.resource == "comparison":
        for key in ("study_area_id", "indicator_keys", "period_a", "period_b"):
            if not filters.get(key):
                raise UnprocessableError(
                    f"comparison exports require filters.{key}"
                )
    if payload.resource == "raster" and not (filters.get("dataset_id") or filters.get("product_id")):
        raise UnprocessableError(
            "raster exports require filters.dataset_id or filters.product_id"
        )

    job = enqueue(
        db,
        kind="export",
        params={"resource": payload.resource, "format": payload.format, "filters": filters},
        requested_by_id=actor.id,
        dedupe_key=None,
    )
    db.flush()
    export = ExportJob(
        job_id=job.id,
        format=payload.format,
        resource_type=payload.resource,
        params_json={"filters": filters, "options": payload.options or {}},
        created_by_id=actor.id,
    )
    db.add(export)
    db.flush()
    audit_service.record(
        action="export.request",
        resource_type="export_job",
        resource_id=export.id,
        actor=actor,
        db=db,
        message=f"Requested {payload.format} export of {payload.resource}",
        details={"job_id": job.id, "filters": filters},
    )
    return job, export


def _as_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value)[:10])


# ------------------------------------------------------------------ renderers
def _write_csv(path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _iso(row.get(k)) for k in fields})


def _write_json(path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=_iso, ensure_ascii=False)


def _dataset_rows(db: Session, filters: dict[str, Any]) -> list[Dataset]:
    rows, _ = datasets_service.list_datasets(
        db,
        page=1,
        size=10_000,
        search=filters.get("search"),
        provider_key=filters.get("provider_key"),
        category=filters.get("category"),
        kind=filters.get("kind"),
        quality_flag=filters.get("quality_flag"),
        study_area_id=filters.get("study_area_id"),
        start_date=_as_date(filters.get("start_date")),
        end_date=_as_date(filters.get("end_date")),
    )
    return rows


def _dataset_dict(dataset: Dataset) -> dict[str, Any]:
    return {
        "id": dataset.id,
        "title": dataset.title,
        "provider_key": dataset.provider_key,
        "category": dataset.category,
        "product_type": dataset.product_type,
        "kind": dataset.kind,
        "is_raw": dataset.is_raw,
        "data_source_id": dataset.data_source_id,
        "study_area_id": dataset.study_area_id,
        "start_date": dataset.start_date,
        "end_date": dataset.end_date,
        "crs": dataset.crs,
        "resolution_m": dataset.resolution_m,
        "format": dataset.format,
        "size_bytes": dataset.size_bytes,
        "quality_flag": dataset.quality_flag,
        "quality_reason": dataset.quality_reason,
        "coverage_fraction": dataset.coverage_fraction,
        "created_at": dataset.created_at,
        "coverage_geojson": dataset.coverage_geojson,
    }


def _indicator_rows(db: Session, filters: dict[str, Any]) -> list[IndicatorResult]:
    stmt = select(IndicatorResult)
    if filters.get("indicator_key"):
        stmt = stmt.where(IndicatorResult.indicator_key == filters["indicator_key"])
    if filters.get("indicator_keys"):
        stmt = stmt.where(IndicatorResult.indicator_key.in_(filters["indicator_keys"]))
    if filters.get("study_area_id") is not None:
        stmt = stmt.where(IndicatorResult.study_area_id == filters["study_area_id"])
    if filters.get("dataset_id") is not None:
        stmt = stmt.where(IndicatorResult.dataset_id == filters["dataset_id"])
    if filters.get("quality_flag"):
        stmt = stmt.where(IndicatorResult.quality_flag == filters["quality_flag"])
    if _as_date(filters.get("start_date")):
        stmt = stmt.where(IndicatorResult.observed_end >= _as_date(filters["start_date"]))
    if _as_date(filters.get("end_date")):
        stmt = stmt.where(IndicatorResult.observed_start <= _as_date(filters["end_date"]))
    return list(
        db.execute(stmt.order_by(IndicatorResult.observed_start.asc(), IndicatorResult.id.asc())).scalars()
    )


def _indicator_dict(row: IndicatorResult) -> dict[str, Any]:
    return {
        "id": row.id,
        "indicator_key": row.indicator_key,
        "study_area_id": row.study_area_id,
        "dataset_id": row.dataset_id,
        "value": row.value,
        "unit": row.unit,
        "observed_start": row.observed_start,
        "observed_end": row.observed_end,
        "temporal_resolution": row.temporal_resolution,
        "quality_flag": row.quality_flag,
        "quality_reason": row.quality_reason,
        "coverage_fraction": row.coverage_fraction,
        "missing_fraction": row.missing_fraction,
        "created_at": row.created_at,
        "spatial_extent_geojson": row.spatial_extent_geojson,
    }


def _feature_collection(items: list[dict[str, Any]], geometry_key: str) -> dict[str, Any]:
    features = []
    for item in items:
        features.append(
            {
                "type": "Feature",
                "geometry": item.get(geometry_key),
                "properties": {
                    k: _iso(v) for k, v in item.items() if k != geometry_key
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


# ------------------------------------------------------------------ raster
def _raster_source(db: Session, filters: dict[str, Any]) -> tuple[Path, str]:
    if filters.get("product_id"):
        product = db.get(DataProduct, int(filters["product_id"]))
        if product is None:
            raise NotFoundError(f"Data product {filters['product_id']} not found")
        if (product.format or "").lower() not in ("geotiff", "tiff"):
            raise UnprocessableError(f"product {product.id} is not a GeoTIFF")
        return resolve_stored_file(product.file_path), product.name
    dataset = db.get(Dataset, int(filters["dataset_id"]))
    if dataset is None:
        raise NotFoundError(f"Dataset {filters['dataset_id']} not found")
    if (dataset.format or "").lower() not in ("geotiff", "tiff"):
        raise UnprocessableError(f"dataset {dataset.id} is not a GeoTIFF")
    granules = (dataset.metadata_json or {}).get("granules") or []
    for granule in granules:
        rel = granule.get("path") or next(iter((granule.get("bands") or {}).values()), None)
        if rel:
            return resolve_stored_file(str(rel)), dataset.title
    raise UnprocessableError(f"dataset {dataset.id} has no stored raster file")


def _product_band_stats(path, *, max_dim: int = 1024) -> dict[str, Any]:
    import rasterio

    with rasterio.open(path) as src:
        scale = min(1.0, max_dim / max(src.height, src.width))
        out_shape = (max(1, int(src.height * scale)), max(1, int(src.width * scale)))
        data = src.read(masked=True, out_shape=out_shape, resampling=rasterio.enums.Resampling.average)
        descriptions = list(src.descriptions)
        bands = {}
        for idx in range(src.count):
            arr = np.ma.filled(data[idx].astype("float64"), np.nan)
            name = descriptions[idx] or f"band_{idx + 1}"
            bands[name] = datasets_service._band_stats(arr)
        return {
            "applicable": True,
            "crs": src.crs.to_string() if src.crs else None,
            "bounds": list(src.bounds),
            "max_dim": max_dim,
            "bands": bands,
        }


def run_export(
    db: Session,
    *,
    export: ExportJob,
    job_id: int | None = None,
    actor: User | None = None,
    progress=None,
) -> dict[str, Any]:
    params = export.params_json or {}
    filters = dict(params.get("filters") or {})
    fmt = export.format
    resource = export.resource_type
    if fmt not in EXPORT_FORMATS:
        raise UnprocessableError(f"unsupported export format '{fmt}'")

    workdir = new_workspace("exports")
    stem = sanitize_filename(f"{resource}_{datetime.now(UTC):%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}")
    path = workdir / f"{stem}.{EXTENSIONS[fmt]}"
    if progress:
        progress(0.1, f"preparing {resource} export")

    row_count = 0
    if resource == "datasets":
        records = [_dataset_dict(d) for d in _dataset_rows(db, filters)]
        if fmt == "csv":
            fields = [
                "id", "title", "provider_key", "category", "product_type", "kind", "is_raw",
                "data_source_id", "study_area_id", "start_date", "end_date", "crs",
                "resolution_m", "format", "size_bytes", "quality_flag", "quality_reason",
                "coverage_fraction", "created_at",
            ]
            _write_csv(path, records, fields)
        elif fmt == "geojson":
            _write_json(path, _feature_collection(records, "coverage_geojson"))
        else:
            _write_json(path, records)
        row_count = len(records)

    elif resource == "indicator_results":
        records = [_indicator_dict(r) for r in _indicator_rows(db, filters)]
        if fmt == "csv":
            fields = [
                "id", "indicator_key", "study_area_id", "dataset_id", "value", "unit",
                "observed_start", "observed_end", "temporal_resolution", "quality_flag",
                "quality_reason", "coverage_fraction", "missing_fraction", "created_at",
            ]
            _write_csv(path, records, fields)
        elif fmt == "geojson":
            _write_json(path, _feature_collection(records, "spatial_extent_geojson"))
        else:
            _write_json(path, records)
        row_count = len(records)

    elif resource == "timeseries":
        series = analysis.build_timeseries(
            db,
            indicator_key=str(filters["indicator_key"]),
            study_area_id=filters.get("study_area_id"),
            dataset_ids=filters.get("dataset_ids"),
            start=_as_date(filters.get("start_date")),
            end=_as_date(filters.get("end_date")),
            aggregation=str(filters.get("aggregation") or "raw"),
        )
        points = [
            {
                "date": p["date"],
                "value": p["value"],
                "unit": p["unit"],
                "quality_flag": p["quality_flag"],
                "quality_reason": p["quality_reason"],
                "dataset_title": p["dataset_title"],
                "coverage_fraction": p["coverage_fraction"],
            }
            for p in series["points"]
        ]
        if fmt == "csv":
            _write_csv(
                path,
                points,
                ["date", "value", "unit", "quality_flag", "quality_reason", "dataset_title", "coverage_fraction"],
            )
        elif fmt == "geojson":
            _write_json(path, _feature_collection(points, "geometry"))
        else:
            _write_json(path, series)
        row_count = len(points)

    elif resource == "comparison":
        payload = ComparisonCreate(
            study_area_id=int(filters["study_area_id"]),
            indicator_keys=list(filters["indicator_keys"]),
            period_a=PeriodWindow(**filters["period_a"]),
            period_b=PeriodWindow(**filters["period_b"]),
            dataset_ids=filters.get("dataset_ids"),
            aggregation=str(filters.get("aggregation") or "mean"),
        )
        comparison = analysis.compare_periods(db, payload)
        if fmt == "csv":
            rows = []
            for entry in comparison["entries"]:
                rows.append(
                    {
                        "indicator_key": entry["indicator_key"],
                        "indicator_name": entry["indicator_name"],
                        "unit": entry["unit"],
                        "aggregation": entry["aggregation"],
                        "a_value": entry["a"]["value"],
                        "a_quality": entry["a"]["quality_flag"],
                        "a_samples": entry["a"]["sample_count"],
                        "b_value": entry["b"]["value"],
                        "b_quality": entry["b"]["quality_flag"],
                        "b_samples": entry["b"]["sample_count"],
                        "delta": entry["delta"],
                        "delta_percent": entry["delta_percent"],
                        "compatible": entry["compatible"],
                        "notes": entry["notes"],
                    }
                )
            _write_csv(
                path,
                rows,
                [
                    "indicator_key", "indicator_name", "unit", "aggregation", "a_value",
                    "a_quality", "a_samples", "b_value", "b_quality", "b_samples",
                    "delta", "delta_percent", "compatible", "notes",
                ],
            )
        elif fmt == "geojson":
            _write_json(path, _feature_collection(comparison["entries"], "geometry"))
        else:
            _write_json(path, comparison)
        row_count = len(comparison["entries"])

    elif resource == "raster":
        source, name = _raster_source(db, filters)
        if fmt == "geotiff":
            import shutil

            shutil.copyfile(source, path)
            row_count = 1
        else:
            stats = _product_band_stats(source)
            _write_json(
                path,
                {
                    "source": name,
                    "checksum_sha256": file_checksum(source),
                    "statistics": stats,
                },
            )
            row_count = len(stats.get("bands") or {})
    else:
        raise UnprocessableError(f"unsupported export resource '{resource}'")

    if not path.exists():
        raise UnprocessableError("export produced no file")
    export.file_path = relative(path)
    export.file_name = path.name
    export.size_bytes = path.stat().st_size
    db.flush()
    if progress:
        progress(1.0, "export written")
    audit_service.record(
        action="export.complete",
        resource_type="export_job",
        resource_id=export.id,
        actor=actor,
        db=db,
        message=f"{resource} {fmt} export written ({row_count} record(s))",
        details={"file": export.file_name, "size_bytes": export.size_bytes},
    )
    return {
        "export_id": export.id,
        "resource": resource,
        "format": fmt,
        "file_name": export.file_name,
        "size_bytes": export.size_bytes,
        "records": row_count,
    }


@register_handler("export")
def handle_export_job(ctx: JobContext) -> dict:
    export = ctx.db.execute(
        select(ExportJob).where(ExportJob.job_id == ctx.job.id)
    ).scalar_one_or_none()
    if export is None:
        raise UnprocessableError("Export record for this job is missing")
    return run_export(
        ctx.db, export=export, job_id=ctx.job.id, actor=ctx.actor, progress=ctx.progress
    )


def get_export(db: Session, export_id: int) -> ExportJob:
    export = db.get(ExportJob, export_id)
    if export is None:
        raise NotFoundError(f"Export {export_id} not found")
    return export


def list_exports(db: Session, *, page: int = 1, size: int = 20) -> tuple[list[ExportJob], int]:

    stmt = select(ExportJob)
    total = count_query(stmt, db)
    rows = list(
        db.execute(
            stmt.order_by(ExportJob.created_at.desc(), ExportJob.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        ).scalars()
    )
    return rows, total

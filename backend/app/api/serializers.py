"""ORM -> response-schema serialisers and small pagination helpers.

The ORM uses ``*_json`` columns and relationships that are not part of the
public contract, so every endpoint goes through one of these functions rather
than relying on ``from_attributes`` alone.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from app.schemas.admin import (
    AuditEventOut,
    DataSourceOut,
    ThresholdOut,
    ThresholdVersionOut,
)
from app.schemas.common import Page
from app.schemas.disaster import (
    AlertDetailOut,
    AlertOut,
    AlertResponseOut,
    ForecastOut,
)
from app.schemas.public import PublicAlertOut, PublicDatasetOut
from app.schemas.report import ReportOut
from app.schemas.research import (
    BandOut,
    DatasetDetailOut,
    DatasetOut,
    ExportOut,
    IndicatorResultOut,
    IngestionJobOut,
    JobOut,
    ProcessingRunOut,
    ProviderOut,
    QualityAssessmentOut,
    StudyAreaOut,
)


def page_response(items: Iterable[Any], total: int, page: int, size: int) -> Page:
    return Page(
        items=list(items),
        total=total,
        page=page,
        size=size,
        pages=max(1, math.ceil(total / size)) if size else 1,
    )


# --------------------------------------------------------------------- jobs
def job_out(job) -> JobOut:
    return JobOut(
        id=job.id,
        kind=job.kind,
        status=job.status,
        progress=job.progress,
        message=job.message,
        params=job.params_json,
        result=job.result_json,
        error=job.error,
        attempts=job.attempts,
        requested_by_id=job.requested_by_id,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


# --------------------------------------------------------------- study areas
def study_area_out(area) -> StudyAreaOut:
    return StudyAreaOut(
        id=area.id,
        name=area.name,
        description=area.description,
        boundary_geojson=area.boundary_geojson,
        minx=area.minx,
        miny=area.miny,
        maxx=area.maxx,
        maxy=area.maxy,
        is_default=area.is_default,
        is_public=area.is_public,
    )


# ------------------------------------------------------------------ datasets
def _bands(dataset) -> list[BandOut]:
    raw = dataset.bands_json or []
    if isinstance(raw, dict):
        raw = [
            {"key": key, **(value if isinstance(value, dict) else {})}
            for key, value in raw.items()
        ]
    bands: list[BandOut] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("key"):
            continue
        bands.append(
            BandOut(
                key=str(item["key"]),
                label=str(item.get("label") or ""),
                unit=str(item.get("unit") or ""),
                scale=float(item.get("scale") or 1.0),
                offset=float(item.get("offset") or 0.0),
                wavelength_nm=item.get("wavelength_nm"),
                description=str(item.get("description") or ""),
            )
        )
    return bands


def dataset_out(dataset, *, data_source_name: str | None = None, study_area_name: str | None = None) -> DatasetOut:
    if data_source_name is None and getattr(dataset, "data_source", None) is not None:
        data_source_name = dataset.data_source.name
    if study_area_name is None and getattr(dataset, "study_area", None) is not None:
        study_area_name = dataset.study_area.name
    return DatasetOut(
        id=dataset.id,
        title=dataset.title,
        provider_key=dataset.provider_key,
        category=dataset.category,
        product_type=dataset.product_type,
        kind=dataset.kind,
        is_raw=dataset.is_raw,
        is_public=dataset.is_public,
        data_source_id=dataset.data_source_id,
        data_source_name=data_source_name,
        ingestion_job_id=dataset.ingestion_job_id,
        study_area_id=dataset.study_area_id,
        study_area_name=study_area_name,
        start_date=dataset.start_date,
        end_date=dataset.end_date,
        crs=dataset.crs,
        resolution_m=dataset.resolution_m,
        bands=_bands(dataset),
        coverage_geojson=dataset.coverage_geojson,
        format=dataset.format,
        size_bytes=dataset.size_bytes,
        quality_flag=dataset.quality_flag,
        quality_reason=dataset.quality_reason,
        coverage_fraction=dataset.coverage_fraction,
        created_at=dataset.created_at,
    )


def quality_assessment_out(row) -> QualityAssessmentOut:
    return QualityAssessmentOut(
        id=row.id,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        rule_version=row.rule_version,
        flag=row.flag,
        reason=row.reason,
        coverage_fraction=row.coverage_fraction,
        missing_fraction=row.missing_fraction,
        cloud_fraction=row.cloud_fraction,
        details=row.details_json,
        created_at=row.created_at,
    )


def dataset_detail_out(
    dataset,
    *,
    assessments: list,
    indicator_result_count: int,
    band_statistics: dict | None = None,
) -> DatasetDetailOut:
    base = dataset_out(dataset)
    return DatasetDetailOut(
        **base.model_dump(),
        metadata=dataset.metadata_json,
        provenance=dataset.provenance_json,
        checksum=dataset.checksum,
        quality_assessments=[quality_assessment_out(a) for a in assessments],
        indicator_result_count=indicator_result_count,
        band_statistics=band_statistics,
    )


# ------------------------------------------------------------ ingestion jobs
def ingestion_job_out(ing) -> IngestionJobOut:
    return IngestionJobOut(
        id=ing.id,
        job_id=ing.job_id,
        data_source_id=ing.data_source_id,
        data_source_name=ing.data_source.name if ing.data_source else None,
        study_area_id=ing.study_area_id,
        study_area_name=ing.study_area.name if ing.study_area else None,
        start_date=ing.start_date,
        end_date=ing.end_date,
        variables=ing.variables_json,
        discovered_count=ing.discovered_count,
        stored_count=ing.stored_count,
        created_at=ing.created_at,
        job=job_out(ing.job) if ing.job else None,
    )


# ----------------------------------------------------------- processing runs
def processing_run_out(run) -> ProcessingRunOut:
    return ProcessingRunOut(
        id=run.id,
        operation=run.operation,
        params=run.params_json,
        algorithm_version=run.algorithm_version,
        input_dataset_ids=run.input_dataset_ids_json,
        job_id=run.job_id,
        status=run.status,
        metrics=run.metrics_json,
        error=run.error,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        products=[
            {
                "id": p.id,
                "kind": p.kind,
                "name": p.name,
                "format": p.format,
                "crs": p.crs,
                "resolution_m": p.resolution_m,
                "size_bytes": p.size_bytes,
                "quality_flag": p.quality_flag,
                "created_at": p.created_at,
            }
            for p in (run.products or [])
        ],
    )


# --------------------------------------------------------------- indicators
def indicator_result_out(
    row,
    *,
    study_area_name: str | None = None,
    dataset_title: str | None = None,
) -> IndicatorResultOut:
    return IndicatorResultOut(
        id=row.id,
        definition_id=row.definition_id,
        indicator_key=row.indicator_key,
        study_area_id=row.study_area_id,
        study_area_name=study_area_name,
        dataset_id=row.dataset_id,
        dataset_title=dataset_title,
        product_id=row.product_id,
        job_id=row.job_id,
        value=row.value,
        unit=row.unit,
        observed_start=row.observed_start,
        observed_end=row.observed_end,
        temporal_resolution=row.temporal_resolution,
        spatial_resolution=row.spatial_resolution,
        quality_flag=row.quality_flag,
        quality_reason=row.quality_reason,
        flag_reasons=row.flag_reasons_json,
        coverage_fraction=row.coverage_fraction,
        missing_fraction=row.missing_fraction,
        uncertainty=row.uncertainty_json,
        provenance=row.provenance_json,
        parameters=row.parameters_json,
        created_at=row.created_at,
    )


# ------------------------------------------------------------------ exports
def export_out(export) -> ExportOut:
    return ExportOut(
        id=export.id,
        job_id=export.job_id,
        format=export.format,
        resource_type=export.resource_type,
        params=export.params_json,
        file_name=export.file_name,
        size_bytes=export.size_bytes,
        created_by_id=export.created_by_id,
        created_at=export.created_at,
        job=job_out(export.job) if export.job else None,
        download_url=(
            f"/api/v1/exports/{export.id}/download" if export.file_path and export.file_name else None
        ),
    )


# -------------------------------------------------------------- data sources
def data_source_out(source, *, dataset_count: int = 0) -> DataSourceOut:
    return DataSourceOut(
        id=source.id,
        name=source.name,
        provider_key=source.provider_key,
        category=source.category,
        dataset_name=source.dataset_name,
        dataset_identifier=source.dataset_identifier,
        description=source.description,
        is_enabled=source.is_enabled,
        coverage_geojson=source.coverage_geojson,
        temporal_start=source.temporal_start,
        temporal_end=source.temporal_end,
        variables=source.variables_json,
        ingestion_config=source.ingestion_config_json,
        auth_method=source.auth_method,
        credential_ref=source.credential_ref,
        status=source.status,
        last_test_at=source.last_test_at,
        last_test_status=source.last_test_status,
        last_test_message=source.last_test_message,
        last_ingestion_attempt_at=source.last_ingestion_attempt_at,
        last_success_at=source.last_success_at,
        error_status=source.error_status,
        error_detail=source.error_detail,
        dataset_count=dataset_count,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


# ---------------------------------------------------------------- thresholds
def threshold_out(t) -> ThresholdOut:
    return ThresholdOut(
        id=t.id,
        indicator_key=t.indicator_key,
        indicator_name=t.indicator_name,
        unit=t.unit,
        operator=t.operator,
        value_low=t.value_low,
        value_high=t.value_high,
        description=t.description,
        justification=t.justification,
        reference=t.reference,
        approval_status=t.approval_status,
        effective_from=t.effective_from,
        effective_to=t.effective_to,
        is_enabled=t.is_enabled,
        version=t.version,
        created_at=t.created_at,
        updated_at=t.updated_at,
        is_provisional=t.approval_status != "approved",
    )


def threshold_version_out(v) -> ThresholdVersionOut:
    return ThresholdVersionOut(
        id=v.id,
        version=v.version,
        change_note=v.change_note,
        changed_by_email=v.changed_by_email,
        created_at=v.created_at,
        snapshot=v.snapshot_json,
    )


# --------------------------------------------------------------------- audit
def audit_event_out(row) -> AuditEventOut:
    return AuditEventOut(
        id=row.id,
        created_at=row.created_at,
        actor_id=row.actor_id,
        actor_email=row.actor_email,
        action=row.action,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        outcome=row.outcome,
        ip_address=row.ip_address,
        request_id=row.request_id,
        message=row.message,
        details=row.details_json,
    )


# ----------------------------------------------------------------- providers
def provider_out(raw: dict) -> ProviderOut:
    return ProviderOut(
        key=raw["key"],
        label=raw["label"],
        category=raw["category"],
        description=raw.get("description", ""),
        product_type=raw.get("product_type", ""),
        verification_note=raw.get("verification_note", ""),
        auth_method=raw.get("auth_method", "none"),
        auth_required=bool(raw.get("auth_required", False)),
        variables=list(raw.get("variables") or []),
        capabilities=dict(raw.get("capabilities") or {}),
        adapter_status=raw.get("adapter_status", "untested"),
    )

# --------------------------------------------------------------------- disaster
def _user_email(user) -> str | None:
    return user.email if user is not None else None


def forecast_out(row) -> ForecastOut:
    return ForecastOut(
        id=row.id,
        study_area_id=row.study_area_id,
        study_area_name=row.study_area.name if row.study_area is not None else None,
        indicator_key=row.indicator_key,
        target_date=row.target_date,
        value=row.value,
        unit=row.unit,
        note=row.note,
        created_at=row.created_at,
        created_by_email=_user_email(row.created_by),
    )


def alert_out(a) -> AlertOut:
    return AlertOut(
        id=a.id,
        study_area_id=a.study_area_id,
        study_area_name=a.study_area.name if a.study_area is not None else None,
        indicator_key=a.indicator_key,
        indicator_name=a.indicator_name,
        threshold_id=a.threshold_id,
        threshold_snapshot=a.threshold_snapshot_json,
        metric_source=a.metric_source,
        metric_value=a.metric_value,
        metric_date=a.metric_date,
        unit=a.unit,
        kind=a.kind,
        severity=a.severity,
        status=a.status,
        is_public=a.is_public,
        message=a.message,
        first_seen_at=a.first_seen_at,
        last_evaluated_at=a.last_evaluated_at,
        times_seen=a.times_seen,
        acknowledged_at=a.acknowledged_at,
        acknowledged_by_email=_user_email(a.acknowledged_by) if a.acknowledged_by_id else None,
        resolved_at=a.resolved_at,
        resolved_by_email=_user_email(a.resolved_by) if a.resolved_by_id else None,
        created_at=a.created_at,
    )


def alert_response_out(r) -> AlertResponseOut:
    return AlertResponseOut(
        id=r.id,
        response_type=r.response_type,
        note=r.note,
        actor_email=_user_email(r.actor),
        created_at=r.created_at,
    )


def alert_detail_out(a) -> AlertDetailOut:
    base = alert_out(a)
    return AlertDetailOut(
        **base.model_dump(),
        responses=[alert_response_out(r) for r in a.responses],
    )

# --------------------------------------------------------------------- reports
def report_out(report) -> ReportOut:
    return ReportOut(
        id=report.id,
        job_id=report.job_id,
        title=report.title,
        kind=report.kind,
        period_type=report.period_type,
        period_start=report.period_start,
        period_end=report.period_end,
        study_area_id=report.study_area_id,
        study_area_name=report.study_area.name if report.study_area is not None else None,
        format=report.format,
        status=report.status,
        error=report.error,
        file_name=report.file_name,
        size_bytes=report.size_bytes,
        download_url=(
            f"/api/v1/reports/{report.id}/download"
            if report.status == "completed" and report.file_path and report.file_name
            else None
        ),
        created_by_email=report.created_by.email if report.created_by is not None else None,
        created_at=report.created_at,
        completed_at=report.completed_at,
        job_status=report.job.status if report.job is not None else None,
    )

# ---------------------------------------------------------------------- public
def public_dataset_out(dataset) -> PublicDatasetOut:
    return PublicDatasetOut(
        id=dataset.id,
        title=dataset.title,
        provider_key=dataset.provider_key,
        category=dataset.category,
        product_type=dataset.product_type,
        kind=dataset.kind,
        is_raw=dataset.is_raw,
        start_date=dataset.start_date,
        end_date=dataset.end_date,
        crs=dataset.crs,
        resolution_m=dataset.resolution_m,
        format=dataset.format,
        size_bytes=dataset.size_bytes,
        quality_flag=dataset.quality_flag,
        quality_reason=dataset.quality_reason,
        coverage_fraction=dataset.coverage_fraction,
        study_area_id=dataset.study_area_id,
        study_area_name=public_area_name(dataset.study_area),
        created_at=dataset.created_at,
    )


def public_area_name(area) -> str | None:
    """The name of a study area is public only when the area is published."""
    return area.name if area is not None and area.is_public else None


def public_alert_out(alert) -> PublicAlertOut:
    return PublicAlertOut(
        id=alert.id,
        kind=alert.kind,
        severity=alert.severity,
        status=alert.status,
        message=alert.message,
        indicator_key=alert.indicator_key,
        indicator_name=alert.indicator_name,
        metric_source=alert.metric_source,
        metric_value=alert.metric_value,
        metric_date=alert.metric_date,
        unit=alert.unit,
        times_seen=alert.times_seen,
        first_seen_at=alert.first_seen_at,
        last_evaluated_at=alert.last_evaluated_at,
        study_area_id=alert.study_area_id,
        study_area_name=public_area_name(alert.study_area),
    )

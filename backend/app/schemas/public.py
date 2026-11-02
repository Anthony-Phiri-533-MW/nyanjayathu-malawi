"""Public Data module schemas.

The public endpoints are deliberately **read-only and minimum-necessary**:
they expose only the fields needed to inform the public about published
datasets, study areas and disaster alerts.  Internal references (file paths,
data-source configuration, threshold snapshots, staff attributions) are never
serialised here.
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class PublishFlag(BaseModel):
    """Body for the staff publish/unpublish toggles."""

    is_public: bool


class PublicDatasetOut(BaseModel):
    """Published-dataset listing: metadata only, no file/storage internals."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    provider_key: str
    category: str
    product_type: str
    kind: str
    is_raw: bool
    start_date: date | None = None
    end_date: date | None = None
    crs: str | None = None
    resolution_m: float | None = None
    format: str | None = None
    size_bytes: int | None = None
    quality_flag: str
    quality_reason: str
    coverage_fraction: float | None = None
    study_area_id: int | None = None
    study_area_name: str | None = None
    created_at: datetime


class PublicAlertOut(BaseModel):
    """Published alert: what happened, how severe, current status."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    severity: str
    status: str
    message: str
    indicator_key: str
    indicator_name: str
    metric_source: str
    metric_value: float
    metric_date: date | None = None
    unit: str
    times_seen: int
    first_seen_at: datetime
    last_evaluated_at: datetime
    study_area_id: int | None = None
    study_area_name: str | None = None


class PublicOverviewAlertTotals(BaseModel):
    by_severity: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    by_status: dict[str, int] = {}
    total: int = 0


class PublicOverviewOut(BaseModel):
    generated_at: datetime
    dataset_count: int
    study_area_count: int
    coverage_start: date | None = None
    coverage_end: date | None = None
    alerts: PublicOverviewAlertTotals
    provenance: str

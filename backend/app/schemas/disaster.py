"""Disaster Management module schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.enums import ALERT_KINDS, ALERT_SEVERITIES, AlertMetricSource


class ForecastCreate(BaseModel):
    """One projected value for an indicator at a study area on a target date."""

    model_config = ConfigDict(str_strip_whitespace=True)

    indicator_key: str = Field(min_length=3, max_length=80, pattern=r"^[a-z0-9_.\-]+$")
    study_area_id: int
    target_date: date
    value: float
    unit: str = Field(min_length=1, max_length=40)
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _note_required(self) -> ForecastCreate:
        # Forecast values are user-supplied, so provenance is mandatory: the
        # note must say where the value comes from (method/source/citation).
        if not self.note.strip():
            raise ValueError("A provenance note is required (source or method of the forecast)")
        return self


class ForecastOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    study_area_id: int
    study_area_name: str | None = None
    indicator_key: str
    target_date: date
    value: float
    unit: str
    note: str
    source: str = "manual"
    model_id: int | None = None
    model_name: str | None = None
    model_algorithm: str | None = None
    run_id: int | None = None
    lead_time_days: int = 0
    lower: float | None = None
    upper: float | None = None
    issued_at: datetime | None = None
    created_at: datetime
    created_by_email: str | None = None


class EvaluateRequest(BaseModel):
    """Run the threshold comparison engine.

    By default only *approved* thresholds are evaluated; ``include_provisional``
    extends the run to provisional ones (results are then labelled provisional
    in the alert message).  ``dry_run`` reports what would happen without
    creating or updating alerts.
    """

    study_area_ids: list[int] | None = Field(default=None, max_length=50)
    indicator_keys: list[str] | None = Field(default=None, max_length=50)
    include_provisional: bool = False
    dry_run: bool = False


class EvaluateMatch(BaseModel):
    """One (study area, threshold) pair the engine considered."""

    study_area_id: int
    study_area_name: str | None = None
    indicator_key: str
    threshold_id: int | None = None
    metric_source: AlertMetricSource
    metric_value: float | None = None
    metric_date: date | None = None
    breached: bool | None = None
    severity: str | None = None
    alert_id: int | None = None
    skipped_reason: str | None = None


class EvaluateOut(BaseModel):
    dry_run: bool
    include_provisional: bool
    thresholds_used: int
    pairs_considered: int
    pairs_skipped: int
    breached: int
    alerts_created: int
    alerts_updated: int
    matches: list[EvaluateMatch] = []


class AlertResponseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    response_type: str
    note: str
    actor_email: str | None = None
    created_at: datetime


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    study_area_id: int | None = None
    study_area_name: str | None = None
    indicator_key: str
    indicator_name: str
    threshold_id: int | None = None
    threshold_snapshot: dict | None = None
    metric_source: AlertMetricSource
    metric_value: float
    metric_date: date | None = None
    unit: str
    kind: str
    severity: str
    status: str
    is_public: bool
    message: str
    first_seen_at: datetime
    last_evaluated_at: datetime
    times_seen: int
    acknowledged_at: datetime | None = None
    acknowledged_by_email: str | None = None
    resolved_at: datetime | None = None
    resolved_by_email: str | None = None
    created_at: datetime


class AlertDetailOut(AlertOut):
    responses: list[AlertResponseOut] = []


class AlertActionCreate(BaseModel):
    """Body for acknowledge / note / resolve / reopen actions."""

    note: str = Field(default="", max_length=2000)
    severity: Literal["info", "warning", "critical"] | None = None
    kind: str | None = Field(default=None, pattern=r"^(flood|drought|water_quality|general)$")

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str | None) -> str | None:
        if v is not None and v not in {k for k, _ in ALERT_KINDS}:
            raise ValueError(f"kind must be one of {[k for k, _ in ALERT_KINDS]}")
        return v

    @field_validator("severity")
    @classmethod
    def _known_severity(cls, v: str | None) -> str | None:
        if v is not None and v not in {s for s, _ in ALERT_SEVERITIES}:
            raise ValueError(f"severity must be one of {[s for s, _ in ALERT_SEVERITIES]}")
        return v

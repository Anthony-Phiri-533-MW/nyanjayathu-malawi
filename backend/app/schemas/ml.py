"""Schemas for the forecasting module and the daily scheduler."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


# ------------------------------------------------------------------ forecasts
class ForecastRunRequest(BaseModel):
    """Trigger model training/validation.  Omit ids to use all configured areas."""

    study_area_ids: list[int] | None = Field(default=None, max_length=50)
    indicator_keys: list[str] | None = Field(default=None, max_length=50)
    horizon: int | None = Field(default=None, ge=1, le=60)
    enqueue: bool = True


class ForecastRunQueued(BaseModel):
    status: str
    job_id: int | None = None
    detail: dict | None = None


class MLModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    name: str
    algorithm: str
    version: str
    indicator_key: str
    study_area_id: int | None = None
    study_area_name: str | None = None
    cadence: str
    n_lags: int
    feature_names: list | dict | None = None
    params: dict | None = None
    train_start: date | None = None
    train_end: date | None = None
    n_train: int
    metrics: dict | None = None
    rmse: float | None = None
    mae: float | None = None
    bias: float | None = None
    skill_score: float | None = None
    artifact_sha256: str | None = None
    is_active: bool
    trained_at: datetime


class ModelEvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    model_id: int
    indicator_key: str
    study_area_id: int | None = None
    fold: int
    horizon_days: int
    train_start: date | None = None
    train_end: date | None = None
    test_start: date | None = None
    test_end: date | None = None
    n_train: int
    n_test: int
    rmse: float | None = None
    mae: float | None = None
    bias: float | None = None
    mape: float | None = None
    r2: float | None = None
    skill_score: float | None = None
    coverage: float | None = None
    metrics: dict | None = None


class ForecastRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    study_area_id: int
    study_area_name: str | None = None
    indicator_key: str
    model_id: int | None = None
    status: str
    horizon_days: int
    issued_at: datetime
    finished_at: datetime | None = None
    row_count: int
    message: str
    metrics: dict | None = None


class LocalModelFeatureOut(BaseModel):
    key: str
    label: str
    unit: str


class LocalModelOut(BaseModel):
    key: str
    name: str
    target: str
    unit: str
    features: list[LocalModelFeatureOut]
    metrics: dict[str, float] | None = None
    metrics_note: str
    ready: bool
    unavailable_reason: str | None = None


class LocalModelPredictionRequest(BaseModel):
    features: dict[str, float]


class LocalModelPredictionOut(BaseModel):
    model_key: str
    model_name: str
    target: str
    unit: str
    value: float
    features: dict[str, float]


# ------------------------------------------------------------------ scheduler
class SchedulerRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_date: date
    status: str
    trigger: str
    job_id: int | None = None
    started_at: datetime
    finished_at: datetime | None = None
    summary: dict | None = None
    error: str | None = None


class SchedulerStatusOut(BaseModel):
    enabled: bool
    jobs_enabled: bool
    scheduled_time_utc: str
    interval_seconds: float
    next_run_at: str
    due: bool
    scheduled_sources: int
    study_areas: int
    last_run: SchedulerRunOut | None = None


class SchedulerTriggerRequest(BaseModel):
    source_ids: list[int] | None = Field(default=None, max_length=100)
    study_area_ids: list[int] | None = Field(default=None, max_length=50)
    force: bool = False

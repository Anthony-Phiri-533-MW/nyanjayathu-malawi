"""Research-module schemas (discovery, jobs, indicators, comparison, exports)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# --- study areas ------------------------------------------------------------
class StudyAreaCreate(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    description: str = ""
    boundary_geojson: dict

    @field_validator("boundary_geojson")
    @classmethod
    def _geo(cls, v: dict) -> dict:
        if v.get("type") not in ("Polygon", "MultiPolygon"):
            raise ValueError("boundary_geojson must be a Polygon or MultiPolygon")
        return v


class StudyAreaUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = None
    boundary_geojson: dict | None = None

    @field_validator("boundary_geojson")
    @classmethod
    def _geo(cls, v: dict | None) -> dict | None:
        if v is not None and v.get("type") not in ("Polygon", "MultiPolygon"):
            raise ValueError("boundary_geojson must be a Polygon or MultiPolygon")
        return v


class StudyAreaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    boundary_geojson: dict
    minx: float
    miny: float
    maxx: float
    maxy: float
    is_default: bool
    is_public: bool


# --- provider metadata ------------------------------------------------------
class ProviderOut(BaseModel):
    key: str
    label: str
    category: str
    description: str
    product_type: str = ""
    verification_note: str = ""
    auth_method: str
    auth_required: bool
    variables: list[dict]
    capabilities: dict
    adapter_status: str   # tested | untested


# --- datasets ---------------------------------------------------------------
class BandOut(BaseModel):
    key: str
    label: str = ""
    unit: str = ""
    scale: float = 1.0
    offset: float = 0.0
    wavelength_nm: float | None = None
    description: str = ""


class QualityAssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subject_type: str
    subject_id: int
    rule_version: str
    flag: str
    reason: str
    coverage_fraction: float | None = None
    missing_fraction: float | None = None
    cloud_fraction: float | None = None
    details: dict | None = None
    created_at: datetime


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    provider_key: str
    category: str
    product_type: str
    kind: str
    is_raw: bool
    is_public: bool
    data_source_id: int | None = None
    data_source_name: str | None = None
    ingestion_job_id: int | None = None
    study_area_id: int | None = None
    study_area_name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    crs: str | None = None
    resolution_m: float | None = None
    bands: list[BandOut] = []
    coverage_geojson: dict | None = None
    format: str | None = None
    size_bytes: int | None = None
    quality_flag: str
    quality_reason: str
    coverage_fraction: float | None = None
    created_at: datetime


class DatasetDetailOut(DatasetOut):
    metadata: dict | None = None
    provenance: dict | None = None
    checksum: str | None = None
    quality_assessments: list[QualityAssessmentOut] = []
    indicator_result_count: int = 0
    band_statistics: dict | None = None   # descriptive statistics (band -> {count,min,max,mean,...})


# --- jobs -------------------------------------------------------------------
class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    status: str
    progress: float
    message: str
    params: dict | None = None
    result: dict | None = None
    error: str | None = None
    attempts: int
    requested_by_id: int | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class IngestionJobCreate(BaseModel):
    data_source_id: int
    study_area_id: int
    start_date: date
    end_date: date
    variables: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _range(self) -> IngestionJobCreate:
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        if (self.end_date - self.start_date).days > 1200:
            raise ValueError("date range must not exceed 1200 days per job")
        return self

    @field_validator("variables")
    @classmethod
    def _vars(cls, v: list[str]) -> list[str]:
        for item in v:
            if not item or len(item) > 80:
                raise ValueError("invalid variable key")
        return v


class IngestionJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int
    data_source_id: int
    data_source_name: str | None = None
    study_area_id: int
    study_area_name: str | None = None
    start_date: date
    end_date: date
    variables: list | dict | None = None
    discovered_count: int
    stored_count: int
    created_at: datetime
    job: JobOut | None = None


class ProcessingRunCreate(BaseModel):
    dataset_ids: list[int] = Field(min_length=1, max_length=50)
    operations: list[str] = Field(min_length=1, max_length=10)
    params: dict = Field(default_factory=dict)
    output_name: str = Field(default="", max_length=300)

    @field_validator("operations")
    @classmethod
    def _ops(cls, v: list[str]) -> list[str]:
        from app.processing.registry import PROCESSING_OPERATIONS

        unknown = [o for o in v if o not in PROCESSING_OPERATIONS]
        if unknown:
            raise ValueError(f"Unknown operations: {', '.join(unknown)}; allowed: {sorted(PROCESSING_OPERATIONS)}")
        return v


class ProcessingRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    operation: str
    params: dict | None = None
    algorithm_version: str
    input_dataset_ids: list | None = None
    job_id: int | None = None
    status: str
    metrics: dict | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    products: list[dict] = []


class IndicatorComputeCreate(BaseModel):
    indicator_keys: list[str] = Field(min_length=1, max_length=10)
    study_area_id: int | None = None
    dataset_ids: list[int] | None = Field(default=None, max_length=50)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def _selection(self) -> IndicatorComputeCreate:
        if not self.dataset_ids and self.start_date and not self.end_date:
            raise ValueError("end_date is required when start_date is provided")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        if not self.dataset_ids and not self.study_area_id:
            raise ValueError("supply dataset_ids or a study_area_id")
        return self


# --- indicators -------------------------------------------------------------
class IndicatorDefinitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    key: str
    name: str
    category: str
    description: str
    definition: str
    unit: str
    method: str
    method_version: str
    is_proxy: bool
    is_enabled: bool
    params: dict | None = None


class IndicatorResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    definition_id: int
    indicator_key: str
    study_area_id: int | None = None
    study_area_name: str | None = None
    dataset_id: int | None = None
    dataset_title: str | None = None
    product_id: int | None = None
    job_id: int | None = None
    value: float | None = None
    unit: str
    observed_start: date
    observed_end: date
    temporal_resolution: str
    spatial_resolution: str
    quality_flag: str
    quality_reason: str
    flag_reasons: list | dict | None = None
    coverage_fraction: float | None = None
    missing_fraction: float | None = None
    uncertainty: dict | None = None
    provenance: dict | None = None
    parameters: dict | None = None
    created_at: datetime


class TimeSeriesPoint(BaseModel):
    date: date
    value: float | None = None
    unit: str
    quality_flag: str
    quality_reason: str = ""
    result_id: int | None = None
    dataset_id: int | None = None
    dataset_title: str | None = None
    coverage_fraction: float | None = None


class TimeSeriesOut(BaseModel):
    indicator_key: str
    indicator_name: str
    unit: str
    study_area_id: int | None = None
    aggregation: str
    date_from: date | None = None
    date_to: date | None = None
    points: list[TimeSeriesPoint]
    excluded_points: int = 0   # points omitted because of MISSING_DATA / PROCESSING_FAILED
    limitations: str = ""


# --- comparison -------------------------------------------------------------
class PeriodWindow(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def _order(self) -> PeriodWindow:
        if self.start > self.end:
            raise ValueError("start must be on or before end")
        return self


class ComparisonCreate(BaseModel):
    study_area_id: int
    indicator_keys: list[str] = Field(min_length=1, max_length=10)
    period_a: PeriodWindow
    period_b: PeriodWindow
    dataset_ids: list[int] | None = Field(default=None, max_length=50)
    aggregation: str = "mean"

    @field_validator("aggregation")
    @classmethod
    def _agg(cls, v: str) -> str:
        if v not in ("mean", "median", "min", "max", "sum"):
            raise ValueError("aggregation must be mean|median|min|max|sum")
        return v


class ComparisonSide(BaseModel):
    period: PeriodWindow
    value: float | None = None
    unit: str
    quality_flag: str
    quality_reason: str = ""
    sample_count: int = 0
    excluded_count: int = 0
    points: list[TimeSeriesPoint] = []


class ComparisonEntry(BaseModel):
    indicator_key: str
    indicator_name: str
    unit: str
    aggregation: str
    a: ComparisonSide
    b: ComparisonSide
    delta: float | None = None
    delta_percent: float | None = None
    compatible: bool = True
    notes: str = ""


class ComparisonOut(BaseModel):
    study_area_id: int
    study_area_name: str
    aggregation: str
    entries: list[ComparisonEntry]
    limitations: str = ""


# --- exports ----------------------------------------------------------------
class ExportCreate(BaseModel):
    resource: str          # datasets|indicator_results|timeseries|comparison|raster
    format: str            # csv|json|geojson|geotiff
    filters: dict = Field(default_factory=dict)
    options: dict = Field(default_factory=dict)

    @field_validator("resource")
    @classmethod
    def _res(cls, v: str) -> str:
        from app.core.enums import ExportResource

        if v not in ExportResource.__args__:
            raise ValueError(f"resource must be one of {ExportResource.__args__}")
        return v

    @field_validator("format")
    @classmethod
    def _fmt(cls, v: str) -> str:
        from app.core.enums import ExportFormat

        if v not in ExportFormat.__args__:
            raise ValueError(f"format must be one of {ExportFormat.__args__}")
        return v

    @model_validator(mode="after")
    def _compat(self) -> ExportCreate:
        if self.resource in ("datasets", "indicator_results", "timeseries", "comparison") and self.format == "geotiff":
            raise ValueError("GeoTIFF exports are available for resource 'raster'")
        if self.resource == "raster" and self.format not in ("geotiff", "json"):
            raise ValueError("raster exports support geotiff (and json for band statistics)")
        return self


class ExportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int
    format: str
    resource_type: str
    params: dict | None = None
    file_name: str | None = None
    size_bytes: int | None = None
    created_by_id: int | None = None
    created_at: datetime
    job: JobOut | None = None
    download_url: str | None = None

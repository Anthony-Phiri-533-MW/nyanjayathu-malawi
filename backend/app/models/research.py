"""Research-module persistence: study areas, datasets, processing, indicators,
quality assessments and exports."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, GeoJSONType, utcnow


class StudyArea(Base):
    __tablename__ = "study_areas"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    boundary_geojson: Mapped[dict] = mapped_column(GeoJSONType)   # Polygon / MultiPolygon, EPSG:4326
    minx: Mapped[float] = mapped_column(Float, index=True)
    miny: Mapped[float] = mapped_column(Float)
    maxx: Mapped[float] = mapped_column(Float, index=True)
    maxy: Mapped[float] = mapped_column(Float)
    is_default: Mapped[bool] = mapped_column(default=False)
    is_public: Mapped[bool] = mapped_column(default=False, index=True)  # shown on the public dashboard
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True)
    data_source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id", ondelete="CASCADE"), index=True)
    study_area_id: Mapped[int] = mapped_column(ForeignKey("study_areas.id", ondelete="CASCADE"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    variables_json: Mapped[list | dict | None] = mapped_column(GeoJSONType, nullable=True)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    stored_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    data_source: Mapped[DataSource] = relationship(lazy="selectin")  # noqa: F821
    study_area: Mapped[StudyArea] = relationship(lazy="selectin")
    job: Mapped[Job] = relationship(lazy="selectin")  # noqa: F821


class Dataset(Base):
    """Metadata for an observed or derived dataset (raw or processed)."""

    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    provider_key: Mapped[str] = mapped_column(String(60), index=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    product_type: Mapped[str] = mapped_column(String(80), default="")
    kind: Mapped[str] = mapped_column(String(20), default="observed", index=True)  # observed|composite|processed
    is_raw: Mapped[bool] = mapped_column(default=True)
    is_public: Mapped[bool] = mapped_column(default=False, index=True)  # shown on the public dashboard

    data_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ingestion_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingestion_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    study_area_id: Mapped[int | None] = mapped_column(
        ForeignKey("study_areas.id", ondelete="SET NULL"), nullable=True, index=True
    )

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    crs: Mapped[str | None] = mapped_column(String(60), nullable=True)
    resolution_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    bands_json: Mapped[list | dict | None] = mapped_column(GeoJSONType, nullable=True)
    coverage_geojson: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)

    format: Mapped[str | None] = mapped_column(String(20), nullable=True)   # geotiff|csv|json|netcdf
    file_path: Mapped[str | None] = mapped_column(String(600), nullable=True)  # storage-relative
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(80), nullable=True)

    metadata_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)
    provenance_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)

    quality_flag: Mapped[str] = mapped_column(String(32), default="UNVALIDATED", index=True)
    quality_reason: Mapped[str] = mapped_column(Text, default="")
    coverage_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    data_source: Mapped[DataSource | None] = relationship(back_populates="datasets", lazy="selectin")  # noqa: F821
    study_area: Mapped[StudyArea | None] = relationship(lazy="selectin")


class DataProduct(Base):
    """A processed output artefact (raster/vector/table) on storage."""

    __tablename__ = "data_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    processing_run_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "processing_runs.id",
            ondelete="SET NULL",
            # data_products and processing_runs reference each other
            # (ProcessingRun.output_product_id points back here).  Deferring
            # this one constraint breaks the create-table ordering cycle.
            use_alter=True,
            name="fk_data_products_processing_run_id_processing_runs",
        ),
        nullable=True,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(20), default="raster")   # raster|vector|table
    name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    format: Mapped[str] = mapped_column(String(20), default="geotiff")
    file_path: Mapped[str] = mapped_column(String(600))
    crs: Mapped[str | None] = mapped_column(String(60), nullable=True)
    bbox_geojson: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)
    resolution_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(80), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)
    quality_flag: Mapped[str] = mapped_column(String(32), default="VALID", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    processing_run: Mapped[ProcessingRun | None] = relationship(
        back_populates="products", foreign_keys=[processing_run_id]
    )


class ProcessingRun(Base):
    """Execution record for one preprocessing / computation operation."""

    __tablename__ = "processing_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    operation: Mapped[str] = mapped_column(String(60), index=True)   # clip|cloud_mask|composite|...
    params_json: Mapped[dict] = mapped_column(GeoJSONType, default=dict)
    algorithm_version: Mapped[str] = mapped_column(String(40), default="1.0.0")
    input_dataset_ids_json: Mapped[list | None] = mapped_column(GeoJSONType, nullable=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    output_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_products.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    metrics_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    products: Mapped[list[DataProduct]] = relationship(
        back_populates="processing_run",
        foreign_keys="DataProduct.processing_run_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )


class IndicatorDefinition(Base):
    __tablename__ = "indicator_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(30), index=True)  # water_level|water_quality|climate
    description: Mapped[str] = mapped_column(Text, default="")
    definition: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str] = mapped_column(String(40))
    method: Mapped[str] = mapped_column(Text, default="")
    method_version: Mapped[str] = mapped_column(String(40), default="1.0.0")
    is_proxy: Mapped[bool] = mapped_column(default=False)   # remote-sensing proxy / estimate
    requires_kinds: Mapped[list | None] = mapped_column(GeoJSONType, nullable=True)  # dataset kinds it needs
    params_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class IndicatorResult(Base):
    __tablename__ = "indicator_results"
    __table_args__ = (
        Index := __import__("sqlalchemy").Index("ix_indicator_results_key_date", "indicator_key", "observed_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    definition_id: Mapped[int] = mapped_column(ForeignKey("indicator_definitions.id", ondelete="CASCADE"), index=True)
    indicator_key: Mapped[str] = mapped_column(String(80), index=True)
    study_area_id: Mapped[int | None] = mapped_column(
        ForeignKey("study_areas.id", ondelete="SET NULL"), nullable=True, index=True
    )
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True, index=True)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)

    # value is NULL when the indicator could not be computed - never coerced to 0
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(40))
    observed_start: Mapped[date] = mapped_column(Date, index=True)
    observed_end: Mapped[date] = mapped_column(Date, index=True)
    temporal_resolution: Mapped[str] = mapped_column(String(40), default="instant")
    spatial_resolution: Mapped[str] = mapped_column(String(60), default="")
    spatial_extent_geojson: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)

    quality_flag: Mapped[str] = mapped_column(String(32), default="UNVALIDATED", index=True)
    quality_reason: Mapped[str] = mapped_column(Text, default="")
    flag_reasons_json: Mapped[list | dict | None] = mapped_column(GeoJSONType, nullable=True)
    coverage_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    missing_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    uncertainty_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)

    provenance_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)
    parameters_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class QualityAssessment(Base):
    __tablename__ = "quality_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(30), index=True)   # dataset|product|indicator_result
    subject_id: Mapped[int] = mapped_column(Integer, index=True)
    rule_version: Mapped[str] = mapped_column(String(20))
    flag: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    coverage_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    missing_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    cloud_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    details_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ExportJob(Base):
    __tablename__ = "export_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True)
    format: Mapped[str] = mapped_column(String(12))           # csv|json|geojson|geotiff
    resource_type: Mapped[str] = mapped_column(String(30))    # datasets|indicator_results|timeseries|comparison|raster
    params_json: Mapped[dict] = mapped_column(GeoJSONType, default=dict)
    file_path: Mapped[str | None] = mapped_column(String(600), nullable=True)  # storage-relative
    file_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    job: Mapped[Job] = relationship(lazy="selectin")  # noqa: F821

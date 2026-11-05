"""Data-source configuration and threshold configuration models."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, GeoJSONType, utcnow


class DataSource(Base):
    """An admin-configured satellite / climate data source.

    ``credential_ref`` holds only a *reference* to a secret (e.g.
    ``env:MODIS_EARTHDATA_TOKEN``); secret values never live in the database
    and are never serialised to the frontend.
    """

    __tablename__ = "data_sources"
    __table_args__ = (UniqueConstraint("provider_key", "dataset_identifier", name="uq_data_sources_provider_dataset"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    provider_key: Mapped[str] = mapped_column(String(60), index=True)   # adapter key, e.g. "chirps"
    category: Mapped[str] = mapped_column(String(40), index=True)       # core.enums.DataSourceCategory
    dataset_name: Mapped[str] = mapped_column(String(200), default="")
    dataset_identifier: Mapped[str] = mapped_column(String(200), default="", index=True)
    description: Mapped[str] = mapped_column(Text, default="")

    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    coverage_geojson: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)
    temporal_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    temporal_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    variables_json: Mapped[list | dict | None] = mapped_column(GeoJSONType, nullable=True)  # JSON list
    ingestion_config_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)

    auth_method: Mapped[str] = mapped_column(String(30), default="none")
    credential_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)  # reference only, never a secret

    status: Mapped[str] = mapped_column(String(20), default="configured", index=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_test_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    last_ingestion_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- daily schedule (mirrors DATA_SOURCES.schedule in the ER diagram) ---
    # ``schedule_enabled`` is deliberately opt-in: an administrator must mark a
    # source as scheduled before the daily pipeline downloads from it.
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    schedule_time_utc: Mapped[str] = mapped_column(String(5), default="02:00")  # HH:MM
    schedule_lookback_days: Mapped[int] = mapped_column(Integer, default=3)
    last_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    datasets: Mapped[list[Dataset]] = relationship(  # noqa: F821
        back_populates="data_source", lazy="selectin", cascade="all, delete-orphan", passive_deletes=True
    )


class Threshold(Base):
    """Configurable indicator threshold (configuration only; no alert engine)."""

    __tablename__ = "thresholds"

    id: Mapped[int] = mapped_column(primary_key=True)
    indicator_key: Mapped[str] = mapped_column(String(80), index=True)
    indicator_name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(40))
    operator: Mapped[str] = mapped_column(String(10))          # gt|gte|lt|lte|between
    value_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    justification: Mapped[str] = mapped_column(Text, default="")
    reference: Mapped[str] = mapped_column(Text, default="")
    approval_status: Mapped[str] = mapped_column(String(20), default="provisional", index=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    versions: Mapped[list[ThresholdVersion]] = relationship(
        back_populates="threshold",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ThresholdVersion.version.desc()",
    )


class ThresholdVersion(Base):
    """Append-only version history for a threshold configuration."""

    __tablename__ = "threshold_versions"
    __table_args__ = (UniqueConstraint("threshold_id", "version", name="uq_threshold_versions_threshold_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    threshold_id: Mapped[int] = mapped_column(
        ForeignKey("thresholds.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    snapshot_json: Mapped[dict] = mapped_column(GeoJSONType)
    change_note: Mapped[str] = mapped_column(Text, default="")
    changed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changed_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    threshold: Mapped[Threshold] = relationship(back_populates="versions")

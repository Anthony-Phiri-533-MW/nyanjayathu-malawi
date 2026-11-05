"""Machine-learning persistence: trained models, blocked-validation results and
forecast runs.

These tables mirror the ``MODELS``, ``EVALUATIONS`` and ``FORECASTS`` entities in
the project's ER diagram.  A model row is the *fitted artefact metadata* only -
the serialised estimator lives on disk under ``settings.forecast_model_dir`` so
the database stays small and the artefact can be checksummed separately.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, GeoJSONType, utcnow


class MLModel(Base):
    """One trained estimator for one (indicator, study area) series."""

    __tablename__ = "models"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stable identity used for upserts: algorithm + series + version.
    key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    algorithm: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[str] = mapped_column(String(40), default="1")

    indicator_key: Mapped[str] = mapped_column(String(80), index=True)
    study_area_id: Mapped[int | None] = mapped_column(
        ForeignKey("study_areas.id", ondelete="CASCADE"), nullable=True, index=True
    )

    cadence: Mapped[str] = mapped_column(String(20), default="daily")  # daily|weekly|monthly
    n_lags: Mapped[int] = mapped_column(Integer, default=1)
    feature_names_json: Mapped[list | dict | None] = mapped_column(GeoJSONType, nullable=True)
    params_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)

    train_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    train_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    n_train: Mapped[int] = mapped_column(Integer, default=0)

    # Aggregate out-of-fold metrics (mean over folds) for quick ranking.
    metrics_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)
    rmse: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)
    bias: Mapped[float | None] = mapped_column(Float, nullable=True)
    skill_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    artifact_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    trained_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    study_area: Mapped["StudyArea | None"] = relationship(lazy="selectin")  # noqa: F821
    evaluations: Mapped[list["ModelEvaluation"]] = relationship(
        back_populates="model", lazy="selectin", cascade="all, delete-orphan", passive_deletes=True
    )


class ModelEvaluation(Base):
    """Metrics from one blocked rolling-origin fold (one horizon, one test window)."""

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"), index=True)
    indicator_key: Mapped[str] = mapped_column(String(80), index=True)
    study_area_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    fold: Mapped[int] = mapped_column(Integer, default=0)
    horizon_days: Mapped[int] = mapped_column(Integer, default=1)
    train_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    train_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    test_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    test_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    n_train: Mapped[int] = mapped_column(Integer, default=0)
    n_test: Mapped[int] = mapped_column(Integer, default=0)

    rmse: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)
    bias: Mapped[float | None] = mapped_column(Float, nullable=True)
    mape: Mapped[float | None] = mapped_column(Float, nullable=True)
    r2: Mapped[float | None] = mapped_column(Float, nullable=True)
    skill_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 1 - MSE_model/MSE_persistence
    coverage: Mapped[float | None] = mapped_column(Float, nullable=True)      # share inside the prediction interval
    metrics_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    model: Mapped[MLModel] = relationship(back_populates="evaluations")


class ForecastRun(Base):
    """One invocation of the forecasting engine for an (area, indicator) pair."""

    __tablename__ = "forecast_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    study_area_id: Mapped[int] = mapped_column(ForeignKey("study_areas.id", ondelete="CASCADE"), index=True)
    indicator_key: Mapped[str] = mapped_column(String(80), index=True)
    model_id: Mapped[int | None] = mapped_column(
        ForeignKey("models.id", ondelete="SET NULL"), nullable=True, index=True
    )

    status: Mapped[str] = mapped_column(String(20), default="running", index=True)  # running|succeeded|skipped|failed
    horizon_days: Mapped[int] = mapped_column(Integer, default=7)
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    metrics_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)

    study_area: Mapped["StudyArea | None"] = relationship(lazy="selectin")  # noqa: F821
    model: Mapped[MLModel | None] = relationship(lazy="selectin")

"""Disaster Management module persistence: forecast values, alerts and the
append-only response record for each alert.

The comparison engine is documented in ``app/services/disaster.py``.  Nothing
here invents data: an alert always points at the metric value that triggered it
(either a computed indicator result or a recorded forecast) and snapshots the
threshold that was breached.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, GeoJSONType, utcnow


class ForecastValue(Base):
    """A projected value for one indicator/study-area/date.

    Two provenances share this table so the threshold engine has a single
    source of truth:

    * ``source="manual"`` - entered by an authorised user (with a mandatory
      provenance note);
    * ``source="model"`` - produced by the short-term forecasting engine, which
      links the row to the trained model (``model_id``), the run that issued it
      (``run_id``) and a prediction interval (``lower``/``upper``).

    The engine never invents a value: rows are written only from ingested
    indicator results, and a series that is too short produces no row at all.
    """

    __tablename__ = "forecast_values"

    id: Mapped[int] = mapped_column(primary_key=True)
    study_area_id: Mapped[int] = mapped_column(ForeignKey("study_areas.id", ondelete="CASCADE"), index=True)
    indicator_key: Mapped[str] = mapped_column(String(80), index=True)
    target_date: Mapped[date] = mapped_column(Date, index=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text, default="")   # provenance / method citation expected here

    # --- model provenance (NULL for manually entered forecasts) -----------
    source: Mapped[str] = mapped_column(String(10), default="manual", index=True)
    model_id: Mapped[int | None] = mapped_column(
        ForeignKey("models.id", ondelete="SET NULL"), nullable=True, index=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    lead_time_days: Mapped[int] = mapped_column(Integer, default=0)
    lower: Mapped[float | None] = mapped_column(Float, nullable=True)
    upper: Mapped[float | None] = mapped_column(Float, nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    study_area: Mapped[StudyArea] = relationship(lazy="selectin")  # noqa: F821
    created_by: Mapped[User | None] = relationship(lazy="selectin")  # noqa: F821
    model: Mapped[object | None] = relationship("MLModel", lazy="selectin")
    run: Mapped[object | None] = relationship("ForecastRun", lazy="selectin")


class Alert(Base):
    """A threshold breach raised by the evaluation engine.

    ``status`` follows the response workflow (open -> acknowledged ->
    resolved, reopenable).  ``threshold_snapshot_json`` records exactly which
    threshold version was breached, so later threshold edits never rewrite
    history.  ``metric_source`` labels the evaluated value as coming from
    computed indicator results ("observed") or a recorded forecast ("forecast").
    """

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    study_area_id: Mapped[int | None] = mapped_column(
        ForeignKey("study_areas.id", ondelete="SET NULL"), nullable=True, index=True
    )
    indicator_key: Mapped[str] = mapped_column(String(80), index=True)
    indicator_name: Mapped[str] = mapped_column(String(200), default="")
    threshold_id: Mapped[int | None] = mapped_column(
        ForeignKey("thresholds.id", ondelete="SET NULL"), nullable=True, index=True
    )
    threshold_snapshot_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)

    metric_source: Mapped[str] = mapped_column(String(20), index=True)   # observed|forecast
    metric_value: Mapped[float] = mapped_column(Float)
    metric_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    unit: Mapped[str] = mapped_column(String(40), default="")

    kind: Mapped[str] = mapped_column(String(30), index=True)            # flood|drought|water_quality|general
    severity: Mapped[str] = mapped_column(String(20), index=True)        # info|warning|critical
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    is_public: Mapped[bool] = mapped_column(default=False, index=True)  # shown on the public dashboard
    message: Mapped[str] = mapped_column(Text, default="")

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    last_evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    times_seen: Mapped[int] = mapped_column(Integer, default=1)

    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acknowledged_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    study_area: Mapped[StudyArea | None] = relationship(lazy="selectin")  # noqa: F821
    acknowledged_by: Mapped[User | None] = relationship(foreign_keys=[acknowledged_by_id], lazy="selectin")  # noqa: F821
    resolved_by: Mapped[User | None] = relationship(foreign_keys=[resolved_by_id], lazy="selectin")  # noqa: F821
    responses: Mapped[list[AlertResponse]] = relationship(
        back_populates="alert",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="AlertResponse.created_at.asc(), AlertResponse.id.asc()",
    )


class AlertResponse(Base):
    """Append-only record of each user response to an alert."""

    __tablename__ = "alert_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    response_type: Mapped[str] = mapped_column(String(20))   # acknowledged|note|resolved|reopened
    note: Mapped[str] = mapped_column(Text, default="")
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    alert: Mapped[Alert] = relationship(back_populates="responses")
    actor: Mapped[User | None] = relationship(lazy="selectin")  # noqa: F821

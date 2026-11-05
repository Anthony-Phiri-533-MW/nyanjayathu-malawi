"""Daily scheduler run log.

One row per UTC day keeps the daily pipeline idempotent: a unique constraint on
``run_date`` means two app instances (or a restarted process) cannot both start
the same day's run.  The row also gives the paper an auditable record of what
was downloaded, which indicators were computed and which forecasts were issued.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, GeoJSONType, utcnow


class SchedulerRun(Base):
    __tablename__ = "scheduler_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)  # running|succeeded|failed|skipped
    trigger: Mapped[str] = mapped_column(String(20), default="schedule")  # schedule|manual
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

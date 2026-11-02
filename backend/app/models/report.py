"""Report Generation persistence.

A ``Report`` row is the record of one report build request.  ``summary_json``
is the computed snapshot taken at build time - reports deliberately freeze the
figures they contained, so a later data change never silently rewrites a
distributed report.  The rendered file lives in the file store (see
``app/services/storage.py``), referenced storage-relative like every other
persisted artefact.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, GeoJSONType, utcnow


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True)

    title: Mapped[str] = mapped_column(String(220))
    kind: Mapped[str] = mapped_column(String(20), index=True)       # periodic|custom
    period_type: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)  # daily|weekly|monthly|quarterly|annual (periodic only)
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    study_area_id: Mapped[int | None] = mapped_column(
        ForeignKey("study_areas.id", ondelete="SET NULL"), nullable=True, index=True
    )

    format: Mapped[str] = mapped_column(String(10), default="pdf")  # pdf|csv
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)
    params_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)  # build config (sections, filters, note)

    # storage-relative file reference; NULL until the build completed
    file_path: Mapped[str | None] = mapped_column(String(600), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    job: Mapped[Job] = relationship(lazy="selectin")  # noqa: F821
    study_area: Mapped[StudyArea | None] = relationship(lazy="selectin")  # noqa: F821
    created_by: Mapped[User | None] = relationship(lazy="selectin")  # noqa: F821

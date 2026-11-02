"""Generic background job queue.

A single table backs ingestion, processing, indicator and export work.  A
small worker (``app.services.jobs``) polls for pending rows, so long-running
tasks never block the request cycle and state survives restarts.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, GeoJSONType, utcnow


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)     # ingestion|processing|indicator|export
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(String(500), default="")
    params_json: Mapped[dict] = mapped_column(GeoJSONType, default=dict)
    result_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)

    requested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

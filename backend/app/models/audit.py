"""Append-only audit log model.

There are intentionally no update/delete service methods or API routes for
these rows; only inserts are ever issued.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, GeoJSONType, utcnow


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(80), index=True)         # e.g. "user.create"
    resource_type: Mapped[str] = mapped_column(String(60), index=True)  # e.g. "user"
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(12), default="success", index=True)
    ip_address: Mapped[str | None] = mapped_column(String(60), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details_json: Mapped[dict | None] = mapped_column(GeoJSONType, nullable=True)  # sanitised change details
    message: Mapped[str] = mapped_column(Text, default="")

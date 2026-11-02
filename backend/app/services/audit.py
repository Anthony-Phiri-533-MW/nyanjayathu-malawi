"""Append-only audit logging.

Writes happen through an independent session so events survive rollbacks of
the triggering transaction.  Passwords, tokens and credential values are
never written: ``details`` is scrubbed for sensitive keys before persisting.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import count_query, run_isolated
from app.models import AuditEvent, User

log = logging.getLogger("lakewatch.audit")

_SENSITIVE_KEYS = {
    "password",
    "new_password",
    "current_password",
    "hashed_password",
    "token",
    "access_token",
    "reset_token",
    "secret",
    "secret_key",
    "credential",
    "credentials",
    "credential_ref",
    "api_key",
    "authorization",
    "password_reset_hash",
}


def scrub(details: Any, _depth: int = 0) -> Any:
    """Recursively drop/redact sensitive values from audit payloads."""
    if _depth > 6:
        return "<truncated>"
    if isinstance(details, dict):
        out: dict[str, Any] = {}
        for k, v in details.items():
            if str(k).lower() in _SENSITIVE_KEYS:
                out[k] = "<redacted>"
            else:
                out[k] = scrub(v, _depth + 1)
        return out
    if isinstance(details, (list, tuple)):
        return [scrub(v, _depth + 1) for v in details]
    if isinstance(details, str) and len(details) > 2000:
        return details[:2000] + "…"
    return details


def record(
    *,
    action: str,
    resource_type: str,
    resource_id: str | int | None = None,
    outcome: str = "success",
    actor: User | None = None,
    actor_id: int | None = None,
    actor_email: str | None = None,
    details: dict[str, Any] | None = None,
    message: str = "",
    ip_address: str | None = None,
    request_id: str | None = None,
    db: Session | None = None,
) -> None:
    """Persist one audit event.  Never raises into the caller.

    Pass ``db`` (the session the caller is already using) whenever one exists:
    on SQLite a second connection cannot write while the caller still holds the
    write lock, and the caller cannot commit while it is blocked here, so the
    event must join the caller's transaction.  The event is then committed with
    the caller's work.

    Without ``db`` the event is written in its own transaction through
    ``run_isolated``, so it survives a rollback of the triggering transaction -
    the behaviour background jobs get from ``session_scope``.
    """
    try:
        def _write(session) -> None:
            session.add(
                AuditEvent(
                    actor_id=actor.id if actor is not None else actor_id,
                    actor_email=(actor.email if actor is not None else actor_email),
                    action=action,
                    resource_type=resource_type,
                    resource_id=str(resource_id) if resource_id is not None else None,
                    outcome=outcome,
                    details_json=scrub(details) if details is not None else None,
                    message=message[:2000],
                    ip_address=ip_address,
                    request_id=request_id or uuid.uuid4().hex,
                )
            )
            session.flush()

        if isinstance(db, Session):
            _write(db)
            return

        def _failed(exc: Exception | None) -> None:
            log.warning("Failed to persist audit event %s: %s", action, exc)

        run_isolated(_write, on_error=_failed)
    except Exception:  # pragma: no cover - defensive
        log.exception("Failed to persist audit event %s", action)


def list_events(
    db,
    *,
    search: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    outcome: str | None = None,
    resource_type: str | None = None,
    date_from=None,
    date_to=None,
    page: int = 1,
    size: int = 20,
):
    from sqlalchemy import or_

    stmt = select(AuditEvent)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                AuditEvent.action.ilike(like),
                AuditEvent.message.ilike(like),
                AuditEvent.actor_email.ilike(like),
                AuditEvent.resource_type.ilike(like),
                AuditEvent.resource_id.ilike(like),
            )
        )
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if actor:
        stmt = stmt.where(AuditEvent.actor_email.ilike(f"%{actor.strip()}%"))
    if outcome:
        stmt = stmt.where(AuditEvent.outcome == outcome)
    if resource_type:
        stmt = stmt.where(AuditEvent.resource_type == resource_type)
    if date_from:
        stmt = stmt.where(AuditEvent.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditEvent.created_at <= date_to)

    total = count_query(stmt, db)
    rows = (
        db.execute(stmt.order_by(AuditEvent.id.desc()).limit(size).offset((page - 1) * size))
        .scalars()
        .all()
    )
    return rows, total

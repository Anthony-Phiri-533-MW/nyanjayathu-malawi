"""SQLAlchemy engine / session setup supporting PostgreSQL and SQLite."""
from __future__ import annotations

import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

log = logging.getLogger("lakewatch.db")

# SQLite serialises writers: a connection cannot write while another
# connection holds the write lock.  The PRAGMA busy_timeout covers most of it,
# but a transaction that already holds a read snapshot on this connection can
# still deadlock with a concurrent writer, so isolated writers retry briefly.
_SQLITE_RETRY_ATTEMPTS = 8
_SQLITE_RETRY_BASE_DELAY = 0.05

# The session currently serving the request/job on this task, if any.  Helpers
# that must not share the caller's transaction (audit logging) consult this so
# they can join it instead of opening a *second* connection: on SQLite a second
# connection cannot write while the caller still holds the write lock, and the
# caller cannot commit while it is blocked inside the helper - a deadlock that
# no timeout can resolve.
_current_session: ContextVar[Session | None] = ContextVar("lakewatch_current_session", default=None)


def current_session() -> Session | None:
    """Session bound to the in-flight request/job on this task, if any."""
    return _current_session.get()


def _make_engine(url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        # A generous busy timeout matters because audit events are written from
        # an independent session while a request transaction is still open.
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        # Enforce foreign keys and keep writes durable on every connection.
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()
    return engine


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def new_session() -> Session:
    """Create a session and publish it as the task's current session.

    Callers that close the session should pair this with ``release_session``
    (``get_db`` / ``session_scope`` do it for you).  Use ``SessionLocal()``
    directly for a genuinely independent session that helpers must *not* join.
    """
    db = SessionLocal()
    _current_session.set(db)
    return db


def release_session(db: Session) -> None:
    """Drop ``db`` from the task's current-session slot and close it."""
    if _current_session.get() is db:
        _current_session.set(None)
    db.close()


def get_db() -> Generator[Session, None, None]:
    db = new_session()
    try:
        yield db
    finally:
        release_session(db)


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Session for background jobs / CLI where no request scope exists."""
    db = new_session()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        release_session(db)


def run_isolated(work, *, attempts: int = _SQLITE_RETRY_ATTEMPTS, on_error=None):
    """Run ``work(db)`` in its own session, retrying SQLite write contention.

    Used for writes that must not share the caller's transaction (see
    ``app.models.base.ISOLATED_WRITE_TABLES``).  On PostgreSQL the first
    attempt simply succeeds.

    When a request/job session is already bound to this task *and the backend
    is SQLite*, the work joins that session instead: a second connection could
    never acquire the write lock while the caller holds it, and the caller
    cannot commit while it is blocked here.  The caller then owns the commit.
    ``on_error`` receives the last exception when every attempt fails; the
    caller decides whether that is fatal.
    """
    existing = current_session()
    if existing is not None and settings.is_sqlite:
        try:
            return work(existing)
        except Exception as exc:  # pragma: no cover - defensive
            if on_error is not None:
                on_error(exc)
                return None
            raise

    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return _attempt_isolated_write(work)
        except OperationalError as exc:  # almost always SQLite lock contention
            last_error = exc
            if not settings.is_sqlite or attempt == attempts - 1:
                break
            log.debug("isolated write retry %s/%s: %s", attempt + 1, attempts, exc)
        time.sleep(_SQLITE_RETRY_BASE_DELAY * (attempt + 1))
    if on_error is not None:
        on_error(last_error)
        return None
    assert last_error is not None
    raise last_error


def count_query(stmt, db: Session) -> int:
    """Total rows a paginated statement would yield, ignoring ordering.

    ``with_only_columns(func.count())`` is not reliable on SQLAlchemy 2.1 for
    statements built from an entity (it keeps an entity column alongside the
    aggregate, so the scalar is wrong).  Counting a subquery of the filtered
    statement is unambiguous and also correct for statements that eager-load
    relationships.
    """
    from sqlalchemy import func, select

    return db.execute(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    ).scalar_one()


def _attempt_isolated_write(work):
    with session_scope() as db:
        return work(db)

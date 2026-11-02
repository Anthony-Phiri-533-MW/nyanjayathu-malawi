"""Declarative base, common column types and timestamp helpers.

All timestamps are stored as naive UTC values and converted to timezone-aware
values on the way out of the API, which keeps PostgreSQL and SQLite behaviour
identical.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import Text, TypeDecorator

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Tables written by an *independent* session while a request transaction may
# still be open.  Audit events are the important case: the audit service opens
# its own session so an event survives a rollback of the triggering
# transaction, which on SQLite requires a short retry (SQLite allows a single
# writer at a time - see app.core.database._sqlite_retry).
ISOLATED_WRITE_TABLES = frozenset({"audit_events"})


def utcnow() -> datetime:
    """Current UTC time, stored without tz info (see module docstring)."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class GeoJSONType(TypeDecorator):
    """Stores a GeoJSON geometry/object as TEXT on every dialect.

    Geometry validation happens at the service layer (shapely); on PostgreSQL
    the migration layer additionally exposes PostGIS helpers/indexes over the
    same column (see alembic revision 0002).
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            json.loads(value)  # validate
            return value
        return json.dumps(value, separators=(",", ":"))

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        return json.loads(value)


UTCDateTime = DateTime()


def timestamp_column(**kwargs: Any):
    return DateTime(**kwargs)

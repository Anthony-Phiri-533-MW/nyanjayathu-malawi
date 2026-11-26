"""Unit and provenance discipline (Signature-Challenge Property 2).

The assignment's crisis theme is the *unit-mismatch failure* (Mars Climate
Orbiter, 1999): a value whose unit is assumed rather than carried is a value
that can mislead disaster planners.  This module makes the unit explicit and
refuses to silently mix incompatible units.

It is deliberately dependency-free (no Pint required at runtime) so it runs in
the zero-config SQLite/test environment.  The public surface is small and
totally testable:

* :func:`to_metres`          – convert a length value to metres.
* :func:`compare_lengths`    – compare two lengths, raising on mix-ups.
* :func:`check_provenance`   – assert unit/sensor/date/version are present.
* :class:`UnitMismatchError` / :class:`ProvenanceError`.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

# multiplicative factor to convert each supported length unit into metres.
_LENGTH_TO_METRES: dict[str, float] = {
    "m": 1.0,
    "metre": 1.0,
    "meter": 1.0,
    "metres": 1.0,
    "meters": 1.0,
    "cm": 0.01,
    "centimetre": 0.01,
    "centimeter": 0.01,
    "mm": 0.001,
    "km": 1000.0,
    "kilometre": 1000.0,
    "kilometer": 1000.0,
}

# coordinate reference systems we accept for provenance; anything else is a
# silent coordinate-system mix-up waiting to happen.
_KNOWN_CRS = {"epsg:4326", "4326", "epsg:3857", "3857", "wgs84"}


class UnitMismatchError(ValueError):
    """Raised when two values carry incompatible or missing units."""


class ProvenanceError(ValueError):
    """Raised when a value is missing mandatory provenance metadata."""


def _normalise(unit: str) -> str:
    return str(unit).strip().lower()


def is_length_unit(unit: str) -> bool:
    """Return ``True`` when *unit* is a recognised length unit."""
    return _normalise(unit) in _LENGTH_TO_METRES


def to_metres(value: float, unit: str) -> float:
    """Convert *value* expressed in *unit* to metres.

    Raises :class:`UnitMismatchError` for an unknown/incompatible unit so a
    caller can never silently treat an unrecognised unit as metres.
    """
    factor = _LENGTH_TO_METRES.get(_normalise(unit))
    if factor is None:
        raise UnitMismatchError(f"unsupported length unit: {unit!r}")
    return float(value) * factor


def compare_lengths(
    a: float, a_unit: str, b: float, b_unit: str, *, tol: float = 1e-6
) -> bool:
    """Compare two lengths after converting both to metres.

    This is the guard that catches the classic metre/centimetre mix-up: a
    water level of ``1500`` cm and ``1500`` m are *not* equal and the function
    converts before comparing instead of comparing raw numbers.
    """
    return abs(to_metres(a, a_unit) - to_metres(b, b_unit)) <= tol


def check_crs(crs: str) -> str:
    """Validate a coordinate reference system label, raising on a mix-up."""
    if _normalise(crs) not in _KNOWN_CRS:
        raise UnitMismatchError(f"unrecognised coordinate reference system: {crs!r}")
    return _normalise(crs)


def check_provenance(record: Mapping[str, Any]) -> None:
    """Assert that *record* carries unit, sensor, date and processing version.

    Every satellite-derived value must be traceable; a value without these four
    fields is rejected rather than published.  ``date`` may be a ``date``/
    ``datetime`` or an ISO-8601 string.
    """
    missing = [f for f in ("unit", "sensor", "date", "processing_version")
               if record.get(f) in (None, "")]
    if missing:
        raise ProvenanceError(f"missing provenance fields: {', '.join(missing)}")
    if not is_length_unit(record["unit"]) and record.get("unit") not in ("km²", "km2", "°C", "mm", "K"):
        # non-length units (area/temperature/rainfall) are allowed but must be
        # from the known vocabulary; an arbitrary string is treated as a mix-up.
        raise UnitMismatchError(f"unrecognised unit in provenance: {record['unit']!r}")
    _coerce_date(record["date"])
    check_crs(record.get("crs", "epsg:4326"))


def _coerce_date(value: Any) -> None:
    if isinstance(value, (date, datetime)):
        return
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:  # pragma: no cover - defensive
        raise ProvenanceError(f"invalid provenance date: {value!r}") from exc

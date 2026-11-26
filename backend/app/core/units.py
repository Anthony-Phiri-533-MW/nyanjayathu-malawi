"""Unit discipline helpers (Pint-backed) for indicator values.

Every indicator result carries a unit string.  This module provides a small
validation layer that rejects obviously mismatched units (metre vs.
centimetre, degree vs. radian) before a value is persisted, in the spirit of
the Mars Climate Orbiter (1999) lesson.
"""

from __future__ import annotations

from pint import UnitRegistry

_ureg = UnitRegistry()


def parse_unit(unit: str):
    return _ureg(unit)


def units_compatible(a: str, b: str) -> bool:
    try:
        return parse_unit(a).dimensionality == parse_unit(b).dimensionality
    except Exception:  # noqa: BLE001
        return False


def assert_unit(expected: str, actual: str) -> None:
    if expected != actual:
        raise ValueError(f"Unit mismatch: expected {expected}, got {actual}")
    # also ensure it parses as a real physical unit
    parse_unit(actual)

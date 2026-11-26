"""Characterisation tests for indicator unit discipline (Signature Challenge)."""

from __future__ import annotations

import pytest
from pint.errors import UndefinedUnitError

from app.core.units import assert_unit, units_compatible


def test_unit_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="Unit mismatch: expected m, got cm"):
        assert_unit("m", "cm")


def test_compatible_units() -> None:
    assert units_compatible("m", "cm") is True
    assert units_compatible("m", "kg") is False


def test_invalid_unit_raises() -> None:
    with pytest.raises(UndefinedUnitError):
        assert_unit("not_a_unit", "not_a_unit")

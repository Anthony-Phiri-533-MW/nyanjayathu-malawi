"""Unit tests for the full spectral-index Strategy catalogue.

Bands are small NumPy arrays so the maths is checkable by hand.  Verifies the
normalised-difference formula, NaN handling and the result contract.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.strategies import index_strategy as S

BANDS = {
    "green": np.array([0.2, 0.4]),
    "red": np.array([0.3, 0.3]),
    "nir": np.array([0.1, 0.2]),
    "swir1": np.array([0.05, 0.1]),
}

ALL = [S.MNDWI_Strategy, S.NdwiStrategy, S.NdmiStrategy, S.NdtiStrategy, S.WriStrategy]


@pytest.mark.parametrize("cls", ALL)
def test_strategy_result_contract(cls):
    result = cls().compute(BANDS)
    for key in ("value", "unit", "quality_flag", "procedure"):
        assert key in result
    assert result["quality_flag"] == "VALID"
    assert result["unit"] == "1"


def test_mndwi_value_by_hand():
    # green=0.2, swir1=0.05 -> (0.2-0.05)/(0.2+0.05)=0.6 ; green=0.4,swir1=0.1 -> 0.6
    result = S.MNDWI_Strategy().compute(BANDS)
    assert result["value"] == pytest.approx(0.6, rel=1e-6)


def test_keys_are_unique():
    keys = [cls().key for cls in ALL]
    assert len(keys) == len(set(keys))


def test_missing_data_when_all_zero():
    bands = {k: np.zeros(2) for k in ("green", "red", "nir", "swir1")}
    result = S.MNDWI_Strategy().compute(bands)
    assert result["value"] is None
    assert result["quality_flag"] == "MISSING_DATA"
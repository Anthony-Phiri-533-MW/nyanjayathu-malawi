"""Strategy pattern: a swappable catalogue of spectral-index algorithms.

Each strategy declares a ``key`` (the indicator catalogue id) and a
``compute(dataset)`` that turns a dict of reflectance bands (NumPy arrays) into
a result dict with ``value``, ``unit``, ``quality_flag`` and provenance.

Adding a new index (e.g. a water-quality index at the defence gate) means
subclassing :class:`IndexStrategy` and registering it — no call site changes.
All indices are dimensionless and computed with a safe normalised difference so
divide-by-zero pixels become NaN and are excluded from the reported mean.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

import numpy as np


def _band(dataset: Any, name: str) -> np.ndarray:
    return np.asarray(dataset[name], dtype=float)


def normalized_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(a - b) / (a + b) with divide-by-zero -> NaN."""
    denom = a + b
    out = np.full_like(denom, np.nan, dtype=float)
    valid = denom != 0
    out[valid] = (a[valid] - b[valid]) / denom[valid]
    return out


class IndexStrategy(ABC):
    """Base class for a spectral-index strategy."""

    @property
    @abstractmethod
    def key(self) -> str:
        """Short catalogue key for this index."""

    @abstractmethod
    def compute(self, dataset: Any) -> Dict[str, Any]:
        """Compute the indicator value from a dict of reflectance bands."""

    def _result(self, index: np.ndarray, procedure: str, sensor: str) -> Dict[str, Any]:
        valid = index[~np.isnan(index)]
        if valid.size == 0:
            return {"value": None, "unit": "1", "quality_flag": "MISSING_DATA",
                    "procedure": procedure, "sensor": sensor}
        return {
            "value": round(float(np.mean(valid)), 6),
            "unit": "1",
            "quality_flag": "VALID",
            "procedure": procedure,
            "sensor": sensor,
            "valid_fraction": round(valid.size / index.size, 4),
        }


class MNDWI_Strategy(IndexStrategy):
    """Modified Normalised Difference Water Index (Green, SWIR1)."""

    @property
    def key(self) -> str:
        return "water_extent"

    def compute(self, dataset: Any) -> Dict[str, Any]:
        idx = normalized_difference(_band(dataset, "green"), _band(dataset, "swir1"))
        return self._result(idx, "MNDWI", "S2_MPC")


class NdwiStrategy(IndexStrategy):
    """Normalised Difference Water Index (Green, NIR)."""

    @property
    def key(self) -> str:
        return "water_extent_ndwi"

    def compute(self, dataset: Any) -> Dict[str, Any]:
        idx = normalized_difference(_band(dataset, "green"), _band(dataset, "nir"))
        return self._result(idx, "NDWI", "S2_MPC")


class NdmiStrategy(IndexStrategy):
    """Normalised Difference Moisture Index (NIR, SWIR1)."""

    @property
    def key(self) -> str:
        return "moisture_index"

    def compute(self, dataset: Any) -> Dict[str, Any]:
        idx = normalized_difference(_band(dataset, "nir"), _band(dataset, "swir1"))
        return self._result(idx, "NDMI", "S2_MPC")


class NdtiStrategy(IndexStrategy):
    """Normalised Difference Turbidity Index (Red, Green) — water quality."""

    @property
    def key(self) -> str:
        return "turbidity_proxy"

    def compute(self, dataset: Any) -> Dict[str, Any]:
        idx = normalized_difference(_band(dataset, "red"), _band(dataset, "green"))
        return self._result(idx, "NDTI", "S2_MPC")


class WriStrategy(IndexStrategy):
    """Water Ratio Index (Green + Red) / (Green + Red + NIR + SWIR1)."""

    @property
    def key(self) -> str:
        return "water_ratio"

    def compute(self, dataset: Any) -> Dict[str, Any]:
        g, r = _band(dataset, "green"), _band(dataset, "red")
        nir, swir1 = _band(dataset, "nir"), _band(dataset, "swir1")
        denom = g + r + nir + swir1
        out = np.full_like(denom, np.nan, dtype=float)
        valid = denom != 0
        out[valid] = (g[valid] + r[valid]) / denom[valid]
        return self._result(out, "WRI", "S2_MPC")
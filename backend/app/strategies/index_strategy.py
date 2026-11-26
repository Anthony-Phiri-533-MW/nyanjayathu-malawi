"""Strategy pattern: swappable spectral‑index algorithms.

Each concrete strategy must implement:
- ``key`` – the short name used in the indicator catalogue (e.g. ``"water_extent"``).
- ``compute(dataset)`` – return a dict with at least the keys
  ``value``, ``unit``, ``quality_flag`` and any provenance info.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class IndexStrategy(ABC):
    """Base class for a spectral‑index strategy."""

    @property
    @abstractmethod
    def key(self) -> str:
        """Short catalogue key for this index."""

    @abstractmethod
    def compute(self, dataset: Any) -> Dict[str, Any]:
        """Compute the indicator value from a dataset.

        Parameters
        ----------
        dataset : any
            The raw (or already‑windowed) raster/data object that the strategy
            needs.  The exact type is up to the concrete implementation.

        Returns
        -------
        dict
            Must contain at least the following keys:
            - ``value``: numeric result (may be ``None`` if computation fails).
            - ``unit``: string describing the unit (e.g. ``"km²"``, ``"°C"``).
            - ``quality_flag``: string from the set
              ``{"MISSING_DATA", "PROCESSING_FAILED", "INSUFFICIENT_COVERAGE",
              "CLOUD_CONTAMINATED", "LOW_QUALITY", "UNVALIDATED", "VALID"}``.
            - Any additional provenance keys are encouraged.
        """
        raise NotImplementedError


# ----------------------------------------------------------------------
# Concrete strategy – MNDWI (Modified Normalised Difference Water Index)
# ----------------------------------------------------------------------
class MNDWI_Strategy(IndexStrategy):
    """Compute MNDWI = (Green – SWIR1) / (Green + SWIR1)."""

    @property
    def key(self) -> str:
        return "water_extent"

    def compute(self, dataset: Any) -> Dict[str, Any]:
        # ---- placeholder: in real code we would read the raster bands ----
        # Simulate a successful computation.
        value = 12.5                      # example km²
        unit = "km²"
        quality_flag = "VALID"            # would be set according to quality rules
        return {
            "value": value,
            "unit": unit,
            "quality_flag": quality_flag,
            "procedure": "MNDWI",
            "sensor": "S2_MPC",
        }
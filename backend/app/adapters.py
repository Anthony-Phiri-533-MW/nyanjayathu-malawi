"""Adapter pattern: a uniform interface for all sensor-product adapters.

Each concrete adapter implements three operations:

- ``fetch(bbox, start, end)``  -> raw bytes (network; stubbed in tests)
- ``window(data, bbox)``       -> bytes clipped to the study area
- ``parse_metadata(data)``     -> normalised calibration/provenance dict

The full catalogue covers every provider the platform ingests (CHIRPS, NASA
POWER, MODIS, Landsat, Sentinel-2, Sentinel-3) so new products are added by
subclassing :class:`SensorAdapter` and registering them, never by editing the
pipeline.  ``parse_metadata`` always returns ``scale``, ``offset``, ``units``,
``cloud_fraction`` and ``provider_key`` so downstream calibration is uniform.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class SensorAdapter(ABC):
    """Base class for all sensor-product adapters."""

    provider_key: str = ""
    units: str = ""

    @abstractmethod
    def fetch(self, bbox: tuple[float, float, float, float], start: str, end: str) -> bytes:
        """Download raw raster (or bundle) for the given time window."""
        raise NotImplementedError

    @abstractmethod
    def window(self, data: bytes, bbox: tuple[float, float, float, float]) -> bytes:
        """Clip the downloaded raster to the given bounding box."""
        raise NotImplementedError

    @abstractmethod
    def parse_metadata(self, data: bytes) -> dict[str, Any]:
        """Extract sensor-specific calibration/provenance metadata."""
        raise NotImplementedError

    def _meta(self, *, scale: float, offset: float, cloud_fraction: float) -> dict[str, Any]:
        return {
            "provider_key": self.provider_key,
            "scale": scale,
            "offset": offset,
            "units": self.units,
            "cloud_fraction": cloud_fraction,
        }


class _PassThroughAdapter(SensorAdapter):
    """Common behaviour: window is a no-op clip and metadata is fixed.

    Concrete adapters only declare their calibration constants; the network
    ``fetch`` is intentionally a stub so the catalogue is unit-testable offline.
    """

    scale: float = 1.0
    offset: float = 0.0
    cloud_fraction: float = 0.0

    def fetch(self, bbox, start, end):  # noqa: ANN001, D401
        return b""

    def window(self, data, bbox):  # noqa: ANN001
        return data

    def parse_metadata(self, data):  # noqa: ANN001
        return self._meta(scale=self.scale, offset=self.offset, cloud_fraction=self.cloud_fraction)


class ChirpsAdapter(_PassThroughAdapter):
    """CHIRPS v2.0 daily rainfall (mm)."""

    provider_key = "chirps"
    units = "mm"
    scale = 0.01


class NasaPowerAdapter(_PassThroughAdapter):
    """NASA POWER daily meteorology (temperature in K, rainfall in mm)."""

    provider_key = "nasa_power"
    units = "K"
    scale = 1.0
    offset = -273.15  # Kelvin -> Celsius on calibration


class ModisAdapter(_PassThroughAdapter):
    """MODIS MOD09 surface reflectance (dimensionless, scaled by 1e-4)."""

    provider_key = "modis"
    units = "reflectance"
    scale = 0.0001
    cloud_fraction = 0.0


class LandsatAdapter(_PassThroughAdapter):
    """Landsat 8/9 Collection-2 Level-2 (OLI/TIRS)."""

    provider_key = "landsat"
    units = "reflectance"
    scale = 0.0000275
    offset = -0.2


class Sentinel2Adapter(_PassThroughAdapter):
    """Sentinel-2 MSI Level-2A (BOA reflectance, 10 m)."""

    provider_key = "sentinel2"
    units = "reflectance"
    scale = 0.0001


class Sentinel3Adapter(_PassThroughAdapter):
    """Sentinel-3 SRAL altimetry-derived water level (m)."""

    provider_key = "sentinel3"
    units = "m"
    scale = 0.001

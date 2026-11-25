"""Adapter pattern: a uniform interface for all sensor product adapters.

Each concrete adapter must implement the three abstract methods:
- fetch(bbox, start, end) -> bytes
- window(data, bbox) -> bytes
- parse_metadata(data) -> dict
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

import rasterio
import rasterio.warp
import numpy as np


class SensorAdapter(ABC):
    """Base class for all sensor‑product adapters."""

    @abstractmethod
    def fetch(self, bbox: tuple[float, float, float, float], start: str, end: str) -> bytes:
        """Download raw raster (or bundle) for the given time window.

        Parameters
        ----------
        bbox : tuple of (min_lon, min_lat, max_lon, max_lat)
            Geographic bounding box in EPSG:4326.
        start : str
            ISO‑8601 date‑time string, e.g. ``"2024-01-01T00:00:00Z"``.
        end : str
            ISO‑8601 date‑time string, exclusive.

        Returns
        -------
        bytes
            Raw downloaded data (e.g. a GeoTIFF or compressed bundle).
        """
        raise NotImplementedError

    @abstractmethod
    def window(self, data: bytes, bbox: tuple[float, float, float, float]) -> bytes:
        """Clip the downloaded raster to the given bounding box.

        Parameters
        ----------
        data : bytes
            Raw data returned by ``fetch``.
        bbox : tuple of (min_lon, min_lat, max_lon, max_lat)
            Geographic bounding box in EPSG:4326.

        Returns
        -------
        bytes
            Windowed raster ready for calibration.
        """
        raise NotImplementedError

    @abstractmethod
    def parse_metadata(self, data: bytes) -> Dict[str, Any]:
        """Extract sensor‑specific metadata from the raw download.

        The returned dictionary should contain at least the following keys:
        - ``provider_key``: the short identifier used elsewhere (e.g. ``"chirps"``).
        - ``scale``: multiplicative factor to convert raw DN to physical units.
        - ``offset``: additive offset for the same conversion.
        - ``units``: string describing the physical unit (e.g. ``"mm"``, ``"K"``).
        - ``cloud_fraction``: float 0‑1, proportion of cloud cover (when available).

        Parameters
        ----------
        data : bytes
            Raw download content.

        Returns
        -------
        dict
            Normalised metadata.
        """
        raise NotImplementedError


# ----------------------------------------------------------------------
# Example concrete adapter – CHIRPS ( daily rainfall )
# ----------------------------------------------------------------------
class ChirpsAdapter(SensorAdapter):
    """Adapter for the CHIRPS v2.0 daily rainfall product."""

    BASE_URL = "https://chirps.ucsb.edu"

    def fetch(self, bbox: tuple[float, float, float, float], start: str, end: str) -> bytes:
        min_lon, min_lat, max_lon, max_lat = bbox
        # Build a simple request; the real implementation uses the provider's STAC endpoint.
        url = f"{self.BASE_URL}/chirps-v2.0/{start[:4]}/global/chirps-v2.0.{start[:4]}-{end[:10]}.tif.gz"
        # placeholder: return empty bytes – real code would use httpx or requests
        return b""

    def window(self, data: bytes, bbox: tuple[float, float, float, float]) -> bytes:
        # In a full implementation we would use rasterio/vrt to clip.
        # Here we just return the original data unchanged.
        return data

    def parse_metadata(self, data: bytes) -> Dict[str, Any]:
        # Normalised metadata – values are placeholders.
        return {
            "provider_key": "chirps",
            "scale": 0.01,          # 1 mm per DN
            "offset": 0.0,
            "units": "mm",
            "cloud_fraction": 0.0,
        }
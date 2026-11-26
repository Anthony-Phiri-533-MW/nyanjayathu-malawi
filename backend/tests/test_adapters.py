"""Unit tests for the full sensor-adapter catalogue (Adapter pattern).

Verifies that every concrete adapter:

* is a ``SensorAdapter`` and declares a provider key + units;
* returns the full metadata contract from ``parse_metadata``;
* exposes a numeric scale so raw DN can be calibrated to physical units.
"""
from __future__ import annotations

import pytest

from app import adapters
from app.adapters import SensorAdapter

ALL = [
    adapters.ChirpsAdapter,
    adapters.NasaPowerAdapter,
    adapters.ModisAdapter,
    adapters.LandsatAdapter,
    adapters.Sentinel2Adapter,
    adapters.Sentinel3Adapter,
]


@pytest.mark.parametrize("cls", ALL)
def test_adapter_metadata_contract(cls):
    adapter = cls()
    assert isinstance(adapter, SensorAdapter)
    meta = adapter.parse_metadata(b"")
    for key in ("provider_key", "scale", "offset", "units", "cloud_fraction"):
        assert key in meta
    assert meta["provider_key"] == adapter.provider_key
    assert isinstance(meta["scale"], (int, float))


def test_provider_keys_are_unique():
    keys = [cls().provider_key for cls in ALL]
    assert len(keys) == len(set(keys))


def test_window_is_passthrough_offline():
    a = adapters.Sentinel2Adapter()
    assert a.window(b"raw", (0, 0, 1, 1)) == b"raw"


def test_landsat_applies_offset():
    meta = adapters.LandsatAdapter().parse_metadata(b"")
    assert meta["offset"] == pytest.approx(-0.2)
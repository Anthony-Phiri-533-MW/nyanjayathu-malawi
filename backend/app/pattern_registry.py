"""Registry for the design-pattern implementations (Adapter + Strategy).

This is a tiny, dedicated registry that the pipeline and other new code
use.  It does NOT replace the existing ``providers.registry``; it co-exists
alongside it.
"""

from __future__ import annotations

from .adapters import (
    ChirpsAdapter,
    LandsatAdapter,
    ModisAdapter,
    NasaPowerAdapter,
    SensorAdapter,
    Sentinel2Adapter,
    Sentinel3Adapter,
)
from .strategies.index_strategy import (
    IndexStrategy,
    MNDWI_Strategy,
    NdmiStrategy,
    NdtiStrategy,
    NdwiStrategy,
    WriStrategy,
)

# ----------------------------------------------------------------------
# Adapter registry - maps a provider key to a concrete SensorAdapter.
# ----------------------------------------------------------------------
_ADAPTER_REGISTRY: dict[str, SensorAdapter] = {
    "chirps": ChirpsAdapter(),
    "nasa_power": NasaPowerAdapter(),
    "modis": ModisAdapter(),
    "landsat": LandsatAdapter(),
    "sentinel2": Sentinel2Adapter(),
    "sentinel3": Sentinel3Adapter(),
}


def get_adapter(key: str) -> SensorAdapter:
    """Return the :class:`SensorAdapter` registered for *key*."""
    adapter = _ADAPTER_REGISTRY.get(key)
    if adapter is None:
        raise KeyError(f"No SensorAdapter registered for provider '{key}'")
    return adapter


def known_adapter_keys() -> list[str]:
    return sorted(_ADAPTER_REGISTRY.keys())


# ----------------------------------------------------------------------
# Strategy registry - maps an index key to a concrete IndexStrategy.
# ----------------------------------------------------------------------
_STRATEGY_REGISTRY: dict[str, IndexStrategy] = {
    "water_extent": MNDWI_Strategy(),
    "water_extent_ndwi": NdwiStrategy(),
    "moisture_index": NdmiStrategy(),
    "turbidity_proxy": NdtiStrategy(),
    "water_ratio": WriStrategy(),
}


def get_strategy(key: str) -> IndexStrategy:
    """Return the :class:`IndexStrategy` registered for indicator *key*."""
    strategy = _STRATEGY_REGISTRY.get(key)
    if strategy is None:
        raise KeyError(f"No IndexStrategy registered for indicator '{key}'")
    return strategy


def known_strategy_keys() -> list[str]:
    return sorted(_STRATEGY_REGISTRY.keys())

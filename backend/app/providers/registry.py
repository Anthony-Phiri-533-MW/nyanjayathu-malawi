"""Provider adapter registry.

Adapters register themselves under a stable ``key`` which is stored on
``DataSource.provider_key``.  The registry is the single place the API and
ingestion look up "which adapter handles this source".
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.providers.base import ProviderAdapter, ProviderError

log = logging.getLogger("lakewatch.providers.registry")

_ADAPTERS: dict[str, type[ProviderAdapter]] = {}


def register_adapter(cls: type[ProviderAdapter]) -> type[ProviderAdapter]:
    if not cls.key:
        raise ValueError(f"{cls.__name__} must define a non-empty 'key'")
    if cls.key in _ADAPTERS:
        raise ValueError(f"duplicate provider key '{cls.key}'")
    _ADAPTERS[cls.key] = cls
    return cls


def known_provider_keys() -> list[str]:
    return sorted(_ADAPTERS)


def get_adapter(
    key: str,
    *,
    client: httpx.Client | None = None,
    config: dict[str, Any] | None = None,
) -> ProviderAdapter:
    cls = _ADAPTERS.get(key)
    if cls is None:
        raise ProviderError(
            f"No adapter is registered for provider '{key}'",
            details={"available": known_provider_keys()},
        )
    return cls(client=client, config=config)


def describe_adapters() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in known_provider_keys():
        adapter = _ADAPTERS[key](config={})  # type: ignore[call-arg]
        out.append(adapter.describe())
    return out


# Importing the adapter modules triggers registration.  Kept at the bottom to
# avoid circular imports (adapter modules import ``base`` only).
def _load_adapters() -> None:
    from app.providers import chirps, nasa_power, planetary_computer  # noqa: F401

    for cls in (
        planetary_computer.Sentinel2Mpc,
        planetary_computer.LandsatMpc,
        planetary_computer.ModisMpc,
        planetary_computer.ModisLstMpc,
        planetary_computer.Sentinel3SralMpc,
        chirps.ChirpsAdapter,
        nasa_power.NasaPowerAdapter,
    ):
        register_adapter(cls)


_load_adapters()

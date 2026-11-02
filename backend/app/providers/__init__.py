"""Provider adapters for external satellite / climate data sources."""
from app.providers.base import (
    DiscoveredItem,
    FetchedArtifact,
    IngestParams,
    ProviderAdapter,
    ProviderError,
    TestResult,
    close_http_client,
    get_http_client,
    set_http_client,
)
from app.providers.registry import (
    describe_adapters,
    get_adapter,
    known_provider_keys,
    register_adapter,
)

__all__ = [
    "DiscoveredItem",
    "FetchedArtifact",
    "IngestParams",
    "ProviderAdapter",
    "ProviderError",
    "TestResult",
    "close_http_client",
    "get_http_client",
    "set_http_client",
    "describe_adapters",
    "get_adapter",
    "known_provider_keys",
    "register_adapter",
]

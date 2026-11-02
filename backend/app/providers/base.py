"""Provider adapter base classes and shared HTTP plumbing."""
from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings

log = logging.getLogger("lakewatch.providers")

_client_lock = threading.Lock()
_client: httpx.Client | None = None


def get_http_client() -> httpx.Client:
    global _client
    with _client_lock:
        if _client is None or _client.is_closed:
            _client = httpx.Client(
                timeout=settings.http_timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": "LakeWatch/0.1 (research ingestion)"},
            )
        return _client


def set_http_client(client: httpx.Client | None) -> None:
    """Tests inject a MockTransport-backed client here."""
    global _client
    _client = client


def close_http_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        _client.close()
    _client = None


@dataclass
class TestResult:
    ok: bool
    message: str
    latency_ms: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoveredItem:
    """One retrievable unit (scene, granule or day) advertised by a provider."""

    asset_id: str
    title: str
    start_date: date
    end_date: date
    bbox: tuple[float, float, float, float] | None = None
    media_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    assets: dict[str, str] = field(default_factory=dict)   # variable/band key -> URL or path


@dataclass
class FetchedArtifact:
    item: DiscoveredItem
    path: str                       # storage-relative path (file or directory)
    size_bytes: int
    checksum: str
    variables: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestParams:
    bbox: tuple[float, float, float, float]
    start_date: date
    end_date: date
    variables: list[str] = field(default_factory=list)
    study_area_id: int | None = None
    dest_dir: Path | None = None
    max_items: int = 60
    extra: dict[str, Any] = field(default_factory=dict)


ProgressFn = Callable[[float, str], None]


def _noop_progress(_fraction: float, _message: str) -> None:
    return None


class ProviderAdapter(ABC):
    """Contract every data-source adapter implements.

    ``test_connection`` performs a real, cheap request against the provider;
    ``discover`` lists items without downloading payloads; ``fetch`` stores
    the data and returns storage-relative artifacts.
    """

    key: str = ""
    label: str = ""
    category: str = ""
    description: str = ""
    product_type: str = ""               # human product label stored on datasets
    auth_required: bool = False
    adapter_status: str = "untested"     # tested | untested (honest capability flag)
    verification_note: str = ""          # what was verified, and when
    default_variables: list[dict] = []
    capabilities: dict[str, Any] = {}

    def __init__(self, client: httpx.Client | None = None, config: dict[str, Any] | None = None):
        self.client = client or get_http_client()
        self.config: dict[str, Any] = dict(config or {})

    # -- API ---------------------------------------------------------------
    @abstractmethod
    def test_connection(self) -> TestResult: ...

    @abstractmethod
    def discover(self, params: IngestParams) -> list[DiscoveredItem]: ...

    @abstractmethod
    def fetch(self, params: IngestParams, item: DiscoveredItem, progress: ProgressFn = _noop_progress) -> FetchedArtifact: ...

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "category": self.category,
            "description": self.description,
            "product_type": self.product_type,
            "auth_method": "none" if not self.auth_required else "bearer_token",
            "auth_required": self.auth_required,
            "variables": list(self.default_variables),
            "capabilities": dict(self.capabilities),
            "adapter_status": self.adapter_status,
            "verification_note": self.verification_note,
        }


class ProviderError(RuntimeError):
    """Recoverable provider failure (network, HTTP status, missing asset)."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

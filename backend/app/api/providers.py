"""Provider catalogue (what the configured adapters can ingest)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.serializers import provider_out
from app.core.deps import require_permissions
from app.core.enums import AUTH_METHODS, DATA_SOURCE_CATEGORIES
from app.core.errors import NotFoundError
from app.providers import describe_adapters, known_provider_keys
from app.schemas.research import ProviderOut

router = APIRouter(prefix="/providers", tags=["providers"])

Read = Annotated[set[str], Depends(require_permissions("research.datasets.read"))]


@router.get("", response_model=list[ProviderOut])
def list_providers(_perms: Read) -> list[ProviderOut]:
    return [provider_out(raw) for raw in describe_adapters()]


@router.get("/catalogue")
def catalogue(_perms: Read) -> dict:
    return {
        "categories": [{"value": key, "label": label} for key, label in DATA_SOURCE_CATEGORIES],
        "auth_methods": [{"value": key, "label": label} for key, label in AUTH_METHODS],
    }


@router.get("/{key}", response_model=ProviderOut)
def get_provider(key: str, _perms: Read) -> ProviderOut:
    for raw in describe_adapters():
        if raw["key"] == key:
            return provider_out(raw)
    raise NotFoundError(
        f"No provider adapter registered for '{key}'",
        details={"available": known_provider_keys()},
    )

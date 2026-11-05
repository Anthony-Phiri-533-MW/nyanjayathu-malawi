"""Pydantic schemas shared helpers: pagination and UTC serialisation."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, Field, PlainSerializer

T = TypeVar("T")


def _aware_utc(v: object) -> datetime | None:
    if v is None or isinstance(v, datetime):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v  # type: ignore[return-value]
    raise TypeError("expected datetime")


UTCDateTime = Annotated[
    datetime,
    BeforeValidator(_aware_utc),
    PlainSerializer(lambda d: d.isoformat().replace("+00:00", "Z") if d else None, return_type=str | None),
]


class Page(BaseModel, Generic[T]):  # noqa: UP046 (Generic[T] keeps runtime subscripting working for Pydantic)
    items: list[T]
    total: int
    page: int = Field(ge=1)
    size: int = Field(ge=1)
    pages: int


class Message(BaseModel):
    message: str


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=200)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class AssistantInterpretRequest(BaseModel):
    question: str
    metrics: list[dict] = []

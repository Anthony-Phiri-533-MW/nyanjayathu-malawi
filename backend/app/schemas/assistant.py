"""Request and response models for dashboard metric explanations."""
from __future__ import annotations

from pydantic import BaseModel, Field


class DashboardMetric(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    value: str = Field(max_length=300)


class AssistantInterpretRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    metrics: list[DashboardMetric] = Field(max_length=30)


class AssistantInterpretResponse(BaseModel):
    answer: str

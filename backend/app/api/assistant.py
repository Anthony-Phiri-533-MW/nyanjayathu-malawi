"""Authenticated dashboard assistant endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser
from app.schemas.assistant import AssistantInterpretRequest, AssistantInterpretResponse
from app.services import assistant as service

router = APIRouter(prefix="/assistant", tags=["dashboard assistant"])


@router.post("/interpret", response_model=AssistantInterpretResponse)
async def interpret_dashboard_metrics(
    payload: AssistantInterpretRequest,
    _actor: CurrentUser,
) -> AssistantInterpretResponse:
    return AssistantInterpretResponse(answer=await service.interpret_metrics(payload))

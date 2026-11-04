"""Server-side adapter for the configured OpenAI-compatible dashboard assistant."""
from __future__ import annotations

import json
import logging

import httpx

from app.core.config import settings
from app.core.errors import ServiceUnavailableError, UpstreamServiceError
from app.schemas.assistant import AssistantInterpretRequest

log = logging.getLogger("lakewatch.assistant")

_SYSTEM_PROMPT = (
    "You are LakeWatch's environmental data explainer. Explain the supplied dashboard metrics "
    "in plain language for a non-specialist. Use only the supplied metrics and their labels. "
    "Do not invent trends, causes, forecasts, or certainty. Clearly distinguish recorded forecasts "
    "from observed measurements, identify proxy or unvalidated values when shown, and state when "
    "there is not enough information to answer. Keep the answer concise and do not give emergency "
    "or policy instructions."
)


async def interpret_metrics(payload: AssistantInterpretRequest) -> str:
    base_url = (settings.ai_base_url or "").strip().rstrip("/")
    model = (settings.ai_model or "").strip()
    if not base_url or not model:
        raise ServiceUnavailableError(
            "The AI assistant is not configured. Set AI_BASE_URL and AI_MODEL on the backend."
        )

    request_body = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 500,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": payload.question,
                        "dashboard_metrics": [
                            metric.model_dump() for metric in payload.metrics
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    headers = {"Accept": "application/json"}
    if settings.ai_api_key:
        headers["Authorization"] = f"Bearer {settings.ai_api_key}"

    try:
        async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                json=request_body,
                headers=headers,
            )
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        log.warning("Configured AI provider timed out")
        raise UpstreamServiceError("The AI provider timed out. Please try again.") from exc
    except httpx.HTTPStatusError as exc:
        log.warning("Configured AI provider returned HTTP %s", exc.response.status_code)
        raise UpstreamServiceError(
            "The AI provider rejected the request. Check its model and credentials."
        ) from exc
    except httpx.RequestError as exc:
        log.warning("Configured AI provider request failed (%s)", type(exc).__name__)
        raise UpstreamServiceError("The AI provider could not be reached.") from exc

    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        log.warning("Configured AI provider returned an invalid completion response")
        raise UpstreamServiceError("The AI provider returned an unreadable response.") from exc
    if not isinstance(content, str) or not content.strip():
        raise UpstreamServiceError("The AI provider returned an empty explanation.")
    return content.strip()

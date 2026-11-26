"""Fixed-window rate limiter middleware.

Tracks request counts per client IP and path prefix in memory.  Intended for
single-node deployments (the same constraint as the DB-backed job queue).
Public (anonymous) endpoints are limited more tightly than authenticated ones.
"""
from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.errors import RateLimitError


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Fixed-window rate limiter.

    Window key: ``(client_ip, path_prefix)`` where path_prefix is ``public``
    for ``/api/v1/public/*`` and ``api`` for everything else.
    """

    def __init__(self, app: Callable) -> None:
        super().__init__(app)
        self._counters: dict[tuple[str, str], list[float]] = defaultdict(list)

    def _client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        client = request.client
        return client.host if client else "unknown"

    def _path_prefix(self, request: Request) -> str:
        path = request.url.path
        if path.startswith("/api/v1/public/"):
            return "public"
        return "api"

    def _check(self, key: tuple[str, str], max_requests: int, window_seconds: int) -> None:
        now = time.time()
        window = self._counters[key]
        # Drop timestamps outside the current window.
        self._counters[key] = [t for t in window if now - t < window_seconds]
        if len(self._counters[key]) >= max_requests:
            retry_after = int(window_seconds - (now - self._counters[key][0])) + 1
            raise RateLimitError(
                f"Rate limit exceeded: {max_requests} requests per {window_seconds}s.",
                details={"retry_after_seconds": max(retry_after, 1)},
            )
        self._counters[key].append(now)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not settings.rate_limit_public_enabled or settings.environment == "test":
            return await call_next(request)

        ip = self._client_ip(request)
        prefix = self._path_prefix(request)
        key = (ip, prefix)

        if prefix == "public":
            self._check(
                key,
                settings.rate_limit_public_requests,
                settings.rate_limit_public_window_seconds,
            )
        else:
            self._check(
                key,
                settings.rate_limit_authenticated_requests,
                settings.rate_limit_authenticated_window_seconds,
            )

        return await call_next(request)

"""Sliding-window rate limiter Starlette middleware.

Limits each client IP to ``requests_per_minute`` requests within any
60-second window.  Uses a ``collections.deque`` per IP — timestamps older
than 60 s are evicted before each check so the window slides naturally.

Health endpoints (``/health/``) and the Prometheus metrics endpoint
(``/metrics``) are exempted so probes and scrapers never consume quota.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.core.exceptions import RateLimitError

_WINDOW_SECONDS = 60
_EXEMPT_PREFIXES = ("/health", "/metrics")


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Per-IP sliding-window rate limiter.

    Args:
        app: The ASGI application to wrap.
        requests_per_minute: Maximum requests allowed per 60-second window.
    """

    def __init__(self, app, requests_per_minute: int) -> None:
        super().__init__(app)
        self._rpm = requests_per_minute
        self._windows: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next) -> Response:
        if any(request.url.path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        ip = forwarded or (request.client.host if request.client else "unknown")
        now = time.time()
        window = self._windows[ip]

        # Evict timestamps that have left the 60-second window
        while window and now - window[0] > _WINDOW_SECONDS:
            window.popleft()

        if len(window) >= self._rpm:
            retry_after = int(_WINDOW_SECONDS - (now - window[0])) + 1
            raise RateLimitError(retry_after=retry_after)

        window.append(now)
        return await call_next(request)

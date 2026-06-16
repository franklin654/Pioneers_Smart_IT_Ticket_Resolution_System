"""Sliding-window in-process rate limiter.

Checks X-Forwarded-For first (audit fix M7) so clients behind a reverse proxy
are rate-limited by their real IP, not the proxy's IP.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from src.core.config import get_settings
from src.core.logging import get_logger

logger = get_logger(__name__)

# {ip: deque of request timestamps (float)}
_windows: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def rate_limit(request: Request) -> None:
    settings = get_settings()
    limit = settings.rate_limit_per_minute
    window = 60.0
    now = time.monotonic()
    ip = _client_ip(request)
    dq = _windows[ip]

    # Evict timestamps older than the window
    while dq and now - dq[0] > window:
        dq.popleft()

    if len(dq) >= limit:
        logger.warning("rate_limit_exceeded", ip=ip, requests_in_window=len(dq))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again later.",
        )

    dq.append(now)

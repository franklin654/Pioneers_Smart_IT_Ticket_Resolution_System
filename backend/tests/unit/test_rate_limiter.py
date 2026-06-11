"""Unit tests for RateLimiterMiddleware (src/api/middleware/rate_limiter.py).

Tests the sliding-window logic, per-IP isolation, health endpoint exemption,
and the retry_after calculation — all without a real HTTP server.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.middleware.rate_limiter import RateLimiterMiddleware, _WINDOW_SECONDS
from src.core.exceptions import RateLimitError


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_middleware(rpm: int = 3) -> RateLimiterMiddleware:
    return RateLimiterMiddleware(app=AsyncMock(), requests_per_minute=rpm)


def _make_request(path: str = "/api/v1/tickets/", ip: str = "1.2.3.4") -> MagicMock:
    req = MagicMock()
    req.url.path = path
    req.client = MagicMock()
    req.client.host = ip
    req.headers = {}  # no X-Forwarded-For header; rate limiter falls back to client.host
    return req


async def _call(middleware: RateLimiterMiddleware, request, call_next=None):
    if call_next is None:
        call_next = AsyncMock(return_value=MagicMock())
    return await middleware.dispatch(request, call_next)


# ── Within-window requests allowed ────────────────────────────────────────────


class TestWithinWindow:
    async def test_first_request_allowed(self):
        mw = _make_middleware(rpm=3)
        await _call(mw, _make_request())

    async def test_requests_up_to_limit_allowed(self):
        mw = _make_middleware(rpm=3)
        req = _make_request()
        for _ in range(3):
            await _call(mw, req)  # no exception

    async def test_exceeding_limit_raises_rate_limit_error(self):
        mw = _make_middleware(rpm=3)
        req = _make_request()
        for _ in range(3):
            await _call(mw, req)
        with pytest.raises(RateLimitError):
            await _call(mw, req)


# ── Per-IP isolation ──────────────────────────────────────────────────────────


class TestPerIPIsolation:
    async def test_different_ips_have_independent_counters(self):
        mw = _make_middleware(rpm=2)
        req_a = _make_request(ip="1.1.1.1")
        req_b = _make_request(ip="2.2.2.2")

        # Exhaust IP A
        await _call(mw, req_a)
        await _call(mw, req_a)
        with pytest.raises(RateLimitError):
            await _call(mw, req_a)

        # IP B still has quota
        await _call(mw, req_b)  # should not raise

    async def test_ip_a_block_does_not_block_ip_b(self):
        mw = _make_middleware(rpm=1)
        await _call(mw, _make_request(ip="10.0.0.1"))
        # Second request from same IP blocked
        with pytest.raises(RateLimitError):
            await _call(mw, _make_request(ip="10.0.0.1"))
        # Different IP still fine
        await _call(mw, _make_request(ip="10.0.0.2"))


# ── Window reset ──────────────────────────────────────────────────────────────


class TestWindowReset:
    async def test_old_timestamps_evicted_after_window(self):
        mw = _make_middleware(rpm=2)
        req = _make_request()

        now = time.time()
        # Manually inject two old timestamps (outside the 60s window)
        mw._windows[req.client.host].append(now - _WINDOW_SECONDS - 5)
        mw._windows[req.client.host].append(now - _WINDOW_SECONDS - 3)

        # Both old entries should be evicted — new request goes through
        await _call(mw, req)  # should NOT raise


# ── Health endpoint exemption ─────────────────────────────────────────────────


class TestHealthExemption:
    async def test_health_liveness_exempt(self):
        mw = _make_middleware(rpm=1)
        req = _make_request(path="/health/live")
        # Exhaust quota on a normal path first (ensure counter is maxed)
        await _call(mw, _make_request(ip=req.client.host))
        # health path should still pass (exempt from rate limiting)
        for _ in range(10):
            await _call(mw, req)

    async def test_health_ready_exempt(self):
        mw = _make_middleware(rpm=1)
        req = _make_request(path="/health/ready")
        await _call(mw, _make_request(ip=req.client.host))
        await _call(mw, req)  # should not raise


# ── retry_after in error ──────────────────────────────────────────────────────


class TestRetryAfter:
    async def test_rate_limit_error_contains_retry_after(self):
        mw = _make_middleware(rpm=1)
        req = _make_request()
        await _call(mw, req)
        with pytest.raises(RateLimitError) as exc_info:
            await _call(mw, req)
        assert exc_info.value.detail["retry_after_seconds"] > 0

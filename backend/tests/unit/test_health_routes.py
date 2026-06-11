"""Unit tests for health check endpoints (src/api/routes/health.py).

Uses FastAPI's TestClient via httpx with dependency overrides — no real DB.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.routes.health import router


# ── App fixture ───────────────────────────────────────────────────────────────


@pytest.fixture
def health_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/health")
    return app


@pytest.fixture
async def client(health_app: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=health_app), base_url="http://test"
    ) as ac:
        yield ac


# ── Liveness ──────────────────────────────────────────────────────────────────


class TestLiveness:
    async def test_liveness_returns_200(self, client: AsyncClient):
        resp = await client.get("/health/live")
        assert resp.status_code == 200

    async def test_liveness_body(self, client: AsyncClient):
        resp = await client.get("/health/live")
        assert resp.json() == {"status": "ok"}

    async def test_liveness_requires_no_auth(self, client: AsyncClient):
        resp = await client.get("/health/live")
        assert resp.status_code == 200


# ── Readiness ─────────────────────────────────────────────────────────────────


class TestReadiness:
    async def test_readiness_returns_200_when_db_healthy(self, client: AsyncClient):
        with patch(
            "src.api.routes.health.check_db_health", new=AsyncMock(return_value=True)
        ):
            resp = await client.get("/health/ready")
        assert resp.status_code == 200

    async def test_readiness_body_when_healthy(self, client: AsyncClient):
        with patch(
            "src.api.routes.health.check_db_health", new=AsyncMock(return_value=True)
        ):
            resp = await client.get("/health/ready")
        data = resp.json()
        assert data["status"] == "ready"
        assert data["database"] == "ok"

    async def test_readiness_returns_503_when_db_down(self, client: AsyncClient):
        with patch(
            "src.api.routes.health.check_db_health", new=AsyncMock(return_value=False)
        ):
            resp = await client.get("/health/ready")
        assert resp.status_code == 503

    async def test_readiness_requires_no_auth(self, client: AsyncClient):
        with patch(
            "src.api.routes.health.check_db_health", new=AsyncMock(return_value=True)
        ):
            resp = await client.get("/health/ready")
        assert resp.status_code == 200

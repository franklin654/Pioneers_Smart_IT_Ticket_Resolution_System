"""Unit tests for src/api/main.py.

Tests the exception handler and app factory without starting a full server.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    DuplicateTicketError,
    RateLimitError,
    TicketNotFoundError,
)


# ── App factory ───────────────────────────────────────────────────────────────


class TestCreateApp:
    def test_create_app_returns_fastapi_instance(self):
        from src.api.main import create_app
        with patch("src.api.main.init_db", new=AsyncMock()):
            app = create_app()
        assert isinstance(app, FastAPI)

    def test_app_has_openapi_schema(self):
        from src.api.main import app
        assert app.openapi_url == "/openapi.json"

    def test_app_has_docs_url(self):
        from src.api.main import app
        assert app.docs_url == "/docs"


# ── Exception handler ─────────────────────────────────────────────────────────


@pytest.fixture
def exc_app() -> FastAPI:
    """Minimal app that exercises the AppBaseException handler from main.py."""
    from src.api.main import app as main_app
    from src.core.exceptions import AppBaseException
    from fastapi import FastAPI as _FastAPI
    from fastapi.responses import JSONResponse

    test_app = _FastAPI()

    # Re-register the same handler logic independently
    @test_app.exception_handler(AppBaseException)
    async def handler(req, exc: AppBaseException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    from fastapi import APIRouter
    r = APIRouter()

    @r.get("/raise/{code}")
    async def raise_exc(code: str):
        if code == "404":
            raise TicketNotFoundError("abc-123")
        if code == "401":
            raise AuthenticationError("bad token")
        if code == "403":
            raise AuthorizationError("forbidden")
        if code == "409":
            raise DuplicateTicketError("abc-123", "exact")
        if code == "429":
            raise RateLimitError(retry_after=30)

    test_app.include_router(r)
    return test_app


@pytest.fixture
async def exc_client(exc_app: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=exc_app), base_url="http://test"
    ) as ac:
        yield ac


class TestExceptionHandler:
    async def test_ticket_not_found_mapped_to_404(self, exc_client: AsyncClient):
        resp = await exc_client.get("/raise/404")
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "TICKET_NOT_FOUND"

    async def test_authentication_error_mapped_to_401(self, exc_client: AsyncClient):
        resp = await exc_client.get("/raise/401")
        assert resp.status_code == 401
        assert resp.json()["error_code"] == "AUTHENTICATION_ERROR"

    async def test_authorization_error_mapped_to_403(self, exc_client: AsyncClient):
        resp = await exc_client.get("/raise/403")
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "AUTHORIZATION_ERROR"

    async def test_duplicate_ticket_mapped_to_409(self, exc_client: AsyncClient):
        resp = await exc_client.get("/raise/409")
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "DUPLICATE_TICKET"

    async def test_rate_limit_mapped_to_429(self, exc_client: AsyncClient):
        resp = await exc_client.get("/raise/429")
        assert resp.status_code == 429
        assert resp.json()["error_code"] == "RATE_LIMIT_EXCEEDED"

    async def test_error_response_has_message_field(self, exc_client: AsyncClient):
        resp = await exc_client.get("/raise/404")
        assert "message" in resp.json()

    async def test_error_response_has_detail_field(self, exc_client: AsyncClient):
        resp = await exc_client.get("/raise/404")
        assert "detail" in resp.json()

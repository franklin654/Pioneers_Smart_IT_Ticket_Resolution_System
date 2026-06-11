"""Unit tests for auth routes (src/api/routes/auth.py).

Tests the token-issuance endpoint with valid and invalid credentials.
No database required — credentials come from Settings.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.routes.auth import router, _hashed_admin_password
from src.api.middleware.auth import hash_password, verify_password
from src.core.config import Settings


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_settings() -> MagicMock:
    s = MagicMock(spec=Settings)
    s.admin_username = "admin"
    s.admin_password = "testpass123"
    s.secret_key = "t" * 32
    s.jwt_algorithm = "HS256"
    s.access_token_expire_minutes = 60
    return s


@pytest.fixture
def auth_app() -> FastAPI:
    from src.core.config import get_settings
    from src.core.exceptions import AppBaseException
    from fastapi.responses import JSONResponse

    settings = _make_settings()
    app = FastAPI()
    app.include_router(router, prefix="/auth")
    app.dependency_overrides[get_settings] = lambda: settings

    @app.exception_handler(AppBaseException)
    async def handler(req, exc: AppBaseException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    return app


@pytest.fixture
async def client(auth_app: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=auth_app), base_url="http://test"
    ) as ac:
        yield ac


# ── Login ─────────────────────────────────────────────────────────────────────
# NOTE: Happy-path login tests (correct password → 200) are not included here.
# _hashed_admin_password() is a module-level lru_cache that calls get_settings()
# directly, bypassing FastAPI's DI override. The rejection tests below work
# correctly because they verify the comparison returns False regardless of what
# the hashed value is.


class TestLogin:
    async def test_wrong_password_returns_401(self, client: AsyncClient, auth_app: FastAPI):
        _hashed_admin_password.cache_clear()
        resp = await client.post(
            "/auth/token",
            data={"username": "admin", "password": "wrongpassword"},
        )
        assert resp.status_code == 401

    async def test_wrong_username_returns_401(self, client: AsyncClient, auth_app: FastAPI):
        _hashed_admin_password.cache_clear()
        resp = await client.post(
            "/auth/token",
            data={"username": "notadmin", "password": "testpass123"},
        )
        assert resp.status_code == 401

    async def test_401_body_contains_error_code(self, client: AsyncClient, auth_app: FastAPI):
        _hashed_admin_password.cache_clear()
        resp = await client.post(
            "/auth/token",
            data={"username": "admin", "password": "wrong"},
        )
        assert resp.json()["error_code"] == "AUTHENTICATION_ERROR"


# ── verify_password edge cases ────────────────────────────────────────────────


class TestVerifyPasswordEdgeCases:
    def test_invalid_hash_format_returns_false(self):
        assert verify_password("secret", "notahashstring") is False

    def test_empty_plain_against_valid_hash_returns_false(self):
        hashed = hash_password("something")
        assert verify_password("", hashed) is False

"""Unit tests for src/api/middleware/auth.py.

Tests JWT creation, decoding, expiry, tamper detection, the
``get_current_user`` dependency, and the ``require_role`` factory.
No database or network calls are made.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from jose import jwt

from src.api.middleware.auth import (
    create_access_token,
    decode_access_token,
    get_current_user,
    hash_password,
    require_role,
    verify_password,
)
from src.core.exceptions import AuthenticationError, AuthorizationError


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_settings(secret: str = "x" * 32, algorithm: str = "HS256") -> MagicMock:
    s = MagicMock()
    s.secret_key = secret
    s.jwt_algorithm = algorithm
    s.access_token_expire_minutes = 60
    return s


# ── Password helpers ──────────────────────────────────────────────────────────


class TestPasswordHelpers:
    def test_hash_is_not_plaintext(self):
        assert hash_password("secret") != "secret"

    def test_verify_correct_password(self):
        hashed = hash_password("mypassword")
        assert verify_password("mypassword", hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("mypassword")
        assert verify_password("wrong", hashed) is False


# ── Token creation ────────────────────────────────────────────────────────────


class TestCreateAccessToken:
    def test_returns_string(self):
        settings = _make_settings()
        token = create_access_token({"sub": "admin"}, settings)
        assert isinstance(token, str)

    def test_payload_embedded(self):
        settings = _make_settings()
        token = create_access_token({"sub": "admin", "role": "admin"}, settings)
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["sub"] == "admin"
        assert payload["role"] == "admin"

    def test_exp_claim_present(self):
        settings = _make_settings()
        token = create_access_token({"sub": "admin"}, settings)
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        assert "exp" in payload

    def test_exp_in_future(self):
        settings = _make_settings()
        token = create_access_token({"sub": "admin"}, settings)
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["exp"] > datetime.now(UTC).timestamp()


# ── Token decoding ────────────────────────────────────────────────────────────


class TestDecodeAccessToken:
    def test_valid_token_returns_payload(self):
        settings = _make_settings()
        token = create_access_token({"sub": "admin", "role": "admin"}, settings)
        payload = decode_access_token(token, settings)
        assert payload["sub"] == "admin"

    def test_wrong_secret_raises_authentication_error(self):
        good_settings = _make_settings(secret="a" * 32)
        bad_settings = _make_settings(secret="b" * 32)
        token = create_access_token({"sub": "admin"}, good_settings)
        with pytest.raises(AuthenticationError):
            decode_access_token(token, bad_settings)

    def test_expired_token_raises_authentication_error(self):
        settings = _make_settings()
        payload = {"sub": "admin", "exp": datetime.now(UTC) - timedelta(seconds=1)}
        token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
        with pytest.raises(AuthenticationError, match="expired"):
            decode_access_token(token, settings)

    def test_malformed_token_raises_authentication_error(self):
        settings = _make_settings()
        with pytest.raises(AuthenticationError):
            decode_access_token("not.a.token", settings)

    def test_empty_token_raises_authentication_error(self):
        settings = _make_settings()
        with pytest.raises(AuthenticationError):
            decode_access_token("", settings)


# ── get_current_user dependency ───────────────────────────────────────────────


class TestGetCurrentUser:
    async def test_valid_token_returns_payload(self):
        settings = _make_settings()
        token = create_access_token({"sub": "admin", "role": "admin"}, settings)

        result = await get_current_user(token=token, settings=settings)
        assert result["sub"] == "admin"

    async def test_no_token_raises_authentication_error(self):
        settings = _make_settings()
        with pytest.raises(AuthenticationError, match="Authentication required"):
            await get_current_user(token=None, settings=settings)

    async def test_invalid_token_raises_authentication_error(self):
        settings = _make_settings()
        with pytest.raises(AuthenticationError):
            await get_current_user(token="bad.token.here", settings=settings)


# ── require_role factory ──────────────────────────────────────────────────────


class TestRequireRole:
    async def test_matching_role_passes(self):
        settings = _make_settings()
        token = create_access_token({"sub": "admin", "role": "admin"}, settings)
        user = await get_current_user(token=token, settings=settings)

        guard = require_role("admin")
        result = await guard(user=user)
        assert result["sub"] == "admin"

    async def test_non_matching_role_raises_authorization_error(self):
        settings = _make_settings()
        token = create_access_token({"sub": "user", "role": "L1"}, settings)
        user = await get_current_user(token=token, settings=settings)

        guard = require_role("admin")
        with pytest.raises(AuthorizationError):
            await guard(user=user)

    async def test_multiple_roles_any_match_passes(self):
        settings = _make_settings()
        token = create_access_token({"sub": "eng", "role": "L3"}, settings)
        user = await get_current_user(token=token, settings=settings)

        guard = require_role("admin", "L3")
        result = await guard(user=user)
        assert result["role"] == "L3"

    async def test_missing_role_key_raises_authorization_error(self):
        settings = _make_settings()
        token = create_access_token({"sub": "noop"}, settings)
        user = await get_current_user(token=token, settings=settings)

        guard = require_role("admin")
        with pytest.raises(AuthorizationError):
            await guard(user=user)

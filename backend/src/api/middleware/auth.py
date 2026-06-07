"""JWT authentication helpers and FastAPI dependency functions.

Provides:
    - ``create_access_token`` — signs a JWT with exp claim
    - ``decode_access_token`` — validates and decodes a JWT
    - ``get_current_user``    — FastAPI dependency: extracts + validates Bearer token
    - ``require_role``        — role-guard dependency factory

Tokens are HS256-signed using ``settings.secret_key``.  Roles embedded in
the payload (``"role"``) drive RBAC; the ``require_role()`` factory builds
per-route guards without duplicating logic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import hashlib
import hmac
import os

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError, jwt

from src.core.config import Settings, get_settings
from src.core.exceptions import AuthenticationError, AuthorizationError

if TYPE_CHECKING:
    pass

_PBKDF2_ITERATIONS = 260_000  # OWASP 2023 recommendation for PBKDF2-SHA256
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


# ── Password helpers ──────────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    """Return PBKDF2-SHA256 hash of *plain* with a random salt.

    Format: ``<hex-salt>$<hex-digest>`` — both parts needed for verification.
    Uses stdlib ``hashlib`` to avoid bcrypt version compatibility issues.
    """
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", plain.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS
    ).hex()
    return f"{salt}${digest}"


def verify_password(plain: str, hashed: str) -> bool:
    """Return True when *plain* matches *hashed* (constant-time comparison).

    Args:
        plain: Plaintext password from the login form.
        hashed: Hash string previously produced by :func:`hash_password`.
    """
    try:
        salt, digest = hashed.split("$", 1)
    except ValueError:
        return False
    new_digest = hashlib.pbkdf2_hmac(
        "sha256", plain.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS
    ).hex()
    return hmac.compare_digest(new_digest, digest)


# ── Token helpers ─────────────────────────────────────────────────────────────


def create_access_token(data: dict, settings: Settings) -> str:
    """Encode a JWT with an ``exp`` claim.

    Args:
        data: Payload to embed (e.g. ``{"sub": "admin", "role": "admin"}``).
        settings: Application settings (provides secret key and algorithm).

    Returns:
        Signed JWT string.
    """
    payload = data.copy()
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload["exp"] = expire
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> dict:
    """Decode and validate a JWT.

    Args:
        token: JWT string from the Authorization header.
        settings: Application settings (provides secret key and algorithm).

    Returns:
        Decoded payload dict.

    Raises:
        AuthenticationError: If the token is invalid, expired, or tampered.
    """
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except ExpiredSignatureError:
        raise AuthenticationError("Token has expired")
    except JWTError:
        raise AuthenticationError("Invalid token")


# ── FastAPI dependencies ───────────────────────────────────────────────────────


async def get_current_user(
    token: str | None = Depends(_oauth2_scheme),
    settings: Settings = Depends(get_settings),
) -> dict:
    """FastAPI dependency: extract and validate Bearer token.

    Returns the decoded JWT payload on success.

    Raises:
        AuthenticationError: If no token is provided or validation fails.
    """
    if not token:
        raise AuthenticationError("Authentication required")
    return decode_access_token(token, settings)


def require_role(*roles: str):
    """Return a FastAPI dependency that enforces role membership.

    Args:
        *roles: One or more role strings; the current user must match one.

    Returns:
        An async dependency function that yields the user payload or raises
        :class:`~src.core.exceptions.AuthorizationError`.

    Example::

        @router.delete("/{id}")
        async def delete(_: dict = Depends(require_role("admin", "L3"))):
            ...
    """
    async def _guard(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise AuthorizationError(
                f"Role '{user.get('role')}' is not permitted. Required: {list(roles)}"
            )
        return user

    return _guard

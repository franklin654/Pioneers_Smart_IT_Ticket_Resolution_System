"""JWT authentication middleware and dependency.

Short-lived access tokens (≤15 min) are validated on every protected request.
Refresh tokens live in HttpOnly cookies and are rotated on each /auth/refresh
call — v1 never implemented refresh rotation (audit fix).

Token validation checks: signature, expiry, issuer, audience, token_type claim.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from src.core.config import get_settings
from src.core.logging import get_logger

logger = get_logger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")

_ISSUER = "ticketiq"
_AUDIENCE = "ticketiq-api"


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def create_access_token(username: str) -> tuple[str, int]:
    settings = get_settings()
    expire = _now() + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": username,
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "exp": expire,
        "iat": _now(),
        "jti": str(uuid.uuid4()),
        "token_type": "access",
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, settings.access_token_expire_minutes * 60


def create_refresh_token(username: str) -> str:
    settings = get_settings()
    expire = _now() + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "sub": username,
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "exp": expire,
        "iat": _now(),
        "jti": str(uuid.uuid4()),
        "token_type": "refresh",
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _decode_token(token: str, expected_type: str) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer=_ISSUER,
            audience=_AUDIENCE,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired.")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}"
        )
    if payload.get("token_type") != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Expected {expected_type} token.",
        )
    return payload


def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> str:
    payload = _decode_token(token, "access")
    username: str | None = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
    return username


def decode_refresh_cookie(refresh_token: Annotated[str | None, Cookie()] = None) -> str:
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token cookie."
        )
    payload = _decode_token(refresh_token, "refresh")
    username: str | None = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
    return username


CurrentUser = Annotated[str, Depends(get_current_user)]

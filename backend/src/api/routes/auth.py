"""Authentication routes.

Provides a single token-issuance endpoint following the OAuth2 Password Flow.
Credentials are validated against static values in ``Settings`` — no user
table required for the hackathon demo.

Endpoint:
    POST /api/v1/auth/token  — form body: username + password → TokenResponse
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from src.api.middleware.auth import create_access_token, hash_password, verify_password
from src.core.config import Settings, get_settings
from src.core.exceptions import AuthenticationError

router = APIRouter(tags=["auth"])


class TokenResponse(BaseModel):
    """JWT token returned after successful authentication."""

    access_token: str
    token_type: str = "bearer"


@router.post("/token", response_model=TokenResponse)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Issue a JWT for valid credentials.

    Accepts ``application/x-www-form-urlencoded`` with ``username`` and
    ``password`` fields (OAuth2 password flow).  The Swagger UI Authorize
    button uses this endpoint automatically.

    Returns:
        :class:`TokenResponse` containing the signed JWT.

    Raises:
        AuthenticationError: If credentials are invalid (mapped to HTTP 401).
    """
    username_ok = form.username == settings.admin_username
    password_ok = verify_password(form.password, _hashed_admin_password())

    if not (username_ok and password_ok):
        raise AuthenticationError("Invalid username or password")

    token = create_access_token(
        {"sub": form.username, "role": "admin"},
        settings,
    )
    return TokenResponse(access_token=token)


@lru_cache(maxsize=1)
def _hashed_admin_password() -> str:
    """Stable hash of the admin password — computed once and cached per process."""
    return hash_password(get_settings().admin_password)

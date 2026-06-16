"""Auth routes: /token (login) and /refresh (rotation — new in v2)."""

from __future__ import annotations

from typing import Annotated

import bcrypt
from fastapi import APIRouter, Depends, Form, HTTPException, Response, status

from src.api.envelope import ok
from src.api.middleware.auth import (
    CurrentUser,
    create_access_token,
    create_refresh_token,
    decode_refresh_cookie,
)
from src.core.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE_NAME = "refresh_token"


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=settings.refresh_token_expire_days * 86_400,
        path="/api/v1/auth/refresh",
    )


def _verify_admin(username: str, password: str) -> bool:
    settings = get_settings()
    if username != settings.admin_username:
        return False
    stored = settings.admin_password
    # Support both bcrypt hashes and plain-text dev passwords
    if stored.startswith("$2"):
        return bcrypt.checkpw(password.encode(), stored.encode())
    return password == stored


@router.post("/token")
async def login(
    response: Response,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> dict:
    if not _verify_admin(username, password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token, expires_in = create_access_token(username)
    refresh_token = create_refresh_token(username)
    _set_refresh_cookie(response, refresh_token)

    return ok({"access_token": access_token, "token_type": "bearer", "expires_in": expires_in})


@router.post("/refresh")
async def refresh(
    response: Response,
    username: Annotated[str, Depends(decode_refresh_cookie)],
) -> dict:
    access_token, expires_in = create_access_token(username)
    new_refresh = create_refresh_token(username)
    _set_refresh_cookie(response, new_refresh)

    return ok({"access_token": access_token, "token_type": "bearer", "expires_in": expires_in})


@router.post("/logout")
async def logout(response: Response, _: CurrentUser) -> dict:
    response.delete_cookie(_COOKIE_NAME, path="/api/v1/auth/refresh")
    return ok({"message": "Logged out."})

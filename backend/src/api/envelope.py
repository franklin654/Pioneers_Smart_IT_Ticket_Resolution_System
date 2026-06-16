"""Standard response envelope (CLAUDE.md backend §4.3).

Every endpoint returns one of:
  {"data": ..., "meta": ...}   — success (single or collection)
  {"error": {...}}             — failure

Never mix: a 200 with an error payload is forbidden.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    field: str | None = None
    issue: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] | list[dict[str, Any]] = []


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class Meta(BaseModel):
    total: int
    offset: int
    limit: int


def ok(data: Any) -> dict[str, Any]:
    return {"data": data}


def collection(data: list[Any], *, total: int, offset: int, limit: int) -> dict[str, Any]:
    return {"data": data, "meta": {"total": total, "offset": offset, "limit": limit}}


def error(code: str, message: str, details: list[Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or []}}

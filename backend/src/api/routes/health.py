"""Health and metrics endpoints (audit fix L5 — Pydantic response model)."""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from src.api.envelope import ok
from src.core.config import get_settings
from src.db.database import get_engine

router = APIRouter(prefix="/health", tags=["health"])


class HealthStatus(BaseModel):
    status: str
    version: str | None = None


@router.get("/live")
async def liveness() -> dict:
    return ok({"status": "ok"})


@router.get("/ready")
async def readiness() -> dict:
    """Check DB connectivity before reporting ready."""
    try:
        async with get_engine().connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    if not db_ok:
        return Response(
            content='{"error":{"code":"NOT_READY","message":"Database unavailable."}}',
            status_code=503,
            media_type="application/json",
        )

    settings = get_settings()
    return ok({"status": "ok", "version": settings.app_version})


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus scrape endpoint — no auth required."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

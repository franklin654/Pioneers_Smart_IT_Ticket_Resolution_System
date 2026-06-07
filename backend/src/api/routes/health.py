"""Health check endpoints.

Provides two endpoints used by load balancers, Docker health checks, and
Kubernetes probes:

    GET /health/live   — liveness:  always 200 if the process is up
    GET /health/ready  — readiness: 200 only if the database is reachable

These routes are exempt from authentication and rate limiting.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.db.database import check_db_health

router = APIRouter(tags=["health"])


class LivenessResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    database: str


@router.get("/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    """Liveness probe — confirms the process is running.

    Returns:
        :class:`LivenessResponse` with HTTP 200.
    """
    return LivenessResponse(status="ok")


@router.get("/ready", response_model=ReadinessResponse)
async def readiness() -> ReadinessResponse:
    """Readiness probe — confirms the database connection is alive.

    Returns:
        :class:`ReadinessResponse` with HTTP 200.

    Raises:
        HTTPException: 503 if the database is unreachable.
    """
    db_ok = await check_db_health()
    if not db_ok:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return ReadinessResponse(status="ready", database="ok")

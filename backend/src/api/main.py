"""FastAPI application entry point.

Start the server with::

    uvicorn src.api.main:app --reload

The lifespan hook initialises the database (idempotent) on startup.
All ``AppBaseException`` subclasses are mapped to consistent JSON error
responses via a global exception handler.

Route prefix: /api/v1
WebSocket:    /ws/tickets/{ticket_id}
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.middleware.rate_limiter import RateLimiterMiddleware
from src.api.routes import auth, health, metrics_route, resolutions, tickets
from src.api.websocket import ws_ticket_status
from src.core.config import get_settings
from src.core.exceptions import AppBaseException
from src.core.logging import get_logger
from src.db.database import engine, init_db
from src.monitoring.metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS_TOTAL

logger = get_logger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Run startup and shutdown hooks."""
    settings = get_settings()
    logger.info(
        "Starting %s v%s [%s]",
        settings.app_name,
        settings.app_version,
        settings.app_env,
    )
    await init_db()
    yield
    await engine.dispose()
    logger.info("Server shutdown complete")


# ── Application factory ───────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Returns:
        Configured :class:`FastAPI` instance ready for ``uvicorn``.
    """
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "AI-Powered Intelligent Ticket Routing & Resolution Agent — "
            "NASSCOM Hackathon, Trail Blazers"
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # ── Middleware (applied in reverse registration order) ────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )
    app.add_middleware(
        RateLimiterMiddleware,
        requests_per_minute=settings.rate_limit_per_minute,
    )

    # ── Metrics middleware (HTTP request tracking) ────────────────────────────
    _SKIP_METRICS = frozenset({"/metrics", "/health/live", "/health/ready"})

    @app.middleware("http")
    async def _metrics_middleware(request: Request, call_next):
        if request.url.path in _SKIP_METRICS:
            return await call_next(request)
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        path = request.url.path
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method,
            path=path,
            status_code=str(response.status_code),
        ).inc()
        HTTP_REQUEST_DURATION.labels(method=request.method, path=path).observe(duration)
        return response

    # ── Exception handlers ────────────────────────────────────────────────────
    @app.exception_handler(AppBaseException)
    async def app_exception_handler(
        request: Request, exc: AppBaseException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(),
        )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(auth.router, prefix="/api/v1/auth")
    app.include_router(tickets.router, prefix="/api/v1/tickets")
    app.include_router(resolutions.router, prefix="/api/v1/resolutions")
    app.include_router(health.router, prefix="/health")
    app.include_router(metrics_route.router)  # /metrics — no prefix

    # ── WebSocket ─────────────────────────────────────────────────────────────
    app.add_api_websocket_route(
        "/ws/tickets/{ticket_id}",
        ws_ticket_status,
    )

    return app


app = create_app()

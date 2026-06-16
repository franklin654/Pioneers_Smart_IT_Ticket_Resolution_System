"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.envelope import error
from src.api.routes import auth, health, resolutions, tickets
from src.api.websocket import router as ws_router
from src.core.config import get_settings
from src.core.exceptions import AppBaseException
from src.core.logging import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    logger.info(
        "startup",
        service="ticketiq-api",
        version=settings.app_version,
        environment=settings.environment,
    )
    yield
    logger.info("shutdown", service="ticketiq-api")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="TicketIQ API",
        version=settings.app_version,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=_lifespan,
    )

    # CORS — explicit allowlist only (audit fix M6)
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )

    # Global exception handler: domain exceptions → typed JSON
    @app.exception_handler(AppBaseException)
    async def _domain_exc_handler(request: Request, exc: AppBaseException) -> JSONResponse:
        logger.warning(
            "domain_exception",
            code=exc.code,
            message=exc.message,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=exc.http_status,
            content=error(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(Exception)
    async def _unhandled_exc_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error("INTERNAL_ERROR", "An unexpected error occurred."),
        )

    prefix = "/api/v1"
    app.include_router(auth.router, prefix=prefix)
    app.include_router(health.router, prefix=prefix)
    app.include_router(tickets.router, prefix=prefix)
    app.include_router(resolutions.router, prefix=prefix)
    app.include_router(ws_router)

    return app


app = create_app()

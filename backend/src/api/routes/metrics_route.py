"""Prometheus metrics exposition endpoint.

Exposes the standard ``/metrics`` path consumed by the Prometheus scraper
configured in ``docker/prometheus.yml``.

This route is mounted at the application root (no prefix) so that
Prometheus can reach it at ``http://api:8000/metrics``.  It is excluded
from the rate limiter and from the OpenAPI schema.
"""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["monitoring"])


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    """Return Prometheus text-format metrics for scraping."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

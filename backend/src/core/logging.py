"""Structured JSON logging.

CLAUDE.md backend §7: every log line is a JSON object with mandatory fields
(timestamp, level, service, traceId, spanId, environment) — never a free-form
interpolated string. `console.log`/`print`-equivalents are disallowed; this
module is the only sanctioned way to emit logs.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from src.core.config import get_settings

_TRACE_ID_KEY = "trace_id"
_SPAN_ID_KEY = "span_id"


def _add_service_context(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    event_dict.setdefault("service", settings.app_name)
    event_dict.setdefault("environment", settings.environment)
    event_dict.setdefault(_TRACE_ID_KEY, None)
    event_dict.setdefault(_SPAN_ID_KEY, None)
    return event_dict


def configure_logging() -> None:
    """Call once at process startup (`api/main.py` lifespan)."""
    settings = get_settings()

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level),
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
            _add_service_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.log_level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def bind_trace_context(trace_id: str | None, span_id: str | None = None) -> None:
    """Bind the current request's trace/span IDs so every subsequent log line
    in this context (and downstream calls) carries them. Cleared per-request
    by the caller (middleware) via `structlog.contextvars.clear_contextvars()`."""
    structlog.contextvars.bind_contextvars(**{_TRACE_ID_KEY: trace_id, _SPAN_ID_KEY: span_id})


def get_logger(name: str) -> structlog.types.FilteringBoundLogger:
    return structlog.get_logger(name)

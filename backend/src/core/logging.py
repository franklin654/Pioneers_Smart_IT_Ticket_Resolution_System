"""Structured JSON logging for the ticket routing application.

Each log record is emitted as a single-line JSON object with consistent
fields so downstream log aggregators (Loki, ELK, CloudWatch) can parse
and index them without additional configuration.

Standard fields per record:
    - ``timestamp``: ISO-8601 UTC datetime
    - ``level``: DEBUG / INFO / WARNING / ERROR / CRITICAL
    - ``service``: logger name (typically ``__name__`` of the module)
    - ``event``: the log message
    - ``ticket_id`` (optional): injected via ``LoggerAdapter``
    - ``trace_id`` (optional): distributed trace identifier
    - ``span_id`` (optional): span within a trace
    - ``metadata`` (optional): arbitrary structured dict
    - ``exception`` (optional): formatted traceback on error records

Usage::

    logger = get_logger(__name__)
    logger.info("Ticket ingested", extra={"ticket_id": "abc", "metadata": {"priority": 1}})
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class _JsonFormatter(logging.Formatter):
    """Formats each log record as a single-line JSON object."""

    # Fields to promote from ``extra`` into the top-level payload
    _EXTRA_FIELDS = ("ticket_id", "trace_id", "span_id", "metadata")

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": record.name,
            "event": record.getMessage(),
        }

        for field in self._EXTRA_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def get_logger(name: str) -> logging.Logger:
    """Return a JSON-structured logger for the given module name.

    Idempotent — calling this multiple times with the same ``name``
    returns the same logger without adding duplicate handlers.

    Args:
        name: Logger name, typically ``__name__`` of the calling module.

    Returns:
        A :class:`logging.Logger` that writes structured JSON to stdout.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # already configured; avoid duplicate handlers

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    return logger

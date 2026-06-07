"""WebSocket endpoint for live ticket status streaming.

Clients connect immediately after ticket ingestion and receive JSON events
as the ticket progresses through the processing pipeline.

Endpoint:
    WS /ws/tickets/{ticket_id}

Event schema:
    {"event": "status_changed", "status": "<TicketStatus.value>"}
    {"event": "done",           "status": "<terminal TicketStatus.value>"}
    {"event": "error",          "message": "<reason>"}

The handler polls the database every 2 seconds, sending a ``status_changed``
event only when the status actually changes.  On reaching a terminal state
it sends a ``done`` event and closes the connection cleanly.
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from src.core.logging import get_logger
from src.db.database import AsyncSessionLocal
from src.db.models import TicketStatus
from src.db.repositories.ticket_repo import TicketRepository

logger = get_logger(__name__)

_POLL_INTERVAL = 2  # seconds between DB checks
_TERMINAL_STATUSES = frozenset({
    TicketStatus.AUTO_RESOLVED,
    TicketStatus.ASSIGNED,
    TicketStatus.ESCALATED,
    TicketStatus.CLOSED,
})


async def ws_ticket_status(websocket: WebSocket, ticket_id: uuid.UUID) -> None:
    """Stream ticket status transitions over a WebSocket connection.

    Opens with the current status, then polls every 2 s and emits events
    only on status changes.  Closes automatically when a terminal status is
    reached or the client disconnects.

    Args:
        websocket: The WebSocket connection accepted by FastAPI.
        ticket_id: UUID of the ticket to monitor.
    """
    await websocket.accept()
    last_status: TicketStatus | None = None

    try:
        while True:
            async with AsyncSessionLocal() as session:
                repo = TicketRepository(session)
                ticket = await repo.get_by_id(ticket_id)

            if ticket is None:
                await websocket.send_json({
                    "event": "error",
                    "message": f"Ticket '{ticket_id}' not found",
                })
                break

            current_status: TicketStatus = ticket.status

            if current_status != last_status:
                await websocket.send_json({
                    "event": "status_changed",
                    "status": current_status.value,
                })
                last_status = current_status

            if current_status in _TERMINAL_STATUSES:
                await websocket.send_json({
                    "event": "done",
                    "status": current_status.value,
                })
                break

            await asyncio.sleep(_POLL_INTERVAL)

    except WebSocketDisconnect:
        logger.info(
            "WebSocket client disconnected",
            extra={"metadata": {"ticket_id": str(ticket_id)}},
        )
    except Exception as exc:
        logger.error(
            "WebSocket handler error",
            extra={"metadata": {"ticket_id": str(ticket_id), "error": str(exc)}},
        )
        try:
            await websocket.send_json({"event": "error", "message": "Internal error"})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass

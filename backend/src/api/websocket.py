"""WebSocket hub: per-ticket status push.

Clients connect to /ws/tickets/{ticket_id} and receive JSON events:
  {"event": "status_changed", "ticket_id": "...", "status": "..."}
  {"event": "done",           "ticket_id": "...", "status": "..."}
  {"event": "error",          "ticket_id": "...", "detail": "..."}
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from typing import Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from src.core.logging import get_logger
from src.db.database import session_scope
from src.db.models import TicketStatus
from src.db.repositories.ticket_repo import TicketRepository

logger = get_logger(__name__)

router = APIRouter(tags=["websocket"])

_TERMINAL_STATUSES = {
    TicketStatus.AUTO_RESOLVED,
    TicketStatus.ASSIGNED,
    TicketStatus.ESCALATED,
    # AWAITING_REVIEW is intentionally excluded — the pipeline resumes after
    # reclassification and the socket must stay open to stream those updates.
}

# {ticket_id: set of websocket connections}
_subscribers: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)
# Public broadcast function — imported by the orchestrator when a status changes
_broadcast_hooks: list[Callable] = []


async def broadcast(ticket_id: uuid.UUID, event: str, payload: dict) -> None:
    """Send an event to all WebSocket subscribers for a ticket."""
    sockets = list(_subscribers.get(ticket_id, set()))
    if not sockets:
        return
    message = {"event": event, "ticket_id": str(ticket_id), **payload}
    dead: list[WebSocket] = []
    for ws in sockets:
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_json(message)
            else:
                dead.append(ws)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _subscribers[ticket_id].discard(ws)


@router.websocket("/ws/tickets/{ticket_id}")
async def ticket_status_ws(websocket: WebSocket, ticket_id: uuid.UUID) -> None:
    await websocket.accept()
    _subscribers[ticket_id].add(websocket)
    logger.info("ws_connected", ticket_id=str(ticket_id))

    try:
        # Send current status immediately on connect
        async with session_scope() as session:
            repo = TicketRepository(session)
            ticket = await repo.get_by_id(ticket_id)

        if ticket is None:
            await websocket.send_json(
                {"event": "error", "ticket_id": str(ticket_id), "detail": "Ticket not found."}
            )
            await websocket.close(code=1008)
            return

        current_status = ticket.status
        await websocket.send_json(
            {
                "event": "status_changed",
                "ticket_id": str(ticket_id),
                "status": current_status.value,
            }
        )

        if current_status in _TERMINAL_STATUSES:
            await websocket.send_json(
                {"event": "done", "ticket_id": str(ticket_id), "status": current_status.value}
            )
            return

        # Poll until terminal status or client disconnects (max 5 min)
        poll_interval = 2.0
        max_polls = int(300 / poll_interval)

        for _ in range(max_polls):
            await asyncio.sleep(poll_interval)

            if websocket.client_state != WebSocketState.CONNECTED:
                break

            async with session_scope() as session:
                repo = TicketRepository(session)
                t = await repo.get_by_id(ticket_id)

            if t is None:
                await websocket.send_json(
                    {"event": "error", "ticket_id": str(ticket_id), "detail": "Ticket not found."}
                )
                break

            new_status = t.status
            if new_status != current_status:
                current_status = new_status
                await websocket.send_json(
                    {
                        "event": "status_changed",
                        "ticket_id": str(ticket_id),
                        "status": new_status.value,
                    }
                )

                if new_status in _TERMINAL_STATUSES:
                    await websocket.send_json(
                        {
                            "event": "done",
                            "ticket_id": str(ticket_id),
                            "status": new_status.value,
                        }
                    )
                    break

    except WebSocketDisconnect:
        logger.info("ws_disconnected", ticket_id=str(ticket_id))
    except Exception as exc:
        logger.error("ws_error", ticket_id=str(ticket_id), error=str(exc))
    finally:
        _subscribers[ticket_id].discard(websocket)
        if not _subscribers[ticket_id]:
            del _subscribers[ticket_id]

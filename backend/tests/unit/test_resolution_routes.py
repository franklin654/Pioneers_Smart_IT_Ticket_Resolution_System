"""Unit tests for resolution feedback endpoint (src/api/routes/resolutions.py).

Mocks ResolutionRepository — no real DB or auth.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.dependencies import get_resolution_repo
from src.api.middleware.auth import get_current_user
from src.api.routes.resolutions import router
from src.core.exceptions import AppBaseException, TicketNotFoundError
from src.db.models import FeedbackAction, RoutingDecision


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_resolution(ticket_id: uuid.UUID) -> MagicMock:
    r = MagicMock()
    r.id = uuid.uuid4()
    r.ticket_id = ticket_id
    r.routing_decision = RoutingDecision.AUTO_RESOLVED
    return r


@pytest.fixture
def app() -> FastAPI:
    _app = FastAPI()
    _app.include_router(router, prefix="/resolutions")
    _app.dependency_overrides[get_current_user] = lambda: {"sub": "agent1", "role": "L1"}

    from fastapi.responses import JSONResponse

    @_app.exception_handler(AppBaseException)
    async def handler(req, exc: AppBaseException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    return _app


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ── Feedback submission ───────────────────────────────────────────────────────


class TestSubmitFeedback:
    async def test_accepted_action_returns_204(self, app, client):
        ticket_id = uuid.uuid4()
        mock_repo = AsyncMock()
        mock_repo.get_by_ticket_id.return_value = _make_resolution(ticket_id)
        mock_repo.add_feedback.return_value = MagicMock()
        app.dependency_overrides[get_resolution_repo] = lambda: mock_repo

        resp = await client.post(
            f"/resolutions/{ticket_id}/feedback",
            json={"action": "accepted"},
        )
        assert resp.status_code == 204

    async def test_rejected_action_returns_204(self, app, client):
        ticket_id = uuid.uuid4()
        mock_repo = AsyncMock()
        mock_repo.get_by_ticket_id.return_value = _make_resolution(ticket_id)
        mock_repo.add_feedback.return_value = MagicMock()
        app.dependency_overrides[get_resolution_repo] = lambda: mock_repo

        resp = await client.post(
            f"/resolutions/{ticket_id}/feedback",
            json={"action": "rejected"},
        )
        assert resp.status_code == 204

    async def test_modified_action_with_text_returns_204(self, app, client):
        ticket_id = uuid.uuid4()
        mock_repo = AsyncMock()
        mock_repo.get_by_ticket_id.return_value = _make_resolution(ticket_id)
        mock_repo.add_feedback.return_value = MagicMock()
        app.dependency_overrides[get_resolution_repo] = lambda: mock_repo

        resp = await client.post(
            f"/resolutions/{ticket_id}/feedback",
            json={"action": "modified", "modified_resolution": "Updated fix steps."},
        )
        assert resp.status_code == 204

    async def test_feedback_persisted_via_repo(self, app, client):
        ticket_id = uuid.uuid4()
        mock_repo = AsyncMock()
        mock_repo.get_by_ticket_id.return_value = _make_resolution(ticket_id)
        mock_repo.add_feedback.return_value = MagicMock()
        app.dependency_overrides[get_resolution_repo] = lambda: mock_repo

        await client.post(
            f"/resolutions/{ticket_id}/feedback",
            json={"action": "accepted"},
        )
        mock_repo.add_feedback.assert_called_once()

    async def test_no_resolution_returns_404(self, app, client):
        mock_repo = AsyncMock()
        mock_repo.get_by_ticket_id.return_value = None
        app.dependency_overrides[get_resolution_repo] = lambda: mock_repo

        resp = await client.post(
            f"/resolutions/{uuid.uuid4()}/feedback",
            json={"action": "accepted"},
        )
        assert resp.status_code == 404

    async def test_modified_without_text_returns_422(self, app, client):
        resp = await client.post(
            f"/resolutions/{uuid.uuid4()}/feedback",
            json={"action": "modified"},
        )
        assert resp.status_code == 422

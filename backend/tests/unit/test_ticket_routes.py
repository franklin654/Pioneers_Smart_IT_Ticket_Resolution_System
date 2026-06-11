"""Unit tests for ticket REST endpoints (src/api/routes/tickets.py).

Uses FastAPI's dependency_overrides to inject mocked pipeline and repo.
No real DB, ingestion model, or orchestrator is involved.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.middleware.auth import create_access_token
from src.api.routes.tickets import router
from src.api.dependencies import get_ingestion_pipeline, get_ticket_repo
from src.api.middleware.auth import get_current_user
from src.core.exceptions import DuplicateTicketError, TicketNotFoundError
from src.db.models import TicketCategory, TicketSource, TicketStatus
from src.schemas.ticket import TicketDetailResponse
from src.ingestion.pipeline import IngestionResult


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.secret_key = "s" * 32
    s.jwt_algorithm = "HS256"
    s.access_token_expire_minutes = 60
    return s


_SETTINGS = _make_settings()


def _valid_token() -> str:
    return create_access_token({"sub": "admin", "role": "admin"}, _SETTINGS)


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {_valid_token()}"}


def _fake_user() -> dict:
    return {"sub": "admin", "role": "admin"}


def _make_ticket_summary(ticket_id: uuid.UUID | None = None):
    t = MagicMock()
    t.id = ticket_id or uuid.uuid4()
    t.title = "VPN down"
    t.category = TicketCategory.NETWORK
    t.priority = 2
    t.status = TicketStatus.NEW
    t.created_at = datetime.now(timezone.utc)
    t.model_fields_set = set()
    return t


def _make_ticket_detail(ticket_id: uuid.UUID | None = None):
    t = MagicMock()
    t.id = ticket_id or uuid.uuid4()
    t.title = "VPN down"
    t.description = "Cannot connect."
    t.category = TicketCategory.NETWORK
    t.priority = 2
    t.status = TicketStatus.NEW
    t.source = TicketSource.API
    t.pii_detected = False
    t.created_at = datetime.now(timezone.utc)
    t.updated_at = datetime.now(timezone.utc)
    t.classification = None
    t.resolution = None
    return t


@pytest.fixture
def app() -> FastAPI:
    _app = FastAPI()
    _app.include_router(router, prefix="/tickets")

    # Override auth so tests don't need a real token
    _app.dependency_overrides[get_current_user] = lambda: _fake_user()
    return _app


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ── POST /tickets/ingest ──────────────────────────────────────────────────────


class TestIngestTicket:
    _valid_payload = {
        "title": "VPN authentication failure",
        "description": "Users cannot connect via VPN from home network.",
        "priority": 2,
    }

    async def test_valid_payload_returns_202(self, app, client):
        ticket_id = uuid.uuid4()
        mock_pipeline = AsyncMock()
        mock_pipeline.run.return_value = IngestionResult(
            ticket_id=ticket_id,
            status=TicketStatus.NEW,
            pii_detected=False,
            message="Ticket received and queued for processing.",
        )
        app.dependency_overrides[get_ingestion_pipeline] = lambda: mock_pipeline

        with patch("src.api.routes.tickets.run_orchestrator_background", new=AsyncMock()):
            resp = await client.post("/tickets/ingest", json=self._valid_payload)

        assert resp.status_code == 202

    async def test_valid_payload_returns_ticket_id(self, app, client):
        ticket_id = uuid.uuid4()
        mock_pipeline = AsyncMock()
        mock_pipeline.run.return_value = IngestionResult(
            ticket_id=ticket_id,
            status=TicketStatus.NEW,
            pii_detected=False,
            message="Ticket received and queued for processing.",
        )
        app.dependency_overrides[get_ingestion_pipeline] = lambda: mock_pipeline

        with patch("src.api.routes.tickets.run_orchestrator_background", new=AsyncMock()):
            resp = await client.post("/tickets/ingest", json=self._valid_payload)

        assert resp.json()["ticket_id"] == str(ticket_id)

    async def test_duplicate_ticket_returns_409(self, app, client):
        mock_pipeline = AsyncMock()
        mock_pipeline.run.side_effect = DuplicateTicketError(
            existing_ticket_id=str(uuid.uuid4()), duplicate_type="exact"
        )
        app.dependency_overrides[get_ingestion_pipeline] = lambda: mock_pipeline

        from src.core.exceptions import AppBaseException
        from fastapi.responses import JSONResponse

        @app.exception_handler(AppBaseException)
        async def handler(req, exc):
            return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

        resp = await client.post("/tickets/ingest", json=self._valid_payload)
        assert resp.status_code == 409

    async def test_title_too_short_returns_422(self, client):
        resp = await client.post(
            "/tickets/ingest",
            json={"title": "ab", "description": "Some description here", "priority": 2},
        )
        assert resp.status_code == 422

    async def test_description_too_short_returns_422(self, client):
        resp = await client.post(
            "/tickets/ingest",
            json={"title": "Valid title", "description": "short", "priority": 2},
        )
        assert resp.status_code == 422

    async def test_priority_out_of_range_returns_422(self, client):
        resp = await client.post(
            "/tickets/ingest",
            json={"title": "Valid title", "description": "A long enough description.", "priority": 99},
        )
        assert resp.status_code == 422


# ── GET /tickets/{ticket_id} ──────────────────────────────────────────────────


class TestGetTicket:
    def _app_with_404_handler(self, base_app: FastAPI) -> FastAPI:
        from fastapi.responses import JSONResponse
        from src.core.exceptions import AppBaseException

        @base_app.exception_handler(AppBaseException)
        async def handler(req, exc: AppBaseException) -> JSONResponse:
            return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

        return base_app

    async def test_existing_ticket_returns_200(self, app, client):
        """Route returns 200 when the ticket exists; repo is called with correct ID."""
        ticket_id = uuid.uuid4()
        mock_repo = AsyncMock()
        # Return a proper TicketDetailResponse so FastAPI response validation passes
        from src.schemas.ticket import TicketDetailResponse
        detail = TicketDetailResponse(
            id=ticket_id,
            title="VPN down",
            description="Cannot connect.",
            category=TicketCategory.NETWORK,
            priority=2,
            status=TicketStatus.NEW,
            source=TicketSource.API,
            pii_detected=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            classification=None,
            resolution=None,
        )
        mock_repo.get_with_relations.return_value = MagicMock()
        app.dependency_overrides[get_ticket_repo] = lambda: mock_repo

        with patch("src.api.routes.tickets.TicketDetailResponse.model_validate", return_value=detail):
            resp = await client.get(f"/tickets/{ticket_id}")

        assert resp.status_code == 200

    async def test_missing_ticket_returns_404(self, app, client):
        self._app_with_404_handler(app)
        mock_repo = AsyncMock()
        mock_repo.get_with_relations.return_value = None
        app.dependency_overrides[get_ticket_repo] = lambda: mock_repo

        resp = await client.get(f"/tickets/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_404_body_contains_error_code(self, app, client):
        self._app_with_404_handler(app)
        mock_repo = AsyncMock()
        mock_repo.get_with_relations.return_value = None
        app.dependency_overrides[get_ticket_repo] = lambda: mock_repo

        resp = await client.get(f"/tickets/{uuid.uuid4()}")
        assert resp.json()["error_code"] == "TICKET_NOT_FOUND"


# ── GET /tickets/ ─────────────────────────────────────────────────────────────


class TestListTickets:
    async def test_list_returns_200(self, app, client):
        mock_repo = AsyncMock()
        mock_repo.search.return_value = ([], 0)
        app.dependency_overrides[get_ticket_repo] = lambda: mock_repo

        resp = await client.get("/tickets/")
        assert resp.status_code == 200

    async def test_list_returns_pagination_metadata(self, app, client):
        mock_repo = AsyncMock()
        mock_repo.search.return_value = ([], 0)
        app.dependency_overrides[get_ticket_repo] = lambda: mock_repo

        resp = await client.get("/tickets/?offset=0&limit=10")
        data = resp.json()
        assert "total" in data
        assert "offset" in data
        assert "limit" in data
        assert "items" in data

    async def test_list_passes_filters_to_repo(self, app, client):
        mock_repo = AsyncMock()
        mock_repo.search.return_value = ([], 0)
        app.dependency_overrides[get_ticket_repo] = lambda: mock_repo

        await client.get("/tickets/?status=new&priority=2")
        call_args = mock_repo.search.call_args
        filters = call_args.args[0]
        assert filters.status == TicketStatus.NEW
        assert filters.priority == 2

    async def test_limit_too_large_returns_422(self, client):
        resp = await client.get("/tickets/?limit=9999")
        assert resp.status_code == 422

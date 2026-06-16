"""Contract tests for the HTTP API layer (Phase 6 gate).

Covers every endpoint defined in docs/05_API_CONTRACT.md:
- Auth: login, expired token, wrong-type token, refresh rotation, logout
- Tickets: ingest 202, get 200/404, list 200 with meta, reclassify 202/404/409/422
- Resolutions: feedback 204/409/404
- Health: /live, /ready

The orchestration background task is patched to a no-op so tests stay
independent of the ML stack.  The DB uses the same testcontainer + rollback
fixture as other integration tests.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.main import create_app
from src.core.config import Settings, get_settings
from src.db.models import (
    Resolution,
    RoutingDecision,
    Ticket,
    TicketCategory,
    TicketSource,
    TicketStatus,
)

# ---------------------------------------------------------------------------
# Settings override — use testcontainer DB; stub secrets
# ---------------------------------------------------------------------------

_TEST_SETTINGS: dict[str, Any] = {
    "admin_username": "testadmin",
    "admin_password": "Test@dmin99",
    "jwt_secret_key": "test-secret-key-that-is-at-least-32-chars!!",
    "jwt_algorithm": "HS256",
    "access_token_expire_minutes": 15,
    "refresh_token_expire_days": 7,
    "rate_limit_per_minute": 1000,
}

_JWT_SECRET = _TEST_SETTINGS["jwt_secret_key"]
_JWT_ALGORITHM = _TEST_SETTINGS["jwt_algorithm"]


@pytest.fixture(autouse=True)
def _patch_settings(database_url: str):
    overrides = {**_TEST_SETTINGS, "database_url": database_url}
    fake = Settings(**overrides)  # type: ignore[call-arg]
    get_settings.cache_clear()
    with patch("src.core.config.get_settings", return_value=fake):
        with patch("src.api.middleware.auth.get_settings", return_value=fake):
            with patch("src.api.routes.auth.get_settings", return_value=fake):
                with patch("src.api.routes.health.get_settings", return_value=fake):
                    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Session-scope mock helper
# ---------------------------------------------------------------------------


def _session_mock(db_session: AsyncSession):
    """Return a context-manager replacement for session_scope that yields db_session."""

    @contextlib.asynccontextmanager
    async def _scope():
        yield db_session

    return _scope


# ---------------------------------------------------------------------------
# Auth token helpers (signed with the test secret)
# ---------------------------------------------------------------------------


def _valid_token(username: str = "testadmin") -> str:
    expire = datetime.now(tz=timezone.utc) + timedelta(minutes=15)
    payload = {
        "sub": username,
        "iss": "ticketiq",
        "aud": "ticketiq-api",
        "exp": expire,
        "iat": datetime.now(tz=timezone.utc),
        "jti": str(uuid.uuid4()),
        "token_type": "access",
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def _expired_token(username: str = "testadmin") -> str:
    expire = datetime.now(tz=timezone.utc) - timedelta(minutes=1)
    payload = {
        "sub": username,
        "iss": "ticketiq",
        "aud": "ticketiq-api",
        "exp": expire,
        "iat": expire - timedelta(minutes=15),
        "jti": str(uuid.uuid4()),
        "token_type": "access",
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def _refresh_token(username: str = "testadmin") -> str:
    expire = datetime.now(tz=timezone.utc) + timedelta(days=7)
    payload = {
        "sub": username,
        "iss": "ticketiq",
        "aud": "ticketiq-api",
        "exp": expire,
        "iat": datetime.now(tz=timezone.utc),
        "jti": str(uuid.uuid4()),
        "token_type": "refresh",
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def _auth_headers(token: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token or _valid_token()}"}


# ---------------------------------------------------------------------------
# DB helpers: create test rows within the rollback transaction
# ---------------------------------------------------------------------------


async def _create_ticket(
    db_session: AsyncSession,
    status: TicketStatus = TicketStatus.NEW,
    category: TicketCategory = TicketCategory.INFRASTRUCTURE,
) -> Ticket:
    ticket = Ticket(
        title="Test ticket",
        description="Something is broken.",
        original_description="Something is broken.",
        priority=3,
        status=status,
        source=TicketSource.API,
        category=category,
        content_hash=str(uuid.uuid4()),
        pii_detected=False,
    )
    db_session.add(ticket)
    await db_session.flush()
    return ticket


async def _create_ticket_with_resolution(
    db_session: AsyncSession,
    ticket_status: TicketStatus = TicketStatus.AUTO_RESOLVED,
) -> tuple[Ticket, Resolution]:
    ticket = await _create_ticket(db_session, status=ticket_status)
    resolution = Resolution(
        ticket_id=ticket.id,
        routing_decision=RoutingDecision.AUTO_RESOLVED,
        suggested_steps=[{"step_number": 1, "instruction": "Reboot the server."}],
        llm_quality_score=4.0,
    )
    db_session.add(resolution)
    await db_session.flush()
    return ticket, resolution


# ---------------------------------------------------------------------------
# Auth contract tests
# ---------------------------------------------------------------------------


class TestAuthToken:
    async def test_login_valid_credentials_returns_200(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/token",
            data={"username": "testadmin", "password": "Test@dmin99"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert body["data"]["token_type"] == "bearer"
        assert body["data"]["expires_in"] == 900
        assert "access_token" in body["data"]
        assert "refresh_token" in resp.cookies

    async def test_login_wrong_password_returns_401(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/token",
            data={"username": "testadmin", "password": "wrongpassword"},
        )
        assert resp.status_code == 401

    async def test_expired_token_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/tickets/", headers=_auth_headers(_expired_token())
        )
        assert resp.status_code == 401

    async def test_refresh_token_used_as_access_token_returns_401(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get(
            "/api/v1/tickets/", headers=_auth_headers(_refresh_token())
        )
        assert resp.status_code == 401

    async def test_refresh_rotates_tokens(self, client: AsyncClient) -> None:
        login = await client.post(
            "/api/v1/auth/token",
            data={"username": "testadmin", "password": "Test@dmin99"},
        )
        assert login.status_code == 200
        old_cookie = login.cookies["refresh_token"]

        refresh = await client.post(
            "/api/v1/auth/refresh",
            cookies={"refresh_token": old_cookie},
        )
        assert refresh.status_code == 200
        new_cookie = refresh.cookies.get("refresh_token")
        assert new_cookie is not None
        assert new_cookie != old_cookie

    async def test_logout_clears_cookie(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/auth/logout", headers=_auth_headers())
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Health contract tests
# ---------------------------------------------------------------------------


class TestHealth:
    async def test_liveness(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/health/live")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "ok"

    async def test_readiness_with_db(self, client: AsyncClient) -> None:
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        @contextlib.asynccontextmanager
        async def _fake_connect():
            yield mock_conn

        mock_engine = MagicMock()
        mock_engine.connect = _fake_connect
        with patch("src.api.routes.health.get_engine", return_value=mock_engine):
            resp = await client.get("/api/v1/health/ready")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Ticket contract tests
# ---------------------------------------------------------------------------


class TestTicketIngest:
    async def test_ingest_returns_202_with_ticket_id(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        stub_ticket = Ticket(
            id=uuid.uuid4(),
            title="VPN not connecting",
            description="Cannot connect to corporate VPN since this morning.",
            original_description="Cannot connect to corporate VPN since this morning.",
            priority=2,
            status=TicketStatus.NEW,
            source=TicketSource.API,
            content_hash=str(uuid.uuid4()),
            pii_detected=False,
        )
        stub_result = MagicMock()
        stub_result.ticket = stub_ticket

        mock_pipeline = AsyncMock()
        mock_pipeline.run = AsyncMock(return_value=stub_result)

        with patch("src.api.routes.tickets._run_pipeline_background", new_callable=AsyncMock):
            with patch("src.ingestion.pipeline.build_ingestion_pipeline", return_value=mock_pipeline):
                with patch("src.api.routes.tickets.session_scope", new=_session_mock(db_session)):
                    resp = await client.post(
                        "/api/v1/tickets/ingest",
                        json={
                            "title": "VPN not connecting",
                            "description": "Cannot connect to corporate VPN since this morning.",
                            "priority": 2,
                        },
                        headers=_auth_headers(),
                    )
        assert resp.status_code == 202
        body = resp.json()
        assert "data" in body
        assert "ticket_id" in body["data"]
        assert body["data"]["status"] == "new"

    async def test_ingest_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/tickets/ingest",
            json={"title": "Test", "description": "Test description.", "priority": 3},
        )
        assert resp.status_code == 401

    async def test_ingest_missing_required_field_returns_422(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/v1/tickets/ingest",
            json={"description": "No title provided."},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422


class TestGetTicket:
    async def test_get_existing_ticket_returns_200(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        ticket = await _create_ticket(db_session)
        with patch("src.api.routes.tickets.session_scope", new=_session_mock(db_session)):
            resp = await client.get(
                f"/api/v1/tickets/{ticket.id}",
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["id"] == str(ticket.id)
        assert body["data"]["title"] == ticket.title
        assert body["data"]["classification"] is None
        assert body["data"]["resolution"] is None

    async def test_get_nonexistent_ticket_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        with patch("src.api.routes.tickets.session_scope", new=_session_mock(db_session)):
            resp = await client.get(
                f"/api/v1/tickets/{uuid.uuid4()}",
                headers=_auth_headers(),
            )
        assert resp.status_code == 404

    async def test_get_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.get(f"/api/v1/tickets/{uuid.uuid4()}")
        assert resp.status_code == 401


class TestListTickets:
    async def test_list_returns_collection_envelope(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _create_ticket(db_session)
        with patch("src.api.routes.tickets.session_scope", new=_session_mock(db_session)):
            resp = await client.get("/api/v1/tickets/", headers=_auth_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "meta" in body
        assert "total" in body["meta"]
        assert "offset" in body["meta"]
        assert "limit" in body["meta"]
        assert body["meta"]["total"] >= 1

    async def test_list_respects_limit(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        with patch("src.api.routes.tickets.session_scope", new=_session_mock(db_session)):
            resp = await client.get("/api/v1/tickets/?limit=1", headers=_auth_headers())
        assert resp.status_code == 200
        assert resp.json()["meta"]["limit"] == 1

    async def test_list_limit_over_200_returns_422(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get("/api/v1/tickets/?limit=201", headers=_auth_headers())
        assert resp.status_code == 422


class TestReclassifyTicket:
    async def test_reclassify_awaiting_review_returns_202(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        ticket = await _create_ticket(db_session, status=TicketStatus.AWAITING_REVIEW)
        # background _resume task must be suppressed — it's a local function inside
        # the route, so we suppress it by patching BackgroundTasks.add_task
        from fastapi import BackgroundTasks

        with patch.object(BackgroundTasks, "add_task"):
            with patch("src.api.routes.tickets.session_scope", new=_session_mock(db_session)):
                resp = await client.patch(
                    f"/api/v1/tickets/{ticket.id}/reclassify",
                    json={"category": "infrastructure"},
                    headers=_auth_headers(),
                )
        assert resp.status_code == 202
        assert resp.json()["data"]["status"] == "classifying"

    async def test_reclassify_non_awaiting_ticket_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        ticket = await _create_ticket(db_session, status=TicketStatus.AUTO_RESOLVED)
        with patch("src.api.routes.tickets.session_scope", new=_session_mock(db_session)):
            resp = await client.patch(
                f"/api/v1/tickets/{ticket.id}/reclassify",
                json={"category": "infrastructure"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 409

    async def test_reclassify_invalid_category_returns_422(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        ticket = await _create_ticket(db_session, status=TicketStatus.AWAITING_REVIEW)
        with patch("src.api.routes.tickets.session_scope", new=_session_mock(db_session)):
            resp = await client.patch(
                f"/api/v1/tickets/{ticket.id}/reclassify",
                json={"category": "not_a_real_category"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 422

    async def test_reclassify_nonexistent_ticket_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        with patch("src.api.routes.tickets.session_scope", new=_session_mock(db_session)):
            resp = await client.patch(
                f"/api/v1/tickets/{uuid.uuid4()}/reclassify",
                json={"category": "infrastructure"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Resolution / feedback contract tests
# ---------------------------------------------------------------------------


class TestFeedback:
    async def test_accepted_feedback_returns_204(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        ticket, _ = await _create_ticket_with_resolution(
            db_session, ticket_status=TicketStatus.AUTO_RESOLVED
        )
        with patch("src.api.routes.resolutions.session_scope", new=_session_mock(db_session)):
            resp = await client.post(
                f"/api/v1/resolutions/{ticket.id}/feedback",
                json={"action": "accepted"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 204

    async def test_rejected_feedback_returns_204(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        ticket, _ = await _create_ticket_with_resolution(
            db_session, ticket_status=TicketStatus.AUTO_RESOLVED
        )
        with patch("src.api.routes.resolutions.session_scope", new=_session_mock(db_session)):
            resp = await client.post(
                f"/api/v1/resolutions/{ticket.id}/feedback",
                json={"action": "rejected"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 204

    async def test_modified_feedback_requires_steps(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        ticket, _ = await _create_ticket_with_resolution(
            db_session, ticket_status=TicketStatus.AUTO_RESOLVED
        )
        with patch("src.api.routes.resolutions.session_scope", new=_session_mock(db_session)):
            resp = await client.post(
                f"/api/v1/resolutions/{ticket.id}/feedback",
                json={"action": "modified"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 422

    async def test_modified_feedback_with_steps_returns_204(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        ticket, _ = await _create_ticket_with_resolution(
            db_session, ticket_status=TicketStatus.AUTO_RESOLVED
        )
        with patch("src.api.routes.resolutions.session_scope", new=_session_mock(db_session)):
            resp = await client.post(
                f"/api/v1/resolutions/{ticket.id}/feedback",
                json={
                    "action": "modified",
                    "modified_resolution": [
                        {"step_number": 1, "instruction": "Restart the VPN service."}
                    ],
                },
                headers=_auth_headers(),
            )
        assert resp.status_code == 204

    async def test_feedback_on_pending_ticket_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        ticket, _ = await _create_ticket_with_resolution(
            db_session, ticket_status=TicketStatus.AWAITING_REVIEW
        )
        with patch("src.api.routes.resolutions.session_scope", new=_session_mock(db_session)):
            resp = await client.post(
                f"/api/v1/resolutions/{ticket.id}/feedback",
                json={"action": "accepted"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 409

    async def test_feedback_ticket_not_found_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        with patch("src.api.routes.resolutions.session_scope", new=_session_mock(db_session)):
            resp = await client.post(
                f"/api/v1/resolutions/{uuid.uuid4()}/feedback",
                json={"action": "accepted"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 404

    async def test_feedback_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            f"/api/v1/resolutions/{uuid.uuid4()}/feedback",
            json={"action": "accepted"},
        )
        assert resp.status_code == 401

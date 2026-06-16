"""Regression test for the `pg_enum()` helper in `db/models.py`.

SQLAlchemy's `Enum(...)` stores the Python member *name* by default, not
`.value` — `values_callable` is required to make Postgres store the lowercase
strings every API response, frontend type, and the rest of this codebase
expects. A round-trip-through-the-ORM test (e.g. `Ticket.status ==
TicketStatus.NEW` after fetch) cannot catch a name/value mismatch, because the
ORM enum type translates consistently in both directions regardless of which
one was actually persisted. This test inspects the raw Postgres catalog
instead, which is how the original bug was actually found.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    ClassificationMethod,
    ConfidenceLevel,
    FeedbackAction,
    RoutingDecision,
    TicketCategory,
    TicketSource,
    TicketStatus,
)

_ENUM_TYPE_TO_PYTHON_ENUM = {
    "ticket_category": TicketCategory,
    "ticket_status": TicketStatus,
    "ticket_source": TicketSource,
    "confidence_level": ConfidenceLevel,
    "classification_method": ClassificationMethod,
    "routing_decision": RoutingDecision,
    "feedback_action": FeedbackAction,
}


async def _enum_labels(session: AsyncSession, pg_type_name: str) -> set[str]:
    result = await session.execute(
        text(
            "SELECT enumlabel FROM pg_enum "
            "JOIN pg_type ON pg_type.oid = pg_enum.enumtypid "
            "WHERE pg_type.typname = :type_name"
        ),
        {"type_name": pg_type_name},
    )
    return {row[0] for row in result.all()}


@pytest.mark.parametrize("pg_type_name,python_enum", _ENUM_TYPE_TO_PYTHON_ENUM.items())
@pytest.mark.asyncio
async def test_postgres_enum_labels_match_python_enum_values(
    db_session: AsyncSession, pg_type_name: str, python_enum: type
) -> None:
    labels = await _enum_labels(db_session, pg_type_name)
    expected = {member.value for member in python_enum}
    assert labels == expected, (
        f"{pg_type_name}: DB has {labels}, expected {expected} — "
        "did a new SQLEnum(...) column get added without pg_enum()?"
    )

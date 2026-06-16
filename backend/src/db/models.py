"""SQLAlchemy 2.0 ORM models + the domain enums backing them.

Six tables, same as v1 (`tickets`, `ticket_embeddings`, `knowledge_base_entries`,
`classifications`, `resolutions`, `feedback_logs`), with two v2 changes — see
`docs/03_BACKEND_DESIGN.md`:

1. `TicketStatus.AWAITING_REVIEW` — a new, non-terminal status for the
   pre-generation confidence gate.
2. `Resolution.suggested_steps` is a structured `list[ResolutionStep]` (stored
   as JSON), not free markdown text — removes the client-side regex parsing
   that caused UAT finding KB-05.

Indexes are declared on every column used in a `WHERE`/`ORDER BY` from this
first migration (audit fix M5), not retrofitted later.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from pydantic import BaseModel, Field
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def pg_enum(enum_cls: type[enum.Enum], name: str) -> SQLEnum:
    """`SQLEnum` stores the Python member *name* ("AWAITING_REVIEW") by default,
    not `.value` ("awaiting_review") — `values_callable` is required to make the
    stored representation match `.value`, which is what every API response,
    frontend type, and the rest of this codebase actually expects. Without this,
    `create_all` and the idempotent `ALTER TYPE ... ADD VALUE` step in
    `scripts/setup_db.py` silently produce a type with *both* the upper- and
    lower-case labels (caught by inspecting the DB directly — see commit notes).
    """
    return SQLEnum(enum_cls, name=name, values_callable=lambda obj: [e.value for e in obj])


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


class TicketCategory(str, enum.Enum):
    INFRASTRUCTURE = "infrastructure"
    APPLICATION = "application"
    SECURITY = "security"
    DATABASE = "database"
    ACCESS_MANAGEMENT = "access_management"
    NETWORK = "network"


class TicketStatus(str, enum.Enum):
    NEW = "new"
    CLASSIFYING = "classifying"
    CLASSIFIED = "classified"
    AWAITING_REVIEW = "awaiting_review"  # NEW in v2 — paused pre-generation
    RETRIEVING = "retrieving"
    GENERATING = "generating"
    EVALUATING = "evaluating"
    AUTO_RESOLVED = "auto_resolved"
    ASSIGNED = "assigned"
    ESCALATED = "escalated"
    CLOSED = "closed"
    REOPENED = "reopened"


# Only these four are terminal. AWAITING_REVIEW is deliberately excluded —
# the pipeline resumes once a human reclassifies (docs/02_ARCHITECTURE.md).
TERMINAL_TICKET_STATUSES = frozenset(
    {TicketStatus.AUTO_RESOLVED, TicketStatus.ASSIGNED, TicketStatus.ESCALATED, TicketStatus.CLOSED}
)


class TicketSource(str, enum.Enum):
    API = "api"
    CSV = "csv"
    WEBHOOK = "webhook"  # held-out evaluation set — never used for training


class ConfidenceLevel(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ClassificationMethod(str, enum.Enum):
    MODEL = "model"
    HUMAN_REVIEWER = "human_reviewer"  # set after PATCH /tickets/{id}/reclassify


class RoutingDecision(str, enum.Enum):
    AWAITING_REVIEW = "awaiting_review"  # pre-generation gate fired (Rules 1-2)
    AUTO_RESOLVED = "auto_resolved"
    ASSIGNED = "assigned"
    ESCALATED = "escalated"


class FeedbackAction(str, enum.Enum):
    ACCEPTED = "accepted"
    MODIFIED = "modified"
    REJECTED = "rejected"


# --------------------------------------------------------------------------
# Pydantic value object embedded in the `resolutions.suggested_steps` JSON
# column — see docs/03_BACKEND_DESIGN.md § Resolution Schema.
# --------------------------------------------------------------------------


class ResolutionStep(BaseModel):
    step_number: int = Field(ge=1)
    instruction: str = Field(min_length=1)


# --------------------------------------------------------------------------
# ORM models
# --------------------------------------------------------------------------


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Masked text — what every downstream ML stage sees.
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Raw pre-mask input, kept for audit/compliance (never fed to ML).
    original_description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[TicketCategory | None] = mapped_column(
        pg_enum(TicketCategory, "ticket_category"), nullable=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    status: Mapped[TicketStatus] = mapped_column(
        pg_enum(TicketStatus, "ticket_status"), nullable=False, default=TicketStatus.NEW
    )
    source: Mapped[TicketSource] = mapped_column(
        pg_enum(TicketSource, "ticket_source"), nullable=False, default=TicketSource.API
    )
    pii_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    embedding: Mapped[TicketEmbedding | None] = relationship(
        back_populates="ticket", uselist=False, cascade="all, delete-orphan"
    )
    classification: Mapped[Classification | None] = relationship(
        back_populates="ticket", uselist=False, cascade="all, delete-orphan"
    )
    resolution: Mapped[Resolution | None] = relationship(
        back_populates="ticket", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("priority >= 1 AND priority <= 5", name="ck_ticket_priority_range"),
        Index("ix_tickets_category", "category"),
        Index("ix_tickets_status", "status"),
        Index("ix_tickets_source", "source"),
        Index("ix_tickets_created_at", "created_at"),
        Index("ix_tickets_priority", "priority"),
    )


class TicketEmbedding(Base):
    __tablename__ = "ticket_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped[Ticket] = relationship(back_populates="embedding")

    __table_args__ = (Index("ix_ticket_embeddings_ticket_id", "ticket_id"),)


class KnowledgeBaseEntry(Base):
    __tablename__ = "knowledge_base_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[TicketCategory] = mapped_column(
        pg_enum(TicketCategory, "ticket_category"), nullable=False
    )
    resolution: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable until `scripts/index_knowledge_base.py` (Phase 4) embeds it.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_kb_entries_category", "category"),)


class Classification(Base):
    __tablename__ = "classifications"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    predicted_category: Mapped[TicketCategory] = mapped_column(
        pg_enum(TicketCategory, "ticket_category"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_level: Mapped[ConfidenceLevel] = mapped_column(
        pg_enum(ConfidenceLevel, "confidence_level"), nullable=False
    )
    # list[{"category": str, "probability": float}], full softmax/probability vector.
    top_categories: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    is_multi_domain: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    classification_method: Mapped[ClassificationMethod] = mapped_column(
        pg_enum(ClassificationMethod, "classification_method"),
        nullable=False,
        default=ClassificationMethod.MODEL,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped[Ticket] = relationship(back_populates="classification")

    __table_args__ = (Index("ix_classifications_ticket_id", "ticket_id"),)


class Resolution(Base):
    __tablename__ = "resolutions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # list[ResolutionStep] serialized. None when no resolution was generated yet
    # (AWAITING_REVIEW stub row, or a pipeline failure before generation).
    suggested_steps: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    retrieved_tickets: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    llm_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    routing_decision: Mapped[RoutingDecision] = mapped_column(
        pg_enum(RoutingDecision, "routing_decision"), nullable=False
    )
    assigned_department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_repeated_issue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    automation_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ticket: Mapped[Ticket] = relationship(back_populates="resolution")
    feedback_logs: Mapped[list[FeedbackLog]] = relationship(
        back_populates="resolution", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_resolutions_ticket_id", "ticket_id"),)


class FeedbackLog(Base):
    __tablename__ = "feedback_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    resolution_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("resolutions.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action: Mapped[FeedbackAction] = mapped_column(
        pg_enum(FeedbackAction, "feedback_action"), nullable=False
    )
    modified_resolution: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    resolution: Mapped[Resolution] = relationship(back_populates="feedback_logs")

    __table_args__ = (Index("ix_feedback_logs_resolution_id", "resolution_id"),)

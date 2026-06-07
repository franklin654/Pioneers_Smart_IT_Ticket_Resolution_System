"""SQLAlchemy ORM models for the ticket routing system.

All models use SQLAlchemy 2.0 declarative style with ``Mapped`` type
annotations for full type safety. Enums are defined as Python ``enum.Enum``
classes and persisted as PostgreSQL native enum types.

Table overview:
    - ``tickets``                 — incoming support tickets
    - ``ticket_embeddings``       — 384-dim vector per ticket (pgvector)
    - ``knowledge_base_entries``  — resolved ticket pairs used by RAG
    - ``classifications``         — classifier output per ticket
    - ``resolutions``             — generated resolution + routing decision
    - ``feedback_logs``           — agent accept/modify/reject actions
"""

import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Common declarative base shared by all models."""

    pass


# ── Enums ─────────────────────────────────────────────────────────────────────


class TicketCategory(str, enum.Enum):
    """Six IT support categories defined by the problem statement."""

    INFRASTRUCTURE = "infrastructure"
    APPLICATION = "application"
    SECURITY = "security"
    DATABASE = "database"
    ACCESS_MANAGEMENT = "access_management"
    NETWORK = "network"


class TicketStatus(str, enum.Enum):
    """State machine states for a ticket's lifecycle."""

    NEW = "new"
    CLASSIFYING = "classifying"
    CLASSIFIED = "classified"
    RETRIEVING = "retrieving"
    GENERATING = "generating"
    EVALUATING = "evaluating"
    AUTO_RESOLVED = "auto_resolved"
    ASSIGNED = "assigned"
    ESCALATED = "escalated"
    CLOSED = "closed"
    REOPENED = "reopened"


class TicketSource(str, enum.Enum):
    """Origin channel from which a ticket was ingested."""

    API = "api"
    CSV = "csv"
    WEBHOOK = "webhook"


class ConfidenceLevel(str, enum.Enum):
    """Classifier confidence band used to drive routing decisions."""

    HIGH = "high"      # confidence >= 0.85
    MEDIUM = "medium"  # 0.60 <= confidence < 0.85
    LOW = "low"        # confidence < 0.60


class RoutingDecision(str, enum.Enum):
    """Final routing outcome assigned to each processed ticket."""

    AUTO_RESOLVED = "auto_resolved"
    ASSIGNED = "assigned"
    ESCALATED = "escalated"


class FeedbackAction(str, enum.Enum):
    """Action a support agent takes on a suggested resolution."""

    ACCEPTED = "accepted"
    MODIFIED = "modified"
    REJECTED = "rejected"


# ── ORM Models ────────────────────────────────────────────────────────────────


class Ticket(Base):
    """A support ticket submitted through the API, CSV upload, or webhook.

    ``description`` holds the PII-masked text used for all ML operations.
    ``original_description`` preserves the raw input for audit purposes.
    ``content_hash`` is a SHA-256 digest of normalized title + description used for
    exact-duplicate detection.
    """

    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    original_description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[TicketCategory | None] = mapped_column(
        Enum(TicketCategory, name="ticket_category"), nullable=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, name="ticket_status"),
        nullable=False,
        default=TicketStatus.NEW,
    )
    pii_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pii_entity_types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    content_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    source: Mapped[TicketSource] = mapped_column(
        Enum(TicketSource, name="ticket_source"),
        nullable=False,
        default=TicketSource.API,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships — cascade deletes so child rows are removed with the ticket
    embedding: Mapped["TicketEmbedding | None"] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", uselist=False
    )
    classification: Mapped["Classification | None"] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", uselist=False
    )
    resolution: Mapped["Resolution | None"] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", uselist=False
    )


class TicketEmbedding(Base):
    """384-dimensional sentence-transformer embedding for a ticket.

    The ``embedding`` column uses the pgvector ``Vector`` type and is
    indexed with IVFFlat (created by ``scripts/setup_db.py``) for fast
    approximate nearest-neighbour search.
    """

    __tablename__ = "ticket_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    embedding: Mapped[list] = mapped_column(Vector(384), nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ticket: Mapped["Ticket"] = relationship(back_populates="embedding")


class KnowledgeBaseEntry(Base):
    """A resolved ticket pair used to build the RAG knowledge base.

    Rows are populated from synthetic training data (``scripts/load_tickets.py``)
    and can be augmented by agent feedback when a resolution is accepted.
    The ``embedding`` column is populated by ``scripts/index_knowledge_base.py``
    and is nullable until that indexing step runs.
    """

    __tablename__ = "knowledge_base_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[TicketCategory] = mapped_column(
        Enum(TicketCategory, name="ticket_category"), nullable=False, index=True
    )
    resolution: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list | None] = mapped_column(Vector(384), nullable=True)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="kaggle"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Classification(Base):
    """Classifier output for a single ticket.

    ``top_categories`` stores a JSON array of ``{category, probability}``
    dicts for the top-3 predictions, enabling downstream agents to inspect
    the full probability distribution.
    """

    __tablename__ = "classifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    predicted_category: Mapped[TicketCategory] = mapped_column(
        Enum(TicketCategory, name="ticket_category"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_level: Mapped[ConfidenceLevel] = mapped_column(
        Enum(ConfidenceLevel, name="confidence_level"), nullable=False
    )
    top_categories: Mapped[list] = mapped_column(JSON, nullable=False)
    is_multi_domain: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    classification_method: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ticket: Mapped["Ticket"] = relationship(back_populates="classification")


class Resolution(Base):
    """Generated resolution suggestion and final routing decision for a ticket.

    ``retrieved_tickets`` is a JSON array of ``{id, title, similarity_score}``
    dicts representing the knowledge base entries used to generate the suggestion.
    """

    __tablename__ = "resolutions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    suggested_steps: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_tickets: Mapped[list | None] = mapped_column(JSON, nullable=True)
    llm_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    routing_decision: Mapped[RoutingDecision] = mapped_column(
        Enum(RoutingDecision, name="routing_decision"), nullable=False
    )
    assigned_department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_repeated_issue: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ticket: Mapped["Ticket"] = relationship(back_populates="resolution")
    feedback_logs: Mapped[list["FeedbackLog"]] = relationship(
        back_populates="resolution", cascade="all, delete-orphan"
    )


class FeedbackLog(Base):
    """Record of a support agent accepting, modifying, or rejecting a resolution.

    ACCEPTED / REJECTED rows carry no ``modified_resolution``.
    MODIFIED rows must include the corrected resolution text which is later
    used to update the knowledge base.
    """

    __tablename__ = "feedback_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    resolution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resolutions.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[FeedbackAction] = mapped_column(
        Enum(FeedbackAction, name="feedback_action"), nullable=False
    )
    modified_resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    resolution: Mapped["Resolution"] = relationship(back_populates="feedback_logs")

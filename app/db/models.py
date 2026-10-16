"""Core data model.

Design rules applied throughout, from ADR-001 and the Database Engineer's
standards:

- Every tenant-scoped table carries a non-null ``tenant_id`` with a foreign key
  to ``tenant``, from this first migration. Isolation enforcement (RLS) lands
  in E9; the column is here now because adding it later means revisiting every
  query ever written.
- ``NOT NULL`` is the default. A nullable column is a deliberate statement that
  absence is meaningful.
- Timestamps are ``timestamptz``. A naive timestamp is a bug waiting for a
  daylight-saving boundary.
- Money is ``numeric``, never floating point.
- Status columns are Postgres enums, never free text.
- Foreign keys declare their ``ON DELETE`` behaviour explicitly.

Columns holding personal data are marked PII in a comment. That inventory feeds
the retention and deletion work in E9 (KAN-41).
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Channel(enum.StrEnum):
    EMAIL = "email"
    CHAT = "chat"
    WEBHOOK = "webhook"


class Intent(enum.StrEnum):
    BILLING = "billing"
    TECHNICAL = "technical"
    REFUND = "refund"
    GENERAL = "general"


class TicketStatus(enum.StrEnum):
    RECEIVED = "received"
    CLASSIFYING = "classifying"
    RESOLVING = "resolving"
    AWAITING_APPROVAL = "awaiting_approval"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    FAILED = "failed"


#: Terminal states. A ticket in one of these is finished and must carry a
#: completion timestamp; see the check constraint on ``ticket``.
TERMINAL_TICKET_STATUSES = (
    TicketStatus.RESOLVED,
    TicketStatus.ESCALATED,
    TicketStatus.FAILED,
)

#: Legal state transitions. Postgres enforces which states *exist*; this map is
#: what the service layer enforces about the order they occur in. Kept beside
#: the enum so the two cannot drift apart unnoticed.
TICKET_TRANSITIONS: dict[TicketStatus, frozenset[TicketStatus]] = {
    TicketStatus.RECEIVED: frozenset({TicketStatus.CLASSIFYING, TicketStatus.FAILED}),
    TicketStatus.CLASSIFYING: frozenset(
        {TicketStatus.RESOLVING, TicketStatus.ESCALATED, TicketStatus.FAILED}
    ),
    TicketStatus.RESOLVING: frozenset(
        {
            TicketStatus.AWAITING_APPROVAL,
            TicketStatus.RESOLVED,
            TicketStatus.ESCALATED,
            TicketStatus.FAILED,
        }
    ),
    TicketStatus.AWAITING_APPROVAL: frozenset(
        {TicketStatus.RESOLVING, TicketStatus.ESCALATED, TicketStatus.FAILED}
    ),
    TicketStatus.RESOLVED: frozenset(),
    TicketStatus.ESCALATED: frozenset(),
    TicketStatus.FAILED: frozenset(),
}


class MessageAuthor(enum.StrEnum):
    CUSTOMER = "customer"
    AGENT = "agent"
    HUMAN_AGENT = "human_agent"
    SYSTEM = "system"


class ResolutionOutcome(enum.StrEnum):
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    FAILED = "failed"


class EscalationReason(enum.StrEnum):
    INSUFFICIENT_KNOWLEDGE = "insufficient_knowledge"
    POLICY_BLOCK = "policy_block"
    TOOL_FAILURE = "tool_failure"
    LOW_CONFIDENCE = "low_confidence"
    CUSTOMER_REQUEST = "customer_request"
    APPROVAL_REJECTED = "approval_rejected"


class ActionType(enum.StrEnum):
    ORDER_LOOKUP = "order_lookup"
    CRM_READ = "crm_read"
    CRM_UPDATE = "crm_update"
    REFUND = "refund"
    TICKET_UPDATE = "ticket_update"


class ActionStatus(enum.StrEnum):
    PROPOSED = "proposed"
    AWAITING_APPROVAL = "awaiting_approval"
    AUTHORISED = "authorised"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


def _pg_enum(enum_cls: type[enum.StrEnum], name: str) -> Enum:
    """A native Postgres enum, stored by value rather than by Python name."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=True,
        values_callable=lambda e: [member.value for member in e],
    )


class Tenant(Base):
    """A customer company. The root of every isolation boundary."""

    __tablename__ = "tenant"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    customers: Mapped[list["Customer"]] = relationship(back_populates="tenant")


class Customer(Base):
    """An end customer of a tenant. Holds PII."""

    __tablename__ = "customer"
    __table_args__ = (
        # A tenant's own identifier for this person is unique within that
        # tenant, never globally. Two tenants may both have a "cust-1".
        UniqueConstraint("tenant_id", "external_id"),
        Index("ix_customer_tenant_id_email", "tenant_id", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)  # PII
    display_name: Mapped[str | None] = mapped_column(String(200))  # PII, optional
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    tenant: Mapped[Tenant] = relationship(back_populates="customers")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="customer")


class Ticket(Base):
    """One support request."""

    __tablename__ = "ticket"
    __table_args__ = (
        # Idempotent intake: the same inbound message delivered twice must not
        # create two tickets. Consumed by KAN-27.
        UniqueConstraint("tenant_id", "external_ref"),
        # A completion timestamp and a terminal status must agree. Without
        # this, a "resolved" ticket with no resolved_at is representable, and
        # every report built on it is quietly wrong.
        CheckConstraint(
            "(status IN ('resolved', 'escalated', 'failed')) = (resolved_at IS NOT NULL)",
            name="terminal_status_requires_resolved_at",
        ),
        CheckConstraint("urgency IS NULL OR urgency BETWEEN 1 AND 5", name="urgency_in_range"),
        # Primary operational query: this tenant's tickets by state, newest
        # first. Drives both the agent's work queue and the dashboard.
        Index("ix_ticket_tenant_id_status_created_at", "tenant_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customer.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[Channel] = mapped_column(_pg_enum(Channel, "channel"), nullable=False)
    external_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(500))  # PII (free text)
    status: Mapped[TicketStatus] = mapped_column(
        _pg_enum(TicketStatus, "ticket_status"),
        nullable=False,
        default=TicketStatus.RECEIVED,
    )
    # Null until the router has classified it, which is a genuine distinction
    # from "classified as general".
    intent: Mapped[Intent | None] = mapped_column(_pg_enum(Intent, "intent"))
    urgency: Mapped[int | None] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer: Mapped[Customer] = relationship(back_populates="tickets")
    messages: Mapped[list["Message"]] = relationship(back_populates="ticket")


class Message(Base):
    """One message in a ticket thread. The body holds PII."""

    __tablename__ = "message"
    __table_args__ = (
        Index(
            "ix_message_tenant_id_ticket_id_created_at",
            "tenant_id",
            "ticket_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ticket.id", ondelete="CASCADE"), nullable=False
    )
    author: Mapped[MessageAuthor] = mapped_column(
        _pg_enum(MessageAuthor, "message_author"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)  # PII (free text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    ticket: Mapped[Ticket] = relationship(back_populates="messages")


class Resolution(Base):
    """The outcome of attempting to resolve a ticket. At most one per ticket."""

    __tablename__ = "resolution"
    __table_args__ = (
        UniqueConstraint("ticket_id"),
        # An escalation must say why, and a resolution must not pretend to
        # have a reason it does not have.
        CheckConstraint(
            "(outcome = 'escalated') = (escalation_reason IS NOT NULL)",
            name="escalation_requires_reason",
        ),
        CheckConstraint("cost_usd >= 0", name="cost_not_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The only tenant_id here that needs its own index: resolution has no
    # composite index leading with tenant_id, and the cascade on tenant delete
    # needs to find these rows without a sequential scan.
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ticket.id", ondelete="CASCADE"), nullable=False
    )
    outcome: Mapped[ResolutionOutcome] = mapped_column(
        _pg_enum(ResolutionOutcome, "resolution_outcome"), nullable=False
    )
    escalation_reason: Mapped[EscalationReason | None] = mapped_column(
        _pg_enum(EscalationReason, "escalation_reason")
    )
    reply_body: Mapped[str | None] = mapped_column(Text)  # PII (free text)
    # Six decimal places: one classification call can cost a fraction of a
    # cent, and those fractions are the whole cost-per-ticket metric.
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, server_default="0")
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Action(Base):
    """A side effect the agent proposed, and what became of it."""

    __tablename__ = "action"
    __table_args__ = (
        # The idempotency contract from ADR-003, enforced in the database so a
        # retry or a resumed workflow cannot execute the same effect twice even
        # if the application logic is wrong.
        UniqueConstraint("tenant_id", "idempotency_key"),
        # Money requires a currency, and a currency requires money.
        CheckConstraint(
            "(amount IS NULL) = (currency IS NULL)",
            name="amount_and_currency_together",
        ),
        CheckConstraint("amount IS NULL OR amount > 0", name="amount_positive"),
        CheckConstraint(
            "(status = 'executed') = (executed_at IS NOT NULL)",
            name="executed_requires_timestamp",
        ),
        Index("ix_action_tenant_id_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ticket.id", ondelete="CASCADE"), nullable=False
    )
    action_type: Mapped[ActionType] = mapped_column(
        _pg_enum(ActionType, "action_type"), nullable=False
    )
    status: Mapped[ActionStatus] = mapped_column(
        _pg_enum(ActionStatus, "action_status"),
        nullable=False,
        default=ActionStatus.PROPOSED,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    refusal_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEntry(Base):
    """Append-only business record.

    Distinct from application logs, which rotate away. This is what is used to
    reconstruct why the system did something, months later. Nothing in the
    application updates or deletes a row here.
    """

    __tablename__ = "audit_entry"
    __table_args__ = (
        Index("ix_audit_entry_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_audit_entry_tenant_id_ticket_id", "tenant_id", "ticket_id"),
    )

    # A monotonic integer rather than a uuid: this table is append-only and the
    # highest-volume one here, and an ordered key keeps inserts at the end of
    # the index instead of scattering them across it.
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    # Kept if the ticket is deleted: the audit record of what happened must
    # outlive the thing it happened to.
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ticket.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

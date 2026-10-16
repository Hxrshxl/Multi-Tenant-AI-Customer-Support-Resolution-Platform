"""Ticket intake and the resolution flow.

The whole vertical slice (KAN-17) in one place: a ticket arrives, is persisted
against a tenant, passes through a resolver, and the reply is persisted with the
ticket reaching a terminal state. All inside one transaction, so a failure
anywhere leaves no partial ticket behind.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.db.models import (
    TERMINAL_TICKET_STATUSES,
    TICKET_TRANSITIONS,
    Channel,
    MessageAuthor,
    Ticket,
    TicketStatus,
)
from app.repositories import tickets as repo
from app.services.resolution import Resolver

logger = logging.getLogger(__name__)


class IllegalTransitionError(AppError):
    """A ticket was asked to move to a state it cannot reach from here.

    This is a programming error, not a user error: the caller never chooses a
    status. It surfaces as a 500 with its own code so it is distinguishable in
    logs from an ordinary failure.
    """

    status_code = 500
    code = "illegal_state_transition"
    default_message = "The ticket could not be moved to that state."


@dataclass(frozen=True)
class IntakeRequest:
    external_ref: str
    channel: Channel
    subject: str | None
    body: str
    customer_external_id: str
    customer_email: str
    customer_display_name: str | None = None


@dataclass(frozen=True)
class IntakeResult:
    ticket_id: uuid.UUID
    status: TicketStatus
    reply: str | None
    created: bool
    """False when an existing ticket was returned rather than a new one."""


def transition(ticket: Ticket, to_status: TicketStatus) -> None:
    """Move a ticket, refusing any transition the state machine disallows.

    Postgres enforces which states *exist* (KAN-15); this enforces the order
    they occur in. Keeping both means an illegal state is unstorable and an
    illegal sequence is unreachable.
    """
    if to_status not in TICKET_TRANSITIONS[ticket.status]:
        raise IllegalTransitionError(
            f"Cannot move a ticket from {ticket.status.value} to {to_status.value}."
        )
    if to_status in TERMINAL_TICKET_STATUSES:
        repo.mark_terminal(ticket, to_status)
    else:
        ticket.status = to_status


class IntakeService:
    """Accepts a ticket and drives it to an outcome."""

    def __init__(self, resolver: Resolver) -> None:
        self._resolver = resolver

    async def submit(
        self, session: AsyncSession, *, tenant_slug: str, request: IntakeRequest
    ) -> IntakeResult:
        tenant = await repo.get_tenant_by_slug(session, tenant_slug)
        if tenant is None:
            # Deliberately the same response as any other unknown resource:
            # probing this endpoint must not reveal which tenants exist.
            raise NotFoundError("Unknown tenant.")

        existing = await repo.get_ticket_by_external_ref(
            session, tenant_id=tenant.id, external_ref=request.external_ref
        )
        if existing is not None:
            # Idempotent intake. Webhooks retry and users double-submit; the
            # unique constraint on (tenant_id, external_ref) is the backstop,
            # this is the graceful path.
            logger.info(
                "duplicate intake ignored",
                extra={"ticket_id": str(existing.id), "external_ref": request.external_ref},
            )
            return IntakeResult(
                ticket_id=existing.id,
                status=existing.status,
                reply=None,
                created=False,
            )

        customer = await repo.get_or_create_customer(
            session,
            tenant_id=tenant.id,
            external_id=request.customer_external_id,
            email=request.customer_email,
            display_name=request.customer_display_name,
        )

        ticket = await repo.create_ticket(
            session,
            tenant_id=tenant.id,
            customer_id=customer.id,
            channel=request.channel,
            external_ref=request.external_ref,
            subject=request.subject,
        )
        inbound = await repo.add_message(
            session,
            tenant_id=tenant.id,
            ticket_id=ticket.id,
            author=MessageAuthor.CUSTOMER,
            body=request.body,
        )
        logger.info("ticket accepted", extra={"ticket_id": str(ticket.id)})

        # Classification is a no-op until E4; the ticket still moves through
        # the state so the sequence is exercised from the first slice.
        transition(ticket, TicketStatus.CLASSIFYING)
        transition(ticket, TicketStatus.RESOLVING)

        draft = await self._resolver.resolve(ticket, [inbound])

        await repo.record_resolution(
            session,
            tenant_id=tenant.id,
            ticket_id=ticket.id,
            outcome=draft.outcome,
            reply_body=draft.reply_body,
            cost_usd=draft.cost_usd,
            tokens_used=draft.tokens_used,
        )
        if draft.reply_body is not None:
            await repo.add_message(
                session,
                tenant_id=tenant.id,
                ticket_id=ticket.id,
                author=MessageAuthor.AGENT,
                body=draft.reply_body,
            )

        transition(ticket, TicketStatus(draft.outcome.value))
        await session.flush()

        logger.info(
            "ticket resolved",
            extra={
                "ticket_id": str(ticket.id),
                "outcome": draft.outcome.value,
                "cost_usd": str(draft.cost_usd),
            },
        )
        return IntakeResult(
            ticket_id=ticket.id,
            status=ticket.status,
            reply=draft.reply_body,
            created=True,
        )

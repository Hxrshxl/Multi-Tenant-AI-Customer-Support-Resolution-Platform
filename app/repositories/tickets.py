"""Queries for the ticket lifecycle.

Every query here filters by ``tenant_id``. That filter is currently the only
thing keeping tenants apart — row-level security arrives in E9 (KAN-48) and
makes a forgotten filter return nothing instead of someone else's data. Until
then, a missing filter here is a leak, so treat this file accordingly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Channel,
    Customer,
    Message,
    MessageAuthor,
    Resolution,
    ResolutionOutcome,
    Tenant,
    Ticket,
    TicketStatus,
)


async def get_tenant_by_slug(session: AsyncSession, slug: str) -> Tenant | None:
    return await session.scalar(select(Tenant).where(Tenant.slug == slug, Tenant.is_active))


async def get_or_create_customer(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    external_id: str,
    email: str,
    display_name: str | None,
) -> Customer:
    """Find a tenant's customer by its own identifier, creating it if new."""
    existing = await session.scalar(
        select(Customer).where(
            Customer.tenant_id == tenant_id,
            Customer.external_id == external_id,
        )
    )
    if existing is not None:
        return existing

    customer = Customer(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        external_id=external_id,
        email=email,
        display_name=display_name,
    )
    session.add(customer)
    await session.flush()
    return customer


async def get_ticket_by_external_ref(
    session: AsyncSession, *, tenant_id: uuid.UUID, external_ref: str
) -> Ticket | None:
    """The idempotency lookup: has this inbound message already been seen?"""
    return await session.scalar(
        select(Ticket).where(
            Ticket.tenant_id == tenant_id,
            Ticket.external_ref == external_ref,
        )
    )


async def create_ticket(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    channel: Channel,
    external_ref: str,
    subject: str | None,
) -> Ticket:
    ticket = Ticket(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        customer_id=customer_id,
        channel=channel,
        external_ref=external_ref,
        subject=subject,
        status=TicketStatus.RECEIVED,
    )
    session.add(ticket)
    await session.flush()
    return ticket


async def add_message(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    ticket_id: uuid.UUID,
    author: MessageAuthor,
    body: str,
) -> Message:
    message = Message(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        ticket_id=ticket_id,
        author=author,
        body=body,
    )
    session.add(message)
    await session.flush()
    return message


async def record_resolution(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    ticket_id: uuid.UUID,
    outcome: ResolutionOutcome,
    reply_body: str | None,
    cost_usd: Decimal = Decimal("0"),
    tokens_used: int = 0,
) -> Resolution:
    resolution = Resolution(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        ticket_id=ticket_id,
        outcome=outcome,
        reply_body=reply_body,
        cost_usd=cost_usd,
        tokens_used=tokens_used,
    )
    session.add(resolution)
    await session.flush()
    return resolution


def mark_terminal(ticket: Ticket, status: TicketStatus) -> None:
    """Move a ticket to a terminal state, setting the completion timestamp.

    The database enforces that these two agree
    (``ck_ticket_terminal_status_requires_resolved_at``), so they are set
    together here rather than being left to each caller to remember.
    """
    ticket.status = status
    ticket.resolved_at = datetime.now(UTC)

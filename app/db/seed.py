"""Sample data for local development.

Deliberately seeds **two** tenants with different configuration. A single
tenant hides every isolation bug: a query missing its tenant filter looks
perfectly correct when there is only one tenant's data to return.

Idempotent — running it twice does not duplicate anything, so it is safe to
re-run against a database you are already working in.
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Channel,
    Customer,
    Intent,
    Message,
    MessageAuthor,
    Tenant,
    Ticket,
    TicketStatus,
)

logger = logging.getLogger(__name__)

TENANTS = (
    ("acme", "Acme Logistics"),
    ("globex", "Globex Retail"),
)

SAMPLE_SUBJECTS: dict[Intent, tuple[str, ...]] = {
    Intent.BILLING: (
        "I was charged twice this month",
        "Can I get a VAT invoice for order 4417?",
        "Why did my subscription price change?",
    ),
    Intent.TECHNICAL: (
        "Export keeps failing with error E_4210",
        "Webhook deliveries stopped yesterday",
        "Cannot log in after password reset",
    ),
    Intent.REFUND: (
        "Package arrived damaged, requesting refund",
        "Wrong item delivered, want my money back",
        "Cancelled order but was still charged",
    ),
    Intent.GENERAL: (
        "Do you ship to Ireland?",
        "How do I add a second user to my account?",
        "What are your support hours?",
    ),
}

# Roughly the mix a real support queue sees: mostly routine, refunds least
# common but highest risk.
INTENT_WEIGHTS = {
    Intent.GENERAL: 0.40,
    Intent.TECHNICAL: 0.30,
    Intent.BILLING: 0.20,
    Intent.REFUND: 0.10,
}


async def seed(
    session: AsyncSession,
    *,
    tickets_per_tenant: int = 50,
    customers_per_tenant: int = 8,
    seed_value: int = 20261017,
) -> dict[str, int]:
    """Load sample tenants, customers and tickets.

    Returns a count of what was created, so the caller can report honestly
    rather than claiming success it cannot see.
    """
    # Fixed seed: the same data every run, so a bug reproduces identically.
    # S311: a predictable generator is the point. Seed data must be identical
    # on every run so a bug found against it reproduces exactly. Nothing here
    # is security-sensitive.
    rng = random.Random(seed_value)  # noqa: S311
    created = {"tenants": 0, "customers": 0, "tickets": 0, "messages": 0}

    for slug, name in TENANTS:
        existing = await session.scalar(select(Tenant).where(Tenant.slug == slug))
        if existing is not None:
            logger.info("tenant already present, skipping", extra={"tenant_slug": slug})
            tenant = existing
        else:
            tenant = Tenant(id=uuid.uuid4(), slug=slug, name=name)
            session.add(tenant)
            await session.flush()
            created["tenants"] += 1

        customers = list(
            await session.scalars(select(Customer).where(Customer.tenant_id == tenant.id))
        )
        while len(customers) < customers_per_tenant:
            index = len(customers) + 1
            customer = Customer(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                external_id=f"cust-{index:04d}",
                email=f"customer{index}@{slug}.example",
                display_name=f"Customer {index}",
            )
            session.add(customer)
            customers.append(customer)
            created["customers"] += 1
        await session.flush()

        existing_tickets = await session.scalar(
            select(Ticket.id).where(Ticket.tenant_id == tenant.id).limit(1)
        )
        if existing_tickets is not None:
            logger.info("tickets already present, skipping", extra={"tenant_slug": slug})
            continue

        intents = list(INTENT_WEIGHTS)
        weights = [INTENT_WEIGHTS[i] for i in intents]

        for n in range(tickets_per_tenant):
            intent = rng.choices(intents, weights=weights, k=1)[0]
            customer = rng.choice(customers)
            age = timedelta(hours=rng.randint(0, 24 * 30))
            opened = datetime.now(UTC) - age

            # A realistic spread of outcomes, including unresolved work.
            status = rng.choices(
                [
                    TicketStatus.RESOLVED,
                    TicketStatus.ESCALATED,
                    TicketStatus.RECEIVED,
                    TicketStatus.AWAITING_APPROVAL,
                ],
                weights=[0.62, 0.18, 0.15, 0.05],
                k=1,
            )[0]
            terminal = status in (TicketStatus.RESOLVED, TicketStatus.ESCALATED)

            ticket = Ticket(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                customer_id=customer.id,
                channel=rng.choice(list(Channel)),
                external_ref=f"{slug}-seed-{n:05d}",
                subject=rng.choice(SAMPLE_SUBJECTS[intent]),
                status=status,
                intent=intent,
                urgency=rng.randint(1, 5),
                created_at=opened,
                resolved_at=opened + timedelta(minutes=rng.randint(2, 240)) if terminal else None,
            )
            session.add(ticket)
            created["tickets"] += 1

            session.add(
                Message(
                    id=uuid.uuid4(),
                    tenant_id=tenant.id,
                    ticket_id=ticket.id,
                    author=MessageAuthor.CUSTOMER,
                    body=f"{ticket.subject}\n\nPlease help, this is affecting my account.",
                    created_at=opened,
                )
            )
            created["messages"] += 1

        await session.flush()

    return created

"""Resolution: deciding what to reply to a ticket.

**This module is the seam.** Everything the agent will eventually be — routing,
retrieval, tool calls, policy checks, human approval — plugs in behind the
``Resolver`` protocol below. Intake does not know, and must never learn, which
implementation is behind it.

Today the only implementation is ``PlaceholderResolver``, which returns a canned
acknowledgement. It exists so the path from HTTP request to persisted reply is
provably wired end to end before any of the hard parts are built (KAN-17).

What replaces it, and when:

- **E4** adds classification, so a resolver receives an intent rather than
  guessing.
- **E5** replaces this with a LangGraph workflow. That is the real swap: same
  protocol, entirely different machinery behind it.
- **E7** means a resolver returns a *proposed action* for a deterministic policy
  layer to authorise, never an executed one (ADR-002).
- **E8** means a resolver may return "awaiting approval" rather than a reply.

The protocol deliberately returns a draft rather than writing anything. Keeping
persistence out of the resolver is what lets the approval interrupt in E8 exist
at all: you cannot pause between deciding and writing if deciding writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.db.models import EscalationReason, Message, ResolutionOutcome, Ticket


@dataclass(frozen=True)
class ResolutionDraft:
    """What a resolver decided, before anything is written.

    ``cost_usd`` and ``tokens_used`` are zero for the placeholder but present
    from the start, because cost per ticket is a tracked metric from the first
    model call (E11) and retrofitting the field later means backfilling it.
    """

    outcome: ResolutionOutcome
    reply_body: str | None
    escalation_reason: EscalationReason | None = None
    cost_usd: Decimal = Decimal("0")
    tokens_used: int = 0


class Resolver(Protocol):
    """Decides what to do with a ticket. Writes nothing."""

    async def resolve(self, ticket: Ticket, messages: list[Message]) -> ResolutionDraft: ...


class PlaceholderResolver:
    """Returns a fixed acknowledgement.

    Deliberately not clever. Its only job is to prove the wiring: a request
    arrives, a reply is produced, and both are persisted and traceable. Any
    intelligence here would be thrown away by E5.
    """

    REPLY = (
        "Thanks for getting in touch — we have received your message and a "
        "member of the team will follow up shortly."
    )

    async def resolve(self, ticket: Ticket, messages: list[Message]) -> ResolutionDraft:
        return ResolutionDraft(
            outcome=ResolutionOutcome.RESOLVED,
            reply_body=self.REPLY,
        )

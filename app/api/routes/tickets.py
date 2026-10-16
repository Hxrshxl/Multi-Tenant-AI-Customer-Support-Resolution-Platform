"""Ticket intake endpoint.

The handler validates, delegates, and maps the result to a status code. It
contains no business logic — that lives in ``app.services.intake``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_intake_service, get_session
from app.db.models import Channel, TicketStatus
from app.services.intake import IntakeRequest, IntakeService

router = APIRouter(tags=["tickets"])


class CustomerPayload(BaseModel):
    external_id: str = Field(max_length=128, description="The tenant's own id for this person.")
    email: EmailStr
    display_name: str | None = Field(default=None, max_length=200)


class TicketIntakePayload(BaseModel):
    external_ref: str = Field(
        max_length=256,
        description=(
            "Stable identifier from the source system. Re-sending the same "
            "value returns the existing ticket rather than creating another."
        ),
    )
    channel: Channel
    body: str = Field(min_length=1, max_length=20_000)
    subject: str | None = Field(default=None, max_length=500)
    customer: CustomerPayload


class TicketAcceptedResponse(BaseModel):
    ticket_id: uuid.UUID
    status: TicketStatus
    reply: str | None


@router.post(
    "/v1/tickets",
    summary="Submit a ticket",
    response_model=TicketAcceptedResponse,
    responses={
        200: {"description": "This external_ref was already submitted; existing ticket returned"},
        201: {"description": "Ticket accepted and resolved"},
        404: {"description": "Unknown tenant"},
    },
)
async def submit_ticket(
    payload: TicketIntakePayload,
    service: Annotated[IntakeService, Depends(get_intake_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_slug: Annotated[str, Header(alias="X-Tenant-Slug", max_length=64)],
) -> JSONResponse:
    """Accept a ticket and run it through to an outcome.

    The tenant arrives in a header because authentication does not exist yet;
    E9 (KAN-50, KAN-51) replaces this with an authenticated identity. Until
    then any caller can name any tenant, which is why this must not be exposed
    publicly.
    """
    result = await service.submit(
        session,
        tenant_slug=tenant_slug,
        request=IntakeRequest(
            external_ref=payload.external_ref,
            channel=payload.channel,
            subject=payload.subject,
            body=payload.body,
            customer_external_id=payload.customer.external_id,
            customer_email=str(payload.customer.email),
            customer_display_name=payload.customer.display_name,
        ),
    )

    body = TicketAcceptedResponse(
        ticket_id=result.ticket_id,
        status=result.status,
        reply=result.reply,
    )
    # 201 for a new ticket, 200 when an existing one was returned. A caller
    # retrying a webhook can tell the difference without parsing the body.
    return JSONResponse(
        status_code=201 if result.created else 200,
        content=body.model_dump(mode="json"),
    )

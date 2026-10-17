"""Queries for the knowledge base.

Every query filters by ``tenant_id``. Until row-level security lands in E9
(KAN-48), that filter is the only thing keeping one tenant's documents out of
another's search results.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentChunk, SourceFormat
from app.ingestion.chunking import Chunk


async def get_by_source_uri(
    session: AsyncSession, *, tenant_id: uuid.UUID, source_uri: str
) -> Document | None:
    """The idempotency lookup: have we ingested this source before?"""
    return await session.scalar(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.source_uri == source_uri,
        )
    )


async def create(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    source_uri: str,
    title: str | None,
    source_format: SourceFormat,
    content_hash: str,
    byte_size: int,
) -> Document:
    document = Document(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        source_uri=source_uri,
        title=title,
        source_format=source_format,
        content_hash=content_hash,
        byte_size=byte_size,
    )
    session.add(document)
    await session.flush()
    return document


def apply_update(
    document: Document,
    *,
    title: str | None,
    source_format: SourceFormat,
    content_hash: str,
    byte_size: int,
) -> None:
    """Update a document's metadata in place after its content changed."""
    document.title = title
    document.source_format = source_format
    document.content_hash = content_hash
    document.byte_size = byte_size


async def delete_chunks(
    session: AsyncSession, *, tenant_id: uuid.UUID, document_id: uuid.UUID
) -> int:
    """Remove every chunk of a document, returning how many were deleted.

    Chunks are replaced wholesale rather than diffed, because chunk boundaries
    move when content moves — a diff would be meaningless.
    """
    # A DELETE really returns a CursorResult, which reports rowcount; the
    # generic execute() signature does not say so.
    result = cast(
        CursorResult[Any],
        await session.execute(
            delete(DocumentChunk).where(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id == document_id,
            )
        ),
    )
    return result.rowcount or 0


async def add_chunks(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    chunks: list[Chunk],
) -> int:
    """Insert a document's chunks, returning how many were written."""
    for chunk in chunks:
        session.add(
            DocumentChunk(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                document_id=document_id,
                ordinal=chunk.ordinal,
                content=chunk.content,
                heading_path=chunk.heading_path,
                char_count=chunk.char_count,
            )
        )
    await session.flush()
    return len(chunks)

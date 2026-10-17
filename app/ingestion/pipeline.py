"""The ingestion run: discover, load, chunk, store.

**One transaction per document, not per run.** That choice does three things at
once:

- *Atomic replace*: a changed document's old chunks are deleted and its new ones
  written in the same transaction, so retrieval never sees a half-reindexed
  document.
- *Resumable*: a run that dies at document 400 of 500 keeps the first 399. The
  next run finds them unchanged by content hash and skips them, so resuming is
  just running it again.
- *Failure isolation*: one malformed file rolls back only itself.

A single transaction for the whole run would be simpler and would lose all
three.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import session_scope
from app.ingestion import loaders
from app.ingestion.chunking import DEFAULT_STRATEGY, ChunkStrategy
from app.repositories import documents as repo

logger = logging.getLogger(__name__)


@dataclass
class IngestionReport:
    """What a run actually did. Printed at the end, and asserted in tests."""

    documents_seen: int = 0
    documents_created: int = 0
    documents_updated: int = 0
    documents_unchanged: int = 0
    documents_failed: int = 0
    chunks_written: int = 0
    chunks_deleted: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)

    @property
    def documents_embedded_later(self) -> int:
        """Documents whose chunks are new and will need embedding (KAN-20).

        The gap between this and ``documents_seen`` is what the content hash
        saves. Once embedding costs money, that gap is the saving.
        """
        return self.documents_created + self.documents_updated


async def _ingest_one(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document: loaders.LoadedDocument,
    strategy: ChunkStrategy,
    report: IngestionReport,
) -> None:
    existing = await repo.get_by_source_uri(
        session, tenant_id=tenant_id, source_uri=document.source_uri
    )

    if existing is not None and existing.content_hash == document.content_hash:
        report.documents_unchanged += 1
        return

    if existing is None:
        record = await repo.create(
            session,
            tenant_id=tenant_id,
            source_uri=document.source_uri,
            title=document.title,
            source_format=document.source_format,
            content_hash=document.content_hash,
            byte_size=document.byte_size,
        )
        report.documents_created += 1
    else:
        # Content changed: replace the chunks wholesale.
        report.chunks_deleted += await repo.delete_chunks(
            session, tenant_id=tenant_id, document_id=existing.id
        )
        repo.apply_update(
            existing,
            title=document.title,
            source_format=document.source_format,
            content_hash=document.content_hash,
            byte_size=document.byte_size,
        )
        record = existing
        report.documents_updated += 1

    report.chunks_written += await repo.add_chunks(
        session,
        tenant_id=tenant_id,
        document_id=record.id,
        chunks=strategy.split(document.content),
    )


async def ingest_directory(
    factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: uuid.UUID,
    root: Path,
    strategy: ChunkStrategy = DEFAULT_STRATEGY,
    progress_every: int = 25,
    on_progress: Callable[[IngestionReport], None] | None = None,
) -> IngestionReport:
    """Ingest every supported file under ``root`` for one tenant."""
    report = IngestionReport()

    for path in loaders.discover(root):
        report.documents_seen += 1
        try:
            document = loaders.load(path, root=root)
            if not document.content.strip():
                raise ValueError("document is empty after extraction")
            # Each document gets its own transaction. See the module docstring.
            async with session_scope(factory) as session:
                await _ingest_one(
                    session,
                    tenant_id=tenant_id,
                    document=document,
                    strategy=strategy,
                    report=report,
                )
        except (ValueError, OSError, UnicodeDecodeError) as exc:
            # Expected, handled problems with a source file: unreadable, empty,
            # too large, wrong encoding. The type and message say everything; a
            # traceback would be noise in a run over hundreds of documents.
            report.documents_failed += 1
            report.failures.append((str(path), f"{type(exc).__name__}: {exc}"))
            logger.warning(
                "document skipped",
                extra={"source_path": str(path), "reason": str(exc)},
            )
        except Exception as exc:
            # Anything else is a surprise and deserves the full trace.
            # One bad file must never abort a 500-document run.
            report.documents_failed += 1
            report.failures.append((str(path), f"{type(exc).__name__}: {exc}"))
            logger.warning(
                "document ingestion failed unexpectedly",
                exc_info=True,
                extra={"source_path": str(path)},
            )

        if on_progress and report.documents_seen % progress_every == 0:
            on_progress(report)

    logger.info(
        "ingestion run complete",
        extra={
            "documents_seen": report.documents_seen,
            "documents_created": report.documents_created,
            "documents_updated": report.documents_updated,
            "documents_unchanged": report.documents_unchanged,
            "documents_failed": report.documents_failed,
            "chunks_written": report.chunks_written,
        },
    )
    return report

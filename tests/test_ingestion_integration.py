"""Ingestion against a real database.

Skipped when Postgres is unreachable, so the suite still runs with no stack up.
Uses a throwaway tenant with a random slug, removed afterwards by cascade.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from app.db.session import create_engine, create_session_factory
from app.ingestion.pipeline import ingest_directory
from tests.test_intake_integration import SETTINGS, _database_reachable

pytestmark = pytest.mark.skipif(
    not _database_reachable(SETTINGS),
    reason="Postgres not reachable; run `docker compose up -d` to include these tests",
)

DOC_A = "# Refunds\n\nRefunds take 5 working days.\n"
DOC_B = "# Webhooks\n\nDelivered at least once.\n"


@pytest.fixture
def tenant_id() -> Iterator[uuid.UUID]:
    assert SETTINGS is not None
    slug = f"ingest-{uuid.uuid4().hex[:10]}"
    dsn = str(SETTINGS.database_url)
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenant (id, slug, name, is_active, created_at, updated_at)"
                " VALUES (gen_random_uuid(), %s, %s, true, now(), now()) RETURNING id",
                (slug, slug),
            )
            row = cur.fetchone()
            assert row is not None
            new_id = row[0]
        conn.commit()
    yield new_id
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tenant WHERE id = %s", (new_id,))
        conn.commit()


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    open(tmp_path / "refunds.md", "w", encoding="utf-8", newline="\n").write(DOC_A)
    open(tmp_path / "webhooks.md", "w", encoding="utf-8", newline="\n").write(DOC_B)
    return tmp_path


async def _run(tenant_id: uuid.UUID, corpus: Path):  # type: ignore[no-untyped-def]
    assert SETTINGS is not None
    engine = create_engine(SETTINGS)
    try:
        factory = create_session_factory(engine)
        return await ingest_directory(factory, tenant_id=tenant_id, root=corpus)
    finally:
        await engine.dispose()


#: Explicit queries rather than interpolating a table name into SQL. The table
#: names here are ours, not user input, but building SQL from a variable is a
#: habit worth not having.
_COUNT_QUERIES = {
    "document": "SELECT count(*) FROM document WHERE tenant_id = %s",
    "document_chunk": "SELECT count(*) FROM document_chunk WHERE tenant_id = %s",
}


def _count(table: str, tenant_id: uuid.UUID) -> int:
    assert SETTINGS is not None
    with psycopg.connect(str(SETTINGS.database_url)) as conn:
        with conn.cursor() as cur:
            cur.execute(_COUNT_QUERIES[table], (tenant_id,))
            row = cur.fetchone()
    return int(row[0]) if row else 0


async def test_first_run_creates_documents_and_chunks(tenant_id: uuid.UUID, corpus: Path) -> None:
    report = await _run(tenant_id, corpus)

    assert report.documents_seen == 2
    assert report.documents_created == 2
    assert report.documents_failed == 0
    assert report.chunks_written > 0
    assert _count("document", tenant_id) == 2
    assert _count("document_chunk", tenant_id) == report.chunks_written


async def test_second_run_is_a_no_op(tenant_id: uuid.UUID, corpus: Path) -> None:
    """The content hash is what makes re-embedding cost nothing in KAN-20."""
    first = await _run(tenant_id, corpus)
    second = await _run(tenant_id, corpus)

    assert second.documents_unchanged == 2
    assert second.documents_created == 0
    assert second.chunks_written == 0
    # Crucially, the chunk count did not change — nothing was duplicated.
    assert _count("document_chunk", tenant_id) == first.chunks_written


async def test_changed_content_replaces_its_chunks_atomically(
    tenant_id: uuid.UUID, corpus: Path
) -> None:
    await _run(tenant_id, corpus)

    open(corpus / "refunds.md", "w", encoding="utf-8", newline="\n").write(
        DOC_A + "\n## Partial refunds\n\nOnly part of the order is refunded.\n"
    )
    report = await _run(tenant_id, corpus)

    assert report.documents_updated == 1
    assert report.documents_unchanged == 1
    assert report.chunks_deleted > 0
    # No orphans: every chunk still belongs to exactly one of the 2 documents.
    assert _count("document", tenant_id) == 2


async def test_one_bad_document_does_not_abort_the_run(tenant_id: uuid.UUID, corpus: Path) -> None:
    """A 500-document corpus must not be stopped by one unreadable file."""
    open(corpus / "empty.md", "w", encoding="utf-8", newline="\n").write("   \n")

    report = await _run(tenant_id, corpus)

    assert report.documents_failed == 1
    assert report.documents_created == 2  # the good ones still landed
    assert len(report.failures) == 1
    assert "empty.md" in report.failures[0][0]


async def test_ingestion_is_scoped_to_its_tenant(tenant_id: uuid.UUID, corpus: Path) -> None:
    """Documents must not leak into another tenant's knowledge base."""
    await _run(tenant_id, corpus)

    assert SETTINGS is not None
    with psycopg.connect(str(SETTINGS.database_url)) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM document WHERE tenant_id <> %s"
                " AND source_uri IN ('refunds.md', 'webhooks.md')",
                (tenant_id,),
            )
            row = cur.fetchone()
    assert row is not None
    assert int(row[0]) == 0

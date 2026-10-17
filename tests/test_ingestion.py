"""Loader and chunker behaviour, with no database involved."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db.models import SourceFormat
from app.ingestion import loaders
from app.ingestion.chunking import HeadingAwareChunker

MARKDOWN = """# Billing

Intro paragraph.

## Refunds

Refunds take 5 working days.

### Partial refunds

Only part of the order is refunded.
"""


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    open(path, "w", encoding="utf-8", newline="\n").write(body)
    return path


def test_markdown_title_comes_from_the_first_heading(tmp_path: Path) -> None:
    path = _write(tmp_path, "doc.md", MARKDOWN)

    document = loaders.load(path, root=tmp_path)

    assert document.title == "Billing"
    assert document.source_format is SourceFormat.MARKDOWN


def test_source_uri_is_relative_so_the_record_is_portable(tmp_path: Path) -> None:
    """The same corpus ingested from another absolute path is the same document."""
    path = _write(tmp_path, "billing/refunds.md", MARKDOWN)

    document = loaders.load(path, root=tmp_path)

    assert document.source_uri == "billing/refunds.md"


def test_content_hash_changes_only_when_content_changes(tmp_path: Path) -> None:
    first = loaders.load(_write(tmp_path, "a.md", MARKDOWN), root=tmp_path)
    same = loaders.load(_write(tmp_path, "b.md", MARKDOWN), root=tmp_path)
    different = loaders.load(_write(tmp_path, "c.md", MARKDOWN + "\nmore\n"), root=tmp_path)

    assert first.content_hash == same.content_hash
    assert first.content_hash != different.content_hash
    assert len(first.content_hash) == 64


def test_html_text_is_extracted_and_script_tags_dropped(tmp_path: Path) -> None:
    html = (
        "<html><head><title>Webhooks</title>"
        "<style>body{color:red}</style></head>"
        "<body><h1>Webhooks</h1><p>Delivered at least once.</p>"
        "<script>alert('x')</script><nav>Home</nav></body></html>"
    )
    path = _write(tmp_path, "page.html", html)

    document = loaders.load(path, root=tmp_path)

    assert document.title == "Webhooks"
    assert "Delivered at least once." in document.content
    # Script, style and nav content must not become retrievable text.
    assert "alert" not in document.content
    assert "color:red" not in document.content
    assert "Home" not in document.content


def test_unsupported_extension_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "data.csv", "a,b\n1,2\n")

    with pytest.raises(ValueError, match="Unsupported extension"):
        loaders.load(path, root=tmp_path)


def test_discover_finds_only_loadable_files_in_stable_order(tmp_path: Path) -> None:
    _write(tmp_path, "b/second.md", "# b")
    _write(tmp_path, "a/first.md", "# a")
    _write(tmp_path, "ignored.csv", "x")

    found = [p.name for p in loaders.discover(tmp_path)]

    assert found == ["first.md", "second.md"]


def test_chunks_carry_their_heading_breadcrumb() -> None:
    chunks = HeadingAwareChunker().split(MARKDOWN)

    paths = [c.heading_path for c in chunks]
    assert "Billing" in paths
    assert "Billing > Refunds" in paths
    assert "Billing > Refunds > Partial refunds" in paths


def test_chunk_ordinals_are_contiguous_from_zero() -> None:
    chunks = HeadingAwareChunker().split(MARKDOWN)

    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_oversized_sections_are_split_with_overlap() -> None:
    body = "# Big\n\n" + ("word " * 2000)
    chunker = HeadingAwareChunker(max_chars=400, overlap_chars=50)

    chunks = chunker.split(body)

    assert len(chunks) > 1
    assert all(c.char_count <= 400 for c in chunks)
    # Every chunk keeps its context, including the ones past the first.
    assert all(c.heading_path == "Big" for c in chunks)


def test_overlap_must_be_smaller_than_the_chunk() -> None:
    with pytest.raises(ValueError, match="overlap"):
        HeadingAwareChunker(max_chars=100, overlap_chars=100)


def test_a_short_document_is_one_chunk() -> None:
    chunks = HeadingAwareChunker().split("# Title\n\nOne short paragraph.")

    assert len(chunks) == 1
    assert chunks[0].heading_path == "Title"

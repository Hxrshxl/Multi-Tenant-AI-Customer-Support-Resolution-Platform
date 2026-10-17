"""Reading source documents off disk.

Format-agnostic on purpose. The corpus this project will eventually use has not
been chosen, so nothing here hardcodes a particular product's documentation —
it loads markdown, HTML and plain text from a directory, and the choice of
directory is the caller's problem.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from app.db.models import SourceFormat

logger = logging.getLogger(__name__)

#: Extension to format. Anything not listed is skipped rather than guessed at.
EXTENSIONS: dict[str, SourceFormat] = {
    ".md": SourceFormat.MARKDOWN,
    ".markdown": SourceFormat.MARKDOWN,
    ".html": SourceFormat.HTML,
    ".htm": SourceFormat.HTML,
    ".txt": SourceFormat.TEXT,
}

#: Guard against loading something absurd into memory. A support document
#: larger than this is almost certainly not a support document.
MAX_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class LoadedDocument:
    source_uri: str
    title: str | None
    content: str
    source_format: SourceFormat
    byte_size: int

    @property
    def content_hash(self) -> str:
        """SHA-256 of the content, hex encoded.

        Comparing this against the stored hash is what makes re-ingesting
        unchanged content free rather than a re-embed.
        """
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


class _TextExtractor(HTMLParser):
    """Pulls readable text out of HTML using only the standard library.

    Enough for documentation pages. Deliberately not a dependency: adding a
    parsing library for this would be a new runtime dependency to justify,
    review and keep patched, for a few dozen lines of behaviour.
    """

    _SKIP = frozenset({"script", "style", "nav", "footer", "head"})

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0
        self.title: str | None = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and self.title is None:
            self.title = data.strip() or None
        elif self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        joined = "".join(self._parts)
        # Collapse the blank-line soup that tag-stripping leaves behind.
        return re.sub(r"\n{3,}", "\n\n", joined).strip()


def _markdown_title(content: str) -> str | None:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or None
    return None


def discover(root: Path) -> Iterator[Path]:
    """Yield every loadable file under ``root``, in a stable order.

    Sorted so two runs process documents identically — which matters when a run
    is resumed after failing partway.
    """
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in EXTENSIONS:
            yield path


def load(path: Path, *, root: Path | None = None) -> LoadedDocument:
    """Read one file into a ``LoadedDocument``.

    Raises:
        ValueError: if the file is too large or its extension is unsupported.
        UnicodeDecodeError: if it is not valid UTF-8.
    """
    source_format = EXTENSIONS.get(path.suffix.lower())
    if source_format is None:
        raise ValueError(f"Unsupported extension: {path.suffix}")

    byte_size = path.stat().st_size
    if byte_size > MAX_BYTES:
        raise ValueError(f"File exceeds {MAX_BYTES} bytes: {byte_size}")

    raw = path.read_text(encoding="utf-8")

    if source_format is SourceFormat.HTML:
        extractor = _TextExtractor()
        extractor.feed(raw)
        content = extractor.text()
        title = extractor.title
    else:
        content = raw.strip()
        title = _markdown_title(raw) if source_format is SourceFormat.MARKDOWN else None

    # A relative URI keeps the record portable: the same corpus ingested from a
    # different absolute path is still the same document.
    uri = str(path.relative_to(root)) if root and root in path.parents else path.name
    return LoadedDocument(
        source_uri=uri.replace("\\", "/"),
        title=title or path.stem,
        content=content,
        source_format=source_format,
        byte_size=byte_size,
    )

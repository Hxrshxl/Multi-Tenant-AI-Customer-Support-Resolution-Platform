"""Splitting a document into retrievable chunks.

**This is a placeholder strategy, and that is deliberate.** KAN-19 compares at
least three strategies against the E3 retrieval metrics and picks a winner with
numbers behind it. Choosing one here by taste would make that card dishonest —
it would be documenting a default as if it had been measured.

What this does provide is the *shape* KAN-19 needs: a `ChunkStrategy` protocol,
so comparing strategies means writing new implementations rather than rewriting
the pipeline, and a heading path on every chunk, because a chunk stripped of its
context is often uninterpretable alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

#: Provisional. Roughly 250 words, which fits comfortably in any embedding
#: model's context while staying specific enough to retrieve precisely.
#: KAN-19 replaces this with a measured value.
DEFAULT_MAX_CHARS = 1500
DEFAULT_OVERLAP_CHARS = 200

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
#: Fenced code blocks. A shell comment inside one looks exactly like a
#: markdown heading, and real documentation is full of them — "# Restore
#: from a PITR backup" in a bash example became an H1 and corrupted the
#: breadcrumb of every section beneath it. Found by reading real output,
#: not by testing: the hand-written sample corpus had no code fences.
_FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    content: str
    heading_path: str | None

    @property
    def char_count(self) -> int:
        return len(self.content)


class ChunkStrategy(Protocol):
    """Splits document text into chunks. KAN-19 compares implementations."""

    name: str

    def split(self, content: str) -> list[Chunk]: ...


def _heading_path(stack: list[str]) -> str | None:
    return " > ".join(stack) if stack else None


class HeadingAwareChunker:
    """Splits on markdown headings, then by size within each section.

    Keeps a section together when it fits, because a heading and its paragraph
    belong in the same chunk. Oversized sections are split with an overlap so a
    sentence spanning the boundary is not lost from both halves.
    """

    name = "heading_aware"

    def __init__(
        self,
        max_chars: int = DEFAULT_MAX_CHARS,
        overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    ) -> None:
        if overlap_chars >= max_chars:
            raise ValueError("overlap must be smaller than max_chars")
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def split(self, content: str) -> list[Chunk]:
        sections = self._sections(content)
        chunks: list[Chunk] = []
        for heading_path, body in sections:
            for piece in self._split_body(body):
                chunks.append(Chunk(ordinal=len(chunks), content=piece, heading_path=heading_path))
        return chunks

    def _sections(self, content: str) -> list[tuple[str | None, str]]:
        """Group lines under their heading breadcrumb."""
        sections: list[tuple[str | None, str]] = []
        stack: list[str] = []
        buffer: list[str] = []
        current_path = _heading_path(stack)

        in_fence = False
        for line in content.splitlines():
            if _FENCE.match(line):
                in_fence = not in_fence
                buffer.append(line)
                continue

            # Inside a fence, a leading '#' is a comment, not a heading.
            match = None if in_fence else _HEADING.match(line.strip())
            if match is None:
                buffer.append(line)
                continue

            body = "\n".join(buffer).strip()
            if body:
                sections.append((current_path, body))
            buffer = []

            level = len(match.group(1))
            title = match.group(2).strip()
            # Pop to the parent level, then push this heading.
            del stack[level - 1 :]
            stack.append(title)
            current_path = _heading_path(stack)
            # Keep the heading itself in the chunk: it is often the clearest
            # statement of what the section is about.
            buffer.append(line.strip())

        body = "\n".join(buffer).strip()
        if body:
            sections.append((current_path, body))
        return sections

    def _split_body(self, body: str) -> list[str]:
        if len(body) <= self.max_chars:
            return [body]

        pieces: list[str] = []
        start = 0
        while start < len(body):
            end = min(start + self.max_chars, len(body))
            if end < len(body):
                # Prefer a paragraph break, then a sentence end, then a space,
                # so chunks rarely begin mid-word.
                window = body[start:end]
                for sep in ("\n\n", ". ", " "):
                    cut = window.rfind(sep)
                    if cut > self.max_chars // 2:
                        end = start + cut + len(sep)
                        break
            piece = body[start:end].strip()
            if piece:
                pieces.append(piece)
            if end >= len(body):
                break
            start = max(end - self.overlap_chars, start + 1)
        return pieces


#: The strategy the pipeline uses until KAN-19 replaces it with a measured one.
DEFAULT_STRATEGY: ChunkStrategy = HeadingAwareChunker()

#!/usr/bin/env python
"""Fetch the evaluation knowledge base from upstream documentation.

    python scripts/fetch_corpus.py

Why a script rather than committed documents:

- **Licensing.** The corpus is someone else's work. Fetching it at setup time
  means this repository never redistributes it.
- **Size.** The repository stays small.
- **Reproducibility.** The upstream ref is *pinned to a commit*, not a branch.
  That matters more than it looks: the eval dataset labels reference documents
  by URI, so if upstream docs moved under us the labels would rot silently and
  every retrieval number would drift for reasons unrelated to our code.

Changing ``UPSTREAM_REF`` invalidates the dataset labels. Treat it as a
dataset-versioning decision, not a dependency bump.
"""

from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

UPSTREAM_REPO = "supabase/supabase"
#: Pinned deliberately. See the module docstring before changing it.
# A git commit SHA is a 40-character hex string, so the secret scanner reads it
# as high entropy. It is public by definition and has to live in the source.
UPSTREAM_REF = "7425d4930528931400fb3e656e860b1094cb224e"  # pragma: allowlist secret
UPSTREAM_LICENCE = "Apache-2.0"
DOCS_PREFIX = "apps/docs/content/guides"

#: Curated for support-ticket shape rather than completeness. Billing and
#: platform docs map to the billing and refund intents; auth and database to
#: technical; getting-started to general.
WANTED_DIRS = (
    "platform",
    "auth",
    "database",
    "getting-started",
)

DESTINATION = Path("knowledge-base/supabase")
TREE_API = f"https://api.github.com/repos/{UPSTREAM_REPO}/git/trees/{UPSTREAM_REF}?recursive=1"
RAW_BASE = f"https://raw.githubusercontent.com/{UPSTREAM_REPO}/{UPSTREAM_REF}"

#: MDX is markdown plus JSX. The JSX is presentational and would otherwise end
#: up in retrievable text as noise.
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_TITLE = re.compile(r"^title:\s*['\"]?(.+?)['\"]?\s*$", re.MULTILINE)
_IMPORTS = re.compile(r"^(import|export)\s.+$", re.MULTILINE)
_JSX_COMMENT = re.compile(r"\{/\*.*?\*/\}", re.DOTALL)
_JSX_TAG = re.compile(r"</?[A-Z][A-Za-z0-9]*(\s[^>]*?)?/?>", re.DOTALL)
_BLANK_RUN = re.compile(r"\n{3,}")


@dataclass
class FetchReport:
    considered: int = 0
    written: int = 0
    skipped_empty: int = 0
    failed: int = 0


def mdx_to_markdown(raw: str) -> tuple[str, str | None]:
    """Strip MDX machinery, returning (markdown, title)."""
    title: str | None = None
    match = _FRONTMATTER.match(raw)
    if match:
        found = _TITLE.search(match.group(1))
        if found:
            title = found.group(1).strip()
        raw = raw[match.end() :]

    raw = _IMPORTS.sub("", raw)
    raw = _JSX_COMMENT.sub("", raw)
    raw = _JSX_TAG.sub("", raw)
    body = _BLANK_RUN.sub("\n\n", raw).strip()

    if title and not body.startswith("# "):
        body = f"# {title}\n\n{body}"
    return body, title


def _get(url: str) -> bytes:
    # Reject anything that is not https before opening it. urlopen will happily
    # follow file: and custom schemes, which is how a "fetch a URL" helper turns
    # into a local file read. The URLs here are built from constants, but the
    # guard costs nothing and survives someone making them configurable later.
    if not url.startswith("https://"):
        raise ValueError(f"Refusing a non-https URL: {url!r}")
    request = urllib.request.Request(  # noqa: S310 - scheme checked above
        url, headers={"User-Agent": "support-platform-corpus"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return bytes(response.read())


def list_doc_paths() -> list[str]:
    import json

    tree = json.loads(_get(TREE_API))
    paths: list[str] = []
    for entry in tree.get("tree", []):
        path = entry.get("path", "")
        if entry.get("type") != "blob" or not path.endswith(".mdx"):
            continue
        if not path.startswith(DOCS_PREFIX + "/"):
            continue
        relative = path[len(DOCS_PREFIX) + 1 :]
        top = relative.split("/")[0].removesuffix(".mdx")
        if top in WANTED_DIRS:
            paths.append(path)
    return sorted(paths)


def fetch(destination: Path = DESTINATION) -> FetchReport:
    report = FetchReport()
    destination.mkdir(parents=True, exist_ok=True)

    for path in list_doc_paths():
        report.considered += 1
        relative = path[len(DOCS_PREFIX) + 1 :].removesuffix(".mdx")
        target = destination / f"{relative}.md"
        try:
            body, _ = mdx_to_markdown(_get(f"{RAW_BASE}/{path}").decode("utf-8"))
            # A page that is only JSX leaves nothing retrievable behind.
            if len(body) < 200:
                report.skipped_empty += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8", newline="\n")
            report.written += 1
        except (urllib.error.URLError, OSError, UnicodeDecodeError) as exc:
            report.failed += 1
            print(f"  FAILED {path}: {exc}", file=sys.stderr)

    (destination / "PROVENANCE.md").write_text(
        "# Corpus provenance\n\n"
        "Fetched by `scripts/fetch_corpus.py`. **Not committed to this repository** —\n"
        "it is third-party content and is downloaded at setup time instead.\n\n"
        f"| | |\n|---|---|\n"
        f"| Source | `{UPSTREAM_REPO}` |\n"
        f"| Path | `{DOCS_PREFIX}` |\n"
        f"| Pinned ref | `{UPSTREAM_REF}` |\n"
        f"| Licence | {UPSTREAM_LICENCE} |\n"
        f"| Directories | {', '.join(WANTED_DIRS)} |\n\n"
        "The ref is pinned to a commit rather than a branch because the eval\n"
        "dataset labels reference these documents by URI. Changing the ref\n"
        "invalidates those labels, so it is a dataset-versioning decision.\n\n"
        "Apache-2.0 permits use and redistribution with attribution. Its\n"
        "trademark clause means this project must not imply endorsement by or\n"
        "affiliation with the upstream project. It does not, and this corpus is\n"
        "used solely as realistic evaluation input.\n",
        encoding="utf-8",
        newline="\n",
    )
    return report


def main() -> int:
    print(f"Fetching {UPSTREAM_REPO} docs at {UPSTREAM_REF[:12]} ...")
    report = fetch()
    print(f"\n  considered    {report.considered}")
    print(f"  written       {report.written}")
    print(f"  skipped empty {report.skipped_empty}")
    print(f"  failed        {report.failed}")
    return 1 if report.written == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())

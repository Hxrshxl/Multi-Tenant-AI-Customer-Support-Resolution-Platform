# Session log

Running development history. **Read this first in any new session**, then
confirm against reality (`git log`, `git status`, the Jira board) before acting
— this file records what *was* true when it was written.

Newest entries first. History is never deleted.

---

## Current state

| | |
|---|---|
| **Epic 1 (Foundation)** | Complete — all 5 cards merged to `main` |
| **Epic 2 (Retrieval)** | KAN-18 merged (PR #5). KAN-19 to 22 blocked on Epic 3 |
| **Epic 3 (Evaluation)** | KAN-23 **partially done** — corpus acquired, dataset not authored |
| **Merged PRs** | #1 (KAN-13), #2 (KAN-14, KAN-16, KAN-15), #3 (KAN-17) |
| **Current branch** | `kan-23-eval-dataset` (off `main`) |
| **Overall progress** | 6 of 53 stories · ~26 of ~320 points · **~8%** |
| **Next up** | Finish KAN-23: author the labelled ticket dataset |

**What runs right now:** `POST /v1/tickets` accepts a ticket, persists it
against a tenant, passes it through a placeholder resolver, persists a canned
reply, and marks the ticket resolved — all in one transaction, fully traceable
by a correlation ID. Baseline p95: 26.8 ms.

**What does not exist yet:** any AI, any retrieval, any real action, any tenant
isolation enforcement, any user interface.

### Open items carried forward

1. **Jira statuses are not synced.** All 5 E1 cards are built and merged, but
   the board shows KAN-13/14 as *In Dev*, KAN-15/16/17 as *To Do*, and all 15
   subtasks as *Idea*. The user manages status; it has deliberately not been
   touched.
2. **`docs/build-log.md` has no KAN-17 section yet.**
3. **Eval data source is still undecided.** Does not block the next card, but
   gates KAN-23, which gates every quality number this project will claim.
4. **Event loop policy has a deadline.** Python 3.16 removes event loop
   policies. See ADR-005; Epic 12's Celery worker will need a fourth entry
   point applying it.
5. **One-transaction-per-request will not survive Epic 5.** A transaction must
   not stay open across model calls. Planned shape recorded in `docs/seams.md`.

### Epic 2 is blocked after one card

KAN-19, 20, 21 and 22 form a chain, and the chain is gated on Epic 3, not on
each other. Their own dependency lines say so:

| Card | Blocked by |
|---|---|
| KAN-19 chunking | ingestion **+ the E3 retrieval metrics** |
| KAN-20 embeddings | chunking |
| KAN-21 hybrid retrieval | embeddings |
| KAN-22 query rewriting | hybrid retrieval |

KAN-19, 21 and 22 each require being "measured on the E3 eval set". That set
does not exist. Choosing a chunking strategy without it means picking a default
and writing "measured" beside it, which is worse than not doing the card.

**Two decisions are needed to unblock the rest:**

1. **The eval/knowledge-base data source** (open since the project started).
   This gates KAN-23, which gates KAN-25, which gates KAN-19.
2. **An embedding provider.** KAN-20 needs real embeddings. Either an API key
   (costs money, and it would be the user's key) or a local model
   (`sentence-transformers`, free, large download, slow on CPU). This also
   fixes the vector dimension, which the schema needs.

**Recommended order:** KAN-23 → KAN-24 → KAN-25 (Epic 3) and then return to
KAN-19. That is why the backlog made Epic 3 Highest priority and parallel to
Epic 2 rather than after it.

### Candidate next cards

- **KAN-23** (golden dataset) — unblocks every measurement. Needs the data
  source decision first.
- **KAN-18** (document ingestion) — starts Epic 2, the retrieval path.
- **KAN-27** (multi-channel intake) — extends what already works.

---

## 2026-10-17 — KAN-23 (part 1) · Real corpus acquired, and a chunker bug fixed

**Decisions taken** (both were the user's to make, and both were asked for):

- **Eval data source: real public product documentation.** Supabase docs,
  Apache-2.0, pinned to commit `7425d493`. Checked Medusa first and rejected it:
  MIT *except* Enterprise Edition materials, and that ambiguity is not worth
  inheriting.
- **Embeddings: a local model, no API key.** Confirmed by survey that no
  embedding API key exists on this machine, so KAN-20 was genuinely blocked
  rather than merely undecided.

**What was done.** `scripts/fetch_corpus.py` fetches the corpus at setup time
rather than vendoring it — the repository never redistributes third-party
content, stays small, and pins the upstream *commit* rather than a branch.
Pinning matters because the dataset labels will reference documents by URI; a
moving branch would rot the labels silently and drift every retrieval number
for reasons unrelated to our code.

**Files touched:** `scripts/fetch_corpus.py` (new),
`app/ingestion/chunking.py`, `tests/test_ingestion.py`, `.gitignore`.

**The bug worth remembering.** Inspecting real heading paths revealed breadcrumbs
like `Restore from a PITR backup (replace Unix timestamp...)` — not a heading at
all, but a **shell comment inside a fenced code block**. The heading regex
matched `#` at the start of any line, including inside fences, so a bash comment
became an H1 and corrupted the breadcrumb of every section beneath it.

Real documentation is full of commented shell examples. The hand-written sample
corpus had no code fences, so five documents and sixteen tests never saw it.
**Reading the real output is what found it**, not the test suite. Fixed, with
two regression tests; chunk count fell 4,134 to 3,985 as the spurious splits
disappeared.

**Also found: changing the chunker does not trigger re-chunking.** The content
hash compares *document content*, which has not changed, so every document is
skipped. Re-chunking currently requires clearing the documents by hand. KAN-19
compares chunking strategies and will need a deliberate way to force it.

**Where it stands.** Verified: 310 documents fetched, 0 failures; ingested in 23
seconds producing 3,985 chunks; mean chunk 626 chars, median 481, p95 1,459,
100% carrying a heading path. 21% are still under 200 characters, which is a
measured finding for KAN-19 rather than something to tune by instinct now.
57 tests pass, strict mypy clean.

**KAN-23 is NOT complete.** Done: data source chosen, provenance and licensing
recorded, corpus acquired and ingested. Not done: the dataset schema, the
150-200 labelled tickets, the hard/should-escalate/adversarial quotas, the
loader and the integrity tests. That is the next piece of work.
---

## 2026-10-17 — KAN-18 · Document ingestion pipeline

**What was done.** Knowledge-base ingestion: loaders for markdown, HTML and
text; a heading-aware chunker behind a swappable protocol; a pipeline that is
idempotent, resumable and isolates per-document failures; a CLI command; and a
five-document sample corpus.

**Files touched:** `app/ingestion/{__init__,loaders,chunking,pipeline}.py`,
`app/db/models.py` (document, document_chunk, SourceFormat),
`alembic/versions/20261017_1157_document_and_chunk_tables.py`, `app/cli.py`,
`knowledge-base/` (5 docs), `tests/test_ingestion.py`,
`tests/test_ingestion_integration.py`, `tests/__init__.py`, `pyproject.toml`.

**Key decisions.**

- **No embedding column.** Vectors arrive with KAN-20. Keeping them out means
  ingestion is runnable and testable with no API key and no cost, which matters
  because KAN-19 will re-run it many times.
- **One transaction per document, not per run.** This is what makes the
  pipeline atomic (chunks replaced wholesale), resumable (a run that dies at
  document 400 keeps 399) and failure-isolating, all at once.
- **The chunker is deliberately not tuned.** It sits behind a `ChunkStrategy`
  protocol so KAN-19 compares implementations rather than rewriting the
  pipeline. Choosing a strategy by taste here would make KAN-19 dishonest.

**Issues hit.**

- The migration left the `source_format` enum behind on downgrade — the **same
  trap as KAN-15**. Caught this time by checking before applying.
- Per-document failures logged a full traceback for *expected* problems (an
  empty file), which is noise in a 500-document run. Split into expected
  (`ValueError`/`OSError`/`UnicodeDecodeError`, no trace) and unexpected
  (full trace).
- Three real lint/type findings fixed properly rather than suppressed: `B008`
  on Typer defaults (configured `extend-immutable-calls`), `S608` SQL built
  from a variable in a test (replaced with explicit queries), and a `rowcount`
  type error (cast to `CursorResult`).

**Where it stands.** Verified against the live stack: first run created 5
documents and 20 chunks; second run skipped all 5 by content hash and wrote 0
chunks; changing one document replaced 4 chunks with 5 and left the other 4
documents untouched; an empty file failed in isolation while the rest landed.
Migration round-trips. 55 tests pass (16 new), strict mypy clean.

**Two honest findings.**

- **The cost saving from content hashing is negligible** at this scale:
  ~$0.000016 per avoided re-run, ~$0.03 even at 10,000 documents. The DoD asked
  for it measured, and measurement says its real value is time and correctness,
  not money.
- **Mean chunk size is 153 characters**, which is probably too small for good
  retrieval — every small heading section becomes its own chunk. Deliberately
  not tuned; that is KAN-19's job, with numbers.

**Next steps.** Epic 2 is blocked. See the state block above.
---

## 2026-10-17 — Development workflow configured

**What was done.** Set up the session-tracking, review and documentation
workflow the user requested.

**Files touched:** `CLAUDE.md` (new), `session.md` (new, this file),
`Project-Management/CHANGELOG.md` (new).

**Issues hit.** The user asked for `session.mv`. There is no `.mv` markdown
convention — GitHub and VS Code will not render it, which defeats the purpose
of a readable history. Created as `session.md` and flagged; renaming is one
line if the user prefers the original.

**Where it stands.** Configured and committed. Not yet exercised on a real card
— the first proper test is whichever card comes next.

**Next steps.** Pick the next card and run the full workflow on it end to end.

---

## 2026-10-17 — KAN-17 · Thin vertical slice (completes Epic 1)

**What was done.** Wired the whole path: `POST /v1/tickets` to persisted ticket
to resolver to persisted reply to terminal state, in one transaction. Added the
`Resolver` protocol, which is the seam Epic 5 replaces.

**Files touched:** `app/api/routes/tickets.py`, `app/api/deps.py`,
`app/services/intake.py`, `app/services/resolution.py`,
`app/repositories/tickets.py`, `app/main.py`,
`tests/test_intake_integration.py`, `docs/seams.md`, `docs/adr/005-*.md`.

**Issues hit.**

- Integration tests failed with the `ProactorEventLoop` error, because **pytest
  creates its own event loop** and nothing applied the policy. ADR-005 had
  predicted exactly this. Fixed in `tests/conftest.py`.
- `record_resolution` took `float` for money. Changed to `Decimal` — money
  never touches a binary float.
- The deprecation warning leaked, because reading the attribute triggers it
  outside the suppression block.

**Where it stands.** Merged (PR #3). Verified live, not only in tests: 201 on
create, 200 on resubmit with one row, 404 for unknown tenant, 422 naming
missing fields, and a failure injected at the resolver leaving **zero** rows.
Baseline latency over 25 requests: median 25.0 ms, p95 26.8 ms.

**Next steps.** Epic 1 is done. Choose Epic 2, or the eval dataset first.

---

## 2026-10-17 — KAN-16 · ADRs, and KAN-15 · Core data model

**What was done.** Five architecture decision records with numeric targets and
a risk register. Then seven database tables with integrity pushed into the
database, Alembic configured, and idempotent seeding.

**Files touched:** `docs/adr/` (6 files),
`app/db/{base,models,session,seed}.py`, `app/core/runtime.py`,
`app/__main__.py`, `alembic.ini`, `alembic/env.py`,
`alembic/versions/20261017_0027_core_data_model.py`, `app/cli.py`,
`tests/test_models.py`, `docs/schema.md`.

**Issues hit.**

- A **native Postgres on the host held port 5432**, silently rejecting our
  credentials — which looked identical to a wrong password. Republished on
  5433.
- My first model draft created **six redundant indexes**, duplicating
  composite indexes that already led with `tenant_id`. Each would have taxed
  every write for no read benefit.
- **The migration did not round-trip.** Alembic drops tables on downgrade but
  leaves Postgres enum types behind, so a second upgrade failed with
  `type "channel" already exists`. The downgrade now drops them explicitly.

**Where it stands.** Merged (PR #2). All constraints verified against live
Postgres with a control insert proving they reject the right things rather than
everything. Seeded 100 tickets across two tenants.

---

## 2026-10-16 — KAN-14 · Service skeleton

**What was done.** Correlation IDs, structured JSON logging with credential
redaction, one error envelope, and split liveness/readiness probes.

**Files touched:** `app/core/{correlation,logging,middleware,errors}.py`,
`app/clients/`, `app/services/health.py`, `app/api/`, `app/main.py`, five test
files.

**Issues hit.**

- **500 responses carried no correlation header.** Starlette's
  `ServerErrorMiddleware` sits outside application middleware and writes its
  own response, so the header was missing on exactly the responses most likely
  to be reported to support. Found by calling the real server, not by tests.
- **`psycopg` async refuses Windows' default event loop**, so readiness
  reported a healthy database as unreachable.

**Where it stands.** Merged (PR #2, stacked). Later verified by actually
stopping Redis: readiness went 503 with postgres still healthy, liveness stayed
200, and it recovered unaided.

---

## 2026-10-16 — KAN-13 · Repository scaffold

**What was done.** One-command local stack, pinned dependencies, fail-fast
configuration, one quality command, ten pre-commit hooks.

**Files touched:** `.gitignore`, `.gitattributes`, `.dockerignore`,
`requirements*.txt`, `pyproject.toml`, `app/{__init__,config,main,cli}.py`,
`docker-compose.yml`, `Dockerfile`, `docker/postgres/init.sql`,
`scripts/check.py`, `.pre-commit-config.yaml`, `.secrets.baseline`,
`README.md`.

**Issues hit.** `app/main.py` instantiated the app at module level, calling
config at import time and breaking test collection immediately. Converted to a
factory rather than patching the test. Swapped `httpx` for `httpx2` after a
Starlette deprecation warning.

**Where it stands.** Merged (PR #1). Docker was not running at the time, so the
compose stack stayed unverified until the KAN-15 session — which is how the
port 5432 clash went unnoticed for two cards.

---

## 2026-10-16 — Jira backlog created

12 epics, 52 stories, 15 subtasks, ~30 dependency links.

Three constraints discovered by inspecting the board before creating anything:
Jira supports only 3 hierarchy levels (so the requested
Epic → Story → Task → Subtask was impossible), Priority and Estimation were
disabled on the project, and only one real user exists so the personas cannot
be assignees. Story points therefore live in labels.

---

## 2026-10-16 — Team personas and project specification

Created `Team/` (8 discipline personas plus a README defining ownership
boundaries, the working agreement and conflict resolution), the
`.claude/agents/` equivalents, and `project idea.md`.

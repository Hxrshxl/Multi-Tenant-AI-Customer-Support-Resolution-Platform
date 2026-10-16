# Session log

Running development history. **Read this first in any new session**, then
confirm against reality (`git log`, `git status`, the Jira board) before acting
— this file records what *was* true when it was written.

Newest entries first. History is never deleted.

---

## Current state

| | |
|---|---|
| **Epic 1 (Foundation)** | Complete — all 5 cards built and merged to `main` |
| **Merged PRs** | #1 (KAN-13), #2 (KAN-14, KAN-16, KAN-15), #3 (KAN-17) |
| **Current branch** | `chore/dev-workflow` |
| **Overall progress** | 5 of 53 stories · ~21 of ~320 points · **~7%** |
| **Next up** | Not yet chosen. Candidates below. |

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

### Candidate next cards

- **KAN-23** (golden dataset) — unblocks every measurement. Needs the data
  source decision first.
- **KAN-18** (document ingestion) — starts Epic 2, the retrieval path.
- **KAN-27** (multi-channel intake) — extends what already works.

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

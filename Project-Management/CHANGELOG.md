# Changelog

What changed, why, how it works, and what is still incomplete — written for
someone building their first production-level project. Jargon is explained the
first time it appears.

**This file answers "what changed and how does it work?"**
For "why does this matter commercially?", read
[`docs/build-log.md`](../docs/build-log.md) instead. The two are deliberately
kept separate so neither becomes a dumping ground.

Newest first.

---

## Terminology, in plain words

Terms used throughout this file. None of them are as complicated as they sound.

| Term | What it actually means |
|---|---|
| **Migration** | A versioned change to the database's structure (adding a table, a column, an index). Versioned so you can move forward *and backward* through them. |
| **Idempotent** | Doing it twice has the same effect as doing it once. Sending the same ticket twice creates one ticket, not two. |
| **Constraint** | A rule the database itself enforces. Breaking it makes the `INSERT` fail. The data cannot be wrong, as opposed to *should* not be wrong. |
| **Index** | A lookup shortcut. Makes reading faster and writing slower, so it is only worth adding for queries you actually run. |
| **Middleware** | Code that runs around every request, before and after your actual handler. Good for things every request needs, like a tracking number. |
| **Fixture** | In tests: reusable setup. "Give me a fresh tenant for this test, and delete it afterwards." |
| **Transaction** | A group of database writes that all succeed or all fail. No half-states. |
| **Factory** | A function that *builds* an object, instead of the object being created when the file is imported. Makes testing far easier. |
| **Protocol** | A described shape. "Anything with a `resolve()` method that returns a draft." Lets you swap implementations without changing callers. |
| **DSN / connection URL** | The database address, e.g. `postgresql://<user>:<password>@host:5432/dbname`. |
| **Lockfile** | A record of the exact version of every library, so everyone installs identically. |
| **Pre-commit hook** | A check that runs automatically before a commit is saved, and can block it. |
| **p95** | The 95th percentile. "p95 is 27 ms" means 95% of requests were faster than 27 ms. More honest than an average, which one slow request can hide. |
| **Seam** | A deliberate joint in the code where a piece can be swapped out later without disturbing its neighbours. |
| **Row-level security (RLS)** | The database itself refusing to return rows outside your tenant — even if the application code forgot to filter. Not built yet; Epic 9. |

---

## 2026-10-17 — Development workflow configured

### What changed

Three new files:

| File | Purpose |
|---|---|
| `CLAUDE.md` | Permanent instructions Claude reads in every session |
| `session.md` | Running development history, newest first |
| `Project-Management/CHANGELOG.md` | This file |

### Why

A new chat has **no memory** of previous ones. Without a written record, every
session starts by re-deriving what already exists — and worse, risks redoing or
contradicting earlier work.

### How it works

`CLAUDE.md` is read automatically by Claude Code at the start of a session. It
instructs: read `session.md` first, follow a fixed workflow, review before
committing, keep both documents current.

The workflow is:

```
Read session.md → Understand context → Implement → Test
→ Update session.md → Update CHANGELOG → Review code
→ Fix issues → Final checks → Commit
```

Updating the documents comes **before** the review on purpose. Writing down
what you did is often how you notice you did not finish it.

### One deliberate deviation

You asked for `session.mv`. There is no `.mv` markdown format — GitHub and
VS Code would show it as plain text rather than rendering the tables and
headings, which defeats the purpose. Created as `session.md`.

Renaming is one command if you prefer the original:

```bash
git mv session.md session.mv
```

### What is incomplete

The workflow has not yet been exercised on a real card. Its first real test is
the next one.

---

## 2026-10-17 — KAN-18 · Document ingestion

### What changed

The knowledge base can now be loaded from a directory of documents.

| File | What it does |
|---|---|
| `app/ingestion/loaders.py` | Reads markdown, HTML and text off disk |
| `app/ingestion/chunking.py` | Splits documents into retrievable pieces |
| `app/ingestion/pipeline.py` | Runs the whole thing, idempotently |
| `app/db/models.py` | Two new tables: `document`, `document_chunk` |
| `knowledge-base/` | Five sample support documents |

### Why

This is the entry point to the whole retrieval path. Nothing can be searched
until something has been loaded and split up.

### How it works

```bash
alembic upgrade head                                    # create the new tables
python -m app.cli ingest --tenant acme --path knowledge-base
```

Output:

```
  documents seen       5
  created              5
  unchanged (skipped)  0
  failed               0
  chunks written       20
```

**Run it again** and every document is skipped:

```
  created              0
  unchanged (skipped)  5
  chunks written       0
```

**Why documents get chopped up.** Search works on *pieces*, not whole pages. If
you store a 50-page manual as one blob, a search for "export error E_4210"
returns the whole manual, which is useless. Splitting it means the search
returns the paragraph that actually answers the question. Each piece is a
**chunk**.

Each chunk keeps a breadcrumb of the headings above it, e.g.
`Billing > Refunds > Partial refunds`. Without it, a chunk reading "Only part of
the order is refunded" has lost the context that makes it meaningful.

**How re-running stays cheap.** Every document is stored with a **content
hash** — a short fingerprint of its text (SHA-256). Change one character and the
fingerprint changes completely. On each run, the stored fingerprint is compared
with the file's: identical means skip, different means re-process. This is the
same idea as a checksum on a download.

**One transaction per document, not per run.** A transaction is a group of
database writes that all succeed or all fail. Doing one *per document* buys
three things at once:

- *Atomic replace* — when a document changes, its old chunks are deleted and new
  ones written together, so a search never sees a half-reindexed document.
- *Resumable* — a run that dies at document 400 of 500 keeps the first 399. The
  next run finds them unchanged and skips them, so "resuming" is just running it
  again.
- *Failure isolation* — one malformed file rolls back only itself.

A single transaction for the whole run would be simpler and would lose all
three.

### Verified, not assumed

| Test | Result |
|---|---|
| First run | 5 documents, 20 chunks |
| Second run | 5 skipped, 0 chunks written |
| One document edited | 1 updated, 4 skipped, 4 chunks replaced by 5 |
| Empty file added | failed in isolation; the other 5 still processed |
| Migration round-trip | upgrade → downgrade → upgrade, all clean |

### Two honest findings

**1. The cost saving from hashing is negligible.** The card asked for it
measured. Measured:

| | |
|---|---|
| 21 chunks, 3,206 characters | ~802 tokens |
| Cost to embed once | ~$0.000016 |
| Even at 10,000 documents | ~$0.03 per avoided re-run |

So the content hash is **not** a cost optimisation at this scale. Its real value
is *time* (not re-processing) and *correctness* (not duplicating). Saying so is
more useful than quoting a saving that rounds to zero.

**2. The chunks are probably too small.** Mean size is 153 characters, because
the splitter gives every small heading section its own chunk. That is likely
bad for retrieval — too little context per piece.

**It was deliberately left alone.** KAN-19 exists to compare chunking
strategies *by measurement*. Tuning it here by instinct would make that card a
rubber stamp. The chunker therefore sits behind a swappable interface
(`ChunkStrategy`) so KAN-19 writes new implementations rather than rewriting the
pipeline.

### Bugs caught during review

- **The migration left a data type behind on rollback** — the same trap as
  KAN-15. Caught this time *before* applying, by checking the generated
  downgrade.
- **Expected failures printed full stack traces.** An empty file is a handled
  problem; a traceback for it is noise in a 500-document run. Now split:
  expected problems log a one-line reason, genuine surprises keep the trace.
- **Three linter findings fixed properly, not silenced.** A SQL query built
  from a variable in a test was rewritten with explicit queries; the Typer
  false positive was fixed by configuring the linter rather than scattering
  `noqa` comments.

### What is incomplete

- **No embeddings.** Chunks are stored as text only. Vectors are KAN-20.
- **Nothing can be searched yet.** Storing chunks is not retrieval.
- **The corpus is a 5-document placeholder** written for this card. The real
  data source is still undecided — and that decision blocks the rest of Epic 2.
---

## 2026-10-17 — KAN-17 · The vertical slice (Epic 1 complete)

### What changed

A ticket can now be submitted over HTTP and come back resolved.

| File | What it does |
|---|---|
| `app/api/routes/tickets.py` | The `POST /v1/tickets` endpoint |
| `app/services/intake.py` | Orchestrates the flow; owns state transitions |
| `app/services/resolution.py` | **The seam** — the `Resolver` protocol |
| `app/repositories/tickets.py` | Every SQL query for the ticket lifecycle |
| `app/api/deps.py` | One database transaction per request |
| `tests/test_intake_integration.py` | Four tests against a real database |
| `docs/seams.md` | Where each remaining epic plugs in |

### Why

Before building breadth, prove the plumbing. One real feature through every
layer — HTTP, service, database, logging, error handling — catches wiring
problems while they are still cheap. If you build ten features first, you find
the same problem ten times.

### How it works

**Try it:**

```bash
docker compose up -d
python -m app
```

Then, in another terminal:

```bash
curl -X POST http://127.0.0.1:8000/v1/tickets \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Slug: acme" \
  -d '{
        "external_ref": "demo-001",
        "channel": "email",
        "body": "My export keeps failing.",
        "customer": {"external_id": "cust-1", "email": "a@b.example"}
      }'
```

You get back:

```json
{"ticket_id": "c33171cc-...", "status": "resolved", "reply": "Thanks for getting in touch — ..."}
```

Send the **exact same request again** and the status code changes from `201` to
`200`, with the same `ticket_id`. That is idempotency: the `external_ref` field
is the caller's own identifier for the message, and resubmitting it returns the
existing ticket instead of creating a duplicate. This matters because webhooks
retry automatically and users double-click buttons.

**The seam.** This is the most important idea in the card. In
`app/services/resolution.py`:

```python
class Resolver(Protocol):
    async def resolve(self, ticket, messages) -> ResolutionDraft: ...
```

A `Protocol` is a described *shape*: anything with a `resolve()` method
returning a draft qualifies. Today the only implementation returns a canned
sentence. In Epic 5, a LangGraph workflow implements the same shape, and the
only line that changes is in `app/main.py`:

```python
app.state.intake_service = IntakeService(resolver=PlaceholderResolver())
#                                                 ^^^^^^^^^^^^^^^^^^^ becomes WorkflowResolver()
```

Nothing else moves. That is what a seam buys you.

**Why the resolver returns a draft instead of saving.** It would be simpler to
let it write to the database directly. It deliberately does not, because Epic 8
needs to *pause* between deciding and acting so a human can approve a refund.
You cannot pause between deciding and writing if deciding writes.

**One transaction per request.** In `app/api/deps.py`:

```python
async with session_scope(request.app.state.session_factory) as session:
    yield session
```

Everything the handler writes — the ticket, both messages, the resolution — is
inside one transaction. If anything raises, it all rolls back. There is a test
that proves it: it swaps in a resolver that throws, submits a ticket, and
asserts **zero** rows exist afterwards, even though the ticket was written
before the resolver ran.

### Bugs found, and what they teach

**1. pytest needed the event loop fix too.**

The integration tests failed with the same `ProactorEventLoop` error from
KAN-14. ADR-005 had explicitly predicted this: *any entry point that bypasses
our helper reproduces the error*. pytest creates its own event loop, so it is
an entry point. Fixed in `tests/conftest.py`.

**The lesson:** when you write down a risk, go and check whether you have
already walked into it.

**2. Money was typed as `float`.**

`record_resolution` accepted `cost_usd: float`. Binary floating point cannot
represent `0.10` exactly — `0.1 + 0.2` is famously not `0.3`. Changed to
`Decimal`. The database column was always `numeric`; the Python side had
drifted.

### Measured

25 requests, full path, two database round trips:

| | |
|---|---|
| median | 25.0 ms |
| **p95** | **26.8 ms** |
| max | 32.1 ms |

This is the floor — before any AI exists. The target for the finished product
is a p95 of 8 seconds, so roughly 300× headroom. Recording it now is what makes
"did we get slower?" answerable later.

### What is incomplete

- The tenant arrives in an `X-Tenant-Slug` **header**, so any caller can claim
  to be any tenant. Real authentication is Epic 9. **This must not be exposed
  publicly before then.**
- The reply is a fixed sentence. No AI, no retrieval, no actions.
- One-transaction-per-request is correct today but **will not survive Epic 5** —
  a transaction must not stay open across slow model calls. The replacement
  shape is recorded in `docs/seams.md`.

---

## 2026-10-17 — KAN-16 · Architecture decision records

### What changed

Six files in `docs/adr/` — five decisions plus an index carrying numeric targets
and a risk register.

### Why

Decisions get re-argued when nobody wrote down why. Six months on, someone asks
"why aren't we using a proper vector database?" and without a record that is a
week of re-investigation.

### How it works

Each record follows one shape: **Context** (what forced the decision),
**Options considered** (at least two real ones), **Decision**, and
**Consequences** — split into what it buys and **what it costs**.

The cost section is not optional. A decision record with no downsides is
marketing, not engineering.

### What is incomplete

Documents go stale. If a decision changes and the record is not updated, it
becomes actively misleading — worse than having no record.

---

## 2026-10-17 — KAN-15 · The database schema

### What changed

Seven tables: `tenant`, `customer`, `ticket`, `message`, `resolution`,
`action`, `audit_entry`. Plus Alembic (the migration tool), a seed command, and
`docs/schema.md`.

### Why

Everything above this needs somewhere to put data. More importantly: putting
the **rules** in the database means invalid data cannot be stored at all,
rather than merely should not be.

### How it works

**Apply the schema:**

```bash
alembic upgrade head     # create the tables
python -m app.cli seed   # load 2 tenants, 16 customers, 100 tickets
```

`alembic upgrade head` means "apply every migration up to the newest one".
`head` is the latest revision, like a branch tip in git.

**The core idea: constraints.** A constraint is a rule the database enforces.
For example, in the `ticket` table:

```sql
CHECK ((status IN ('resolved','escalated','failed')) = (resolved_at IS NOT NULL))
```

In English: *a ticket is in a finished state if and only if it has a completion
timestamp.* Try to break it:

```sql
INSERT INTO ticket (..., status, resolved_at) VALUES (..., 'resolved', NULL);
-- ERROR: violates check constraint "ck_ticket_terminal_status_requires_resolved_at"
```

Why bother? Because a "resolved" ticket with no resolution time **crashes
nothing**. It just quietly makes every "average resolution time" report wrong —
and that is the number you show a client.

Eight constraints were each tested by attempting the illegal insert, with a
valid insert alongside to prove they reject the *wrong* things rather than
everything.

**The one with money attached:**

```sql
UNIQUE (tenant_id, idempotency_key)
```

Each action carries an identity. If the application tries the same refund
twice, the second `INSERT` fails at the database rather than reaching the
payment provider — even if the retry logic above it is wrong.

### Bugs found, and what they teach

**1. Six redundant indexes.**

An index speeds reading and slows writing. My first draft indexed `tenant_id`
on every table — but most tables already had a *combined* index starting with
`tenant_id`, which the database uses for both. Six were pure overhead.

Caught by **reading the migration tool's output**, which lists every index it
is about to create.

**2. The migration could not be undone.**

It applied fine. It rolled back fine. Then it **failed to apply again**:

```
psycopg.errors.DuplicateObject: type "channel" already exists
```

Alembic drops tables on rollback but leaves behind the custom data types
(`enum`s) they used. The next attempt collided with the leftovers. The
downgrade now drops them explicitly.

**The lesson, and it is the important one:** a rollback you have never tested
is a hope, not a rollback. This one *looked* fine. It was broken only in the
exact case you need it — rolling back a bad deploy, then going forward again.

### What is incomplete

- **Tenant isolation is not enforced.** Every table has `tenant_id`, but
  nothing stops a buggy query crossing tenants yet. That is Epic 9.
- **The database does not enforce the *order* of ticket states.** It knows
  which states exist; the ordering lives in `TICKET_TRANSITIONS` in
  `app/db/models.py` and is enforced in the service layer.

---

## 2026-10-16 — KAN-14 · Service skeleton

### What changed

`app/core/` — correlation IDs, JSON logging with credential redaction, one
error format, and split health/readiness probes.

### Why

These are the conventions every endpoint built afterwards inherits for free.
Retrofitting them across fifty endpoints later is the expensive path.

### How it works

**Tracking numbers.** Every request gets a unique ID. Every log line written
while handling it carries the same ID, and it comes back in the response header:

```bash
curl -i http://127.0.0.1:8000/health | grep -i x-request-id
# x-request-id: c20117794809407180e8f833dcb8fee4
```

Supply your own to join an existing trace across several systems:

```bash
curl -H "X-Request-ID: my-trace-1" http://127.0.0.1:8000/
```

It is stored in a `ContextVar` — a variable scoped to the current task, so
concurrent requests never see each other's. No function has to pass it down.

**Caller input is not trusted, even here.** An inbound ID is accepted only if
it is short and uses safe characters. A newline in it would let a caller forge
extra lines in our logs — a real attack called log injection.

**One error shape.** Every failure looks identical:

```json
{"error": {"code": "not_found", "message": "No ticket with that id.", "requestId": "a1b2..."}}
```

`code` is for software to branch on, `message` for humans, `requestId` to quote
when reporting it. Stack traces and database errors never cross the boundary —
they tell an attacker your versions and file paths.

**Passwords are blanked automatically.** A connection URL logged by accident
comes out as:

```
postgresql://support:***redacted***@db:5432/support
```

**Two different health questions.**

| Endpoint | Question | Checks dependencies? |
|---|---|---|
| `/health` | Is this process alive? | **No** |
| `/ready` | Can it do useful work? | Yes — Postgres and Redis |

Keeping them separate prevents a self-inflicted outage: if they were one
question, a 30-second database hiccup would make the orchestrator kill every
healthy copy of the app at once.

Verified by actually stopping Redis:

```bash
docker compose stop redis
curl -s http://127.0.0.1:8000/ready   # 503, redis unreachable, postgres healthy
curl -s http://127.0.0.1:8000/health  # 200 — still alive, no restart loop
docker compose start redis            # back to 200 unaided
```

### Bugs found, and what they teach

**1. Crashes came back with no tracking number.**

Tests passed. Then the real server was called over HTTP, and unexpected
crashes returned **without** the ID — the exact case where you need it.

The web framework has its own outermost safety net that catches crashes and
writes the response itself, bypassing our middleware. Our ID was applied one
layer too deep.

**The lesson:** the simulated test client is not the real server. Every bug
found in this project came from running the real thing.

**2. The health check cried wolf on Windows.**

`/ready` reported "database unreachable" when the database was fine — an
incompatibility between the driver and Windows' default event loop.

A false alarm is indistinguishable from a real outage. Worse, if alarms are
wrong often enough people stop believing them, and then one fails to fire on
the day it matters.

---

## 2026-10-16 — KAN-13 · Repository scaffold

### What changed

The foundation: Docker stack, pinned dependencies, validated configuration, one
quality command, ten pre-commit hooks.

### Why

Setup friction is paid by every person who touches the project, every time.

### How it works

**Start everything:**

```bash
cp .env.example .env     # Windows: copy .env.example .env
docker compose up -d     # Postgres (port 5433) + Redis
python -m venv .venv
.venv\Scripts\activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
python scripts/check.py  # lint, format, types, tests — all in one
```

**Why Postgres is on 5433.** A native Postgres install commonly holds 5432. It
then intercepts our connections and rejects credentials it has never heard of,
which looks exactly like a wrong password. Moving to 5433 sidesteps it. Inside
Docker the port is still 5432; only the host-facing one moved.

**Configuration fails fast.** Missing a required variable stops startup
immediately and names it:

```
Configuration is invalid. Fix these environment variables:

  DATABASE_URL: is required but was not set
  REDIS_URL: is required but was not set
```

The alternative is a service that starts happily and dies at 3am on the first
real request.

**The secret scanner already paid for itself.** One of the pre-commit hooks
scans for passwords and API keys. It caught a test credential during this very
card. Credentials committed to git live in the history permanently — the real
cost is rotating everything and auditing what was accessed.

### Bug found, and what it teaches

`app/main.py` created the application at the moment the file was imported,
which meant importing it required full configuration. Test collection crashed
instantly.

Fixed by converting to a **factory** — a function that builds the app when
called, rather than at import:

```python
# before: app = create_app()        <- runs on import, needs config
# after:  def create_app(settings=None) -> FastAPI: ...
```

**The lesson:** the fix was the design, not the test. It would have been
quicker to set environment variables in the test and move on — and the module
would still have been unimportable without config, forever.

### What is incomplete

Docker was not running during this card, so the compose stack was unverified
until the KAN-15 session — which is exactly how the port 5432 clash went
unnoticed for two cards.

# ADR-005 — Database driver and event loop

**Status:** Accepted · **Date:** 2026-10-17 · **Owner:** Tech Lead / Architect

## Context

Discovered while building the readiness probe (KAN-14). `psycopg`'s async mode
raises on startup under asyncio's `ProactorEventLoop`:

```
psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in
async mode.
```

`ProactorEventLoop` is the **default on Windows**. Production runs in Linux
containers, where the default is `SelectorEventLoop` and the problem does not
exist. So this is strictly a local-development problem — but a bad one: the
readiness probe reported "database unreachable" while the database was
perfectly healthy, which is indistinguishable from a real outage.

KAN-14 worked around it for the probe by running the synchronous driver on a
worker thread. That is fine for one query every few seconds. It is not a
strategy for real data access, which arrives with KAN-15.

## Options considered

### A. Run the synchronous driver on worker threads throughout

- Works identically on every platform, today.
- Simple, no event-loop configuration.
- **Gives up async database access entirely.** Every query occupies a thread
  for its duration; concurrency becomes bounded by the thread pool rather than
  by the database. For a service whose whole job is waiting on I/O — model
  calls, vendor APIs, queries — that is the wrong shape.

### B. Async everywhere, and accept that local Windows development diverges

Use async `psycopg` and let Windows developers run the application inside the
Docker container rather than on the host.

- Production code path is the only code path.
- **Developer experience gets noticeably worse**: no host-side debugger, slower
  edit-reload cycle. The one-command environment from KAN-13 partly exists to
  avoid exactly this friction.
- Tests that touch the database would need the container too, or would silently
  exercise a different path than production.

### C. Switch to `asyncpg`

- Async-native and fast, with good SQLAlchemy support.
- Avoids the Proactor restriction.
- A different driver with different type adaptation, different error classes
  and no DBAPI compatibility — so `pgvector` integration, migrations and any
  raw SQL all need checking against it.
- Swapping the driver to dodge a local-development inconvenience is a large
  change for a small reason.

### D. Set `WindowsSelectorEventLoopPolicy` at the application entry point

Three lines, applied only on Windows, before the event loop is created.

- One driver, one code path, async throughout.
- Zero effect on production, where the policy is already Selector.
- **`SelectorEventLoop` does not support asyncio subprocesses on Windows.** If
  we ever need `asyncio.create_subprocess_*`, it breaks — on Windows only.

## Decision

**Option D: async `psycopg` throughout, with `WindowsSelectorEventLoopPolicy`
set at the application entry point when running on Windows.**

The subprocess limitation is acceptable because this service does not spawn
subprocesses and has no reason to: external work goes out over HTTP or through
the Redis queue. Should that change, the constraint is documented here and the
fallback is option C.

The readiness probe's existing sync-on-thread implementation stays as-is. It
is deliberately independent of the main data-access path, so a probe keeps
working even if the application's own connection handling is misconfigured —
which is precisely when you want a probe to be trustworthy.

## Consequences

**What this buys**

- A single async data-access path, identical on a developer laptop and in
  production.
- Host-side development and debugging continue to work on Windows.
- `psycopg` stays, so `pgvector` adaptation, SQLAlchemy integration and
  migrations all remain on well-trodden ground.

**What it costs**

- **A platform-specific branch in the entry point.** Small, but it is the kind
  of code that gets deleted by someone tidying up and then silently breaks
  Windows development again. It carries a comment pointing here.
- No asyncio subprocesses on Windows. Currently unused; a real constraint if
  that changes.
- The policy must be set before the loop is created, so **every process entry
  point must apply it**. This prediction was confirmed immediately: KAN-17's
  integration tests failed with the original Proactor error because pytest
  creates its own loop and nothing called the helper. There are now three entry
  points applying it — `app/__main__.py`, the `seed` CLI command, and
  `tests/conftest.py` — and a fourth will be needed for the Celery worker in
  E12. A bare `uvicorn app.main:create_app` still reproduces the error.
- **This has a deadline.** Python 3.14 deprecates event loop policies and 3.16
  removes them. When that lands, the choices narrow to option C (asyncpg) or
  option B (run only inside the Linux container). Worth revisiting before it
  becomes forced rather than chosen.
- Two mechanisms now touch the database: async for application queries, sync
  on a thread for the probe. Slightly more surface, justified by probe
  independence.

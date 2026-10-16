# Seams — where the remaining epics plug in

The vertical slice (KAN-17) proves one ticket can travel from HTTP request to
persisted reply. Everything still to be built replaces a piece of that path
rather than bolting onto the side of it.

This document exists so that starting any later epic begins with "which seam
does this attach to?" instead of a reading of the whole codebase.

## The path today

```
POST /v1/tickets
      │
      ▼
app/api/routes/tickets.py ......... validates, maps result to a status code
      │
      ▼
app/api/deps.py:get_session ....... opens ONE transaction for the request
      │
      ▼
app/services/intake.py ............ orchestrates; owns state transitions
      │   │
      │   ├──> app/repositories/tickets.py .... all SQL lives here
      │   │
      │   └──> app/services/resolution.py ..... THE SEAM (Resolver protocol)
      │              └── PlaceholderResolver ... canned reply, to be replaced
      ▼
reply persisted, ticket terminal, transaction commits
```

## The seams, by epic

| Epic | What it adds | Where it attaches | What it must not do |
|---|---|---|---|
| **E2** Retrieval | Knowledge-base search | New `app/services/retrieval.py`, called *by* a resolver | Must not be called from the route or the repository |
| **E4** Routing | Intent + urgency classification | A step inside `IntakeService.submit`, between `CLASSIFYING` and `RESOLVING` — the transition already exists for it | Must not bypass the state transitions |
| **E5** Orchestration | LangGraph workflow | **Replaces `PlaceholderResolver`.** A new `WorkflowResolver` implementing the same `Resolver` protocol, swapped at one line in `create_app` | Must not import anything from `app.api` |
| **E6** Tools / MCP | Order lookup, CRM, refunds | New `app/clients/` modules, invoked by the action path inside the workflow | Must never be called directly by a resolver without going through E7 |
| **E7** Guardrails | Deterministic policy engine | Between a resolver returning a proposed action and that action executing | **Must be unbypassable.** No path from model output to a tool call may skip it (ADR-002) |
| **E8** Approval | Human-in-the-loop interrupt | A resolver returns `AWAITING_APPROVAL` instead of a reply; the transition already exists | Must not hold the request open waiting for a human |
| **E9** Multi-tenancy | RLS, auth, RBAC | Replaces the `X-Tenant-Slug` header in `routes/tickets.py` with an authenticated identity; adds RLS to every table | Must not leave the header path available |
| **E10** Dashboard | Next.js UI | Consumes the API; no Python changes | Must not reach into the database directly |
| **E11** Observability | Tracing, cost, memory | Spans around existing nodes; cost fields already exist on `ResolutionDraft` and `resolution` | Must not break the request path when tracing fails |

## Three contracts worth not breaking

**1. A resolver decides; it does not write.**

`Resolver.resolve()` returns a `ResolutionDraft` and persists nothing. This is
what makes the E8 approval interrupt possible at all — you cannot pause between
deciding and writing if deciding writes.

**2. One transaction per request.**

`get_session` opens it, commits on success, rolls back on any exception. This is
what makes "a failure anywhere leaves no partial ticket" true rather than
aspirational, and it is covered by a test that injects a failure mid-flow and
asserts zero rows.

When E5 makes resolution long-running, this contract has to change: a
transaction must not stay open across model calls. The expected shape is a short
transaction to accept the ticket, a queued job for resolution, and a further
short transaction to record the outcome.

**3. State transitions go through `intake.transition`.**

Postgres enforces which states exist; `TICKET_TRANSITIONS` enforces the order.
Setting `ticket.status` directly bypasses the second and will eventually produce
a ticket that moved from resolved back to resolving.

## Measured baseline

Recorded on the development machine, 25 requests, full path including two
database round trips:

| | |
|---|---|
| median | 25.0 ms |
| p95 | 26.8 ms |
| max | 32.1 ms |

This is the **floor**. Classification, retrieval and generation all add to it.
The ADR target for end-to-end resolution is a p95 of 8 s, so there is roughly
300× headroom — which is the point of recording the number now, while it is
still all infrastructure and no intelligence.

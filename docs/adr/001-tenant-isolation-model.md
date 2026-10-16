# ADR-001 — Tenant isolation model

**Status:** Accepted · **Date:** 2026-10-17 · **Owner:** Tech Lead / Architect

## Context

The platform serves multiple customer companies from one running system. Each
tenant's tickets, customers, knowledge base and configuration must be
completely invisible to every other tenant.

This is the most consequential decision in the project. Every multi-tenant data
leak in the wild has the same root cause: one query that forgot to filter. The
question is not whether application code will eventually contain such a bug —
it is whether that bug can cause a leak when it happens.

The decision has to be made now because it determines the shape of every table
and every query written from here on.

## Options considered

### A. Application-level filtering only

Every query includes `WHERE tenant_id = :current_tenant`, enforced by
convention, code review and a shared repository layer.

- Simplest to build; no database features required.
- Works identically on any database.
- **One missed `WHERE` clause is a cross-tenant leak.** The failure is silent:
  the query returns more rows rather than erroring. Nothing alerts.
- Protection degrades as the team and the query count grow — exactly when the
  risk is highest.

### B. Row-Level Security in Postgres, over a shared schema

Every tenant-scoped table carries `tenant_id` and an RLS policy. A session
variable carries the current tenant; the database refuses rows outside it.

- A forgotten filter in application code returns **nothing**, not another
  tenant's data. The failure mode flips from silent leak to visible bug.
- Enforcement cannot be bypassed by a new endpoint, an ad-hoc script, or a
  migration run by hand at 2am.
- Requires correct handling of the session variable with connection pooling —
  a pooled connection carrying a stale tenant context is itself a leak.
- Adds a measurable cost to every query, which has to be checked on hot paths.

### C. Schema or database per tenant

Each tenant gets its own Postgres schema, or its own database.

- The strongest isolation available short of separate infrastructure.
- Makes per-tenant backup, restore and deletion trivial.
- **Migrations must run across every tenant**, and a partial failure leaves
  tenants on different schema versions — an operational problem that grows
  linearly with customers.
- Connection pooling becomes significantly harder.
- Cross-tenant analytics (resolution rate across the fleet) becomes a
  multi-database join.

## Decision

**Option B: shared schema with `tenant_id` on every tenant-scoped table,
enforced by Postgres Row-Level Security.**

Additionally, and decided now rather than later: `tenant_id` is present on every
such table from the **first migration**, even though RLS enforcement itself
lands later (E9, KAN-48). Threading the column is nearly free today; adding it
across an existing codebase means revisiting every query that was written
without it.

## Consequences

**What this buys**

- A forgotten filter cannot leak data. The database is the backstop, and the
  application filter becomes an optimisation rather than the security boundary.
- One migration path, one connection pool, straightforward fleet-wide
  analytics.
- The isolation claim is testable: the acceptance test for KAN-48 deliberately
  removes the application filter and asserts the query still returns only the
  current tenant's rows.

**What it costs**

- **Connection pooling is now a security concern, not just a performance one.**
  The tenant session variable must be set on checkout and cleared on return. A
  bug here leaks across tenants. This needs an explicit test, not just care.
- RLS adds per-query overhead. Hot-path queries need `EXPLAIN ANALYZE` review
  before and after enabling it.
- Per-tenant data deletion is a `DELETE` across many tables rather than
  dropping a schema, so it needs deliberate implementation and testing to
  satisfy a deletion request.
- A shared schema means a catastrophic bug in a migration affects every tenant
  at once. Migrations must be backward compatible and rehearsed.

**Revisit this if** a single tenant's data volume starts dominating the shared
tables, or a customer contractually requires physical separation. Moving to
option C later is possible but expensive; the `tenant_id` column makes it
*possible* rather than a rewrite.

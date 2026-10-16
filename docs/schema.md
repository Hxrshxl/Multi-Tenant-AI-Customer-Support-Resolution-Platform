# Data model

Seven tables. Every design choice here follows [ADR-001](adr/001-tenant-isolation-model.md)
(isolation) and [ADR-003](adr/003-workflow-durability-and-idempotency.md)
(idempotency).

## Entities and relationships

```
tenant  (1) ──< (N) customer
   │                   │
   │ (1)               │ (1)
   │                   │
   └──< (N) ticket >───┘        ticket.customer_id
              │
              ├──< (N) message          a thread, ordered by created_at
              ├──< (0..1) resolution    at most one outcome per ticket
              ├──< (N) action           proposed side effects
              └──< (N) audit_entry      append-only record (ticket_id nullable)
```

| From | To | Cardinality | On delete | Why |
|---|---|---|---|---|
| customer | tenant | N:1 | `CASCADE` | A tenant's departure takes its customers with it. |
| ticket | tenant | N:1 | `CASCADE` | Same. |
| ticket | customer | N:1 | `CASCADE` | A ticket without a customer is meaningless. |
| message | ticket | N:1 | `CASCADE` | A thread does not outlive its ticket. |
| resolution | ticket | 1:1 | `CASCADE` | Unique on `ticket_id`. |
| action | ticket | N:1 | `CASCADE` | |
| audit_entry | ticket | N:0..1 | `SET NULL` | **Deliberately different.** The record of what happened must outlive the thing it happened to. |

## Integrity rules enforced by the database

These are not conventions. Each one has been verified to reject the illegal
case against a live Postgres.

| Rule | Mechanism |
|---|---|
| A terminal ticket has a completion timestamp, and a non-terminal one does not | `ck_ticket_terminal_status_requires_resolved_at` |
| Urgency, when set, is 1–5 | `ck_ticket_urgency_in_range` |
| The same inbound message cannot create two tickets | `uq_ticket_tenant_id_external_ref` |
| Only defined ticket states exist | Postgres enum `ticket_status` |
| An escalation states a reason; a resolution does not invent one | `ck_resolution_escalation_requires_reason` |
| Money and currency are present together or not at all | `ck_action_amount_and_currency_together` |
| An amount, when present, is positive | `ck_action_amount_positive` |
| An executed action has an execution timestamp | `ck_action_executed_requires_timestamp` |
| **The same effect cannot execute twice** | `uq_action_tenant_id_idempotency_key` |

That last one is the database-level half of ADR-003. Even if the application's
replay logic is wrong, a second attempt at the same logical refund fails on
insert rather than reaching the payment provider.

### What the database does *not* enforce

The **order** of ticket state changes. Postgres constrains which states exist;
it does not know that `resolved` may not go back to `resolving`. That is held
in `TICKET_TRANSITIONS` in `app/db/models.py`, enforced by the service layer,
and covered by tests asserting terminal states have no outgoing edges.

Enforcing ordering in the database would need a trigger. That is a reasonable
future change if transitions ever happen outside the service layer; today they
do not.

## Indexes

Every index exists for a named query. None is speculative.

| Index | Serves |
|---|---|
| `uq_tenant_slug` | Tenant lookup by slug on every request |
| `uq_customer_tenant_id_external_id` | Resolving a tenant's own customer identifier |
| `ix_customer_tenant_id_email` | Finding a customer by email during intake |
| `uq_ticket_tenant_id_external_ref` | Idempotent intake |
| `ix_ticket_tenant_id_status_created_at` | The work queue and the dashboard: a tenant's tickets by state, newest first |
| `ix_action_tenant_id_status` | Pending-approval queue |
| `uq_action_tenant_id_idempotency_key` | Idempotency enforcement |
| `ix_message_tenant_id_ticket_id_created_at` | Loading a thread in order |
| `ix_resolution_tenant_id` | Cascade on tenant delete (no composite index leads with `tenant_id` here) |
| `ix_audit_entry_tenant_id_created_at` | Audit queries by time range |
| `ix_audit_entry_tenant_id_ticket_id` | Reconstructing one ticket's history |

**Note on a removed index.** The first draft put `index=True` on every
`tenant_id`. Autogenerate revealed those duplicated the composite indexes that
already lead with `tenant_id` — Postgres uses the composite for a
`tenant_id`-only lookup. Six redundant indexes were removed; each would have
taxed every write for no read benefit. `resolution` keeps its single-column
index because it has no composite.

## PII inventory

Feeds the retention, encryption and deletion work in E9 (KAN-41). Any new
column holding personal data belongs in this table in the same change.

| Table | Column | Contains |
|---|---|---|
| `customer` | `email` | Email address |
| `customer` | `display_name` | Personal name |
| `ticket` | `subject` | Free text, routinely contains names and order details |
| `message` | `body` | Free text, the highest-risk column here — customers paste anything |
| `resolution` | `reply_body` | Free text sent to the customer |

`audit_entry.payload` and `action.arguments` are JSONB and could hold PII
depending on what is written to them. The redaction in `app/core/logging.py`
covers logs; writing PII into these columns is a review concern.

## Migration safety

The first migration creates seven tables on an empty database. Every statement
is a `CREATE`, so the only locks taken are on objects that do not yet exist and
no existing table is blocked — safe to run against a live system.

It round-trips: `upgrade` → `downgrade` → `upgrade` all succeed. That needed an
explicit fix. Alembic's autogenerate drops tables on downgrade but leaves
Postgres enum types behind, so the second upgrade failed with
`type "channel" already exists`. The downgrade now drops the eight enum types
explicitly. This was found by actually running the cycle, not by inspection.

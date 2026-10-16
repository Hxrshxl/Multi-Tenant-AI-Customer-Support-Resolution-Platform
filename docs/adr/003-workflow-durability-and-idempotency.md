# ADR-003 — Workflow durability and the idempotency contract

**Status:** Accepted · **Date:** 2026-10-17 · **Owner:** Tech Lead / Architect

## Context

Resolving a ticket takes several model calls and external API calls, so it runs
for tens of seconds. In that window a worker can be killed by a deploy, an
out-of-memory event, or a node failure.

Two questions follow, and the second is far harder than the first:

1. How does a half-finished ticket continue?
2. How does continuing it avoid repeating a side effect that already happened —
   specifically, a refund?

A checkpoint written *before* a refund means resumption re-attempts it. A
checkpoint written *after* means a crash in between loses all record of a
refund that did occur. Neither is safe on its own.

## Options considered

### Control flow: free-roaming agent vs. explicit workflow

**A free agent** given tools and a goal, deciding its own next step each turn.

- Flexible; handles cases nobody enumerated.
- Non-deterministic control flow: the same ticket can take different paths on
  different runs, which makes behaviour hard to test, hard to explain to a
  customer, and hard to bound in cost.
- Resumption is ill-defined — there is no "step 3" to resume from.

**An explicit workflow** (LangGraph) with typed state and conditional edges.

- Deterministic routing. The same ticket takes the same path.
- Every state is nameable, so a stalled ticket can be diagnosed from its state
  alone.
- Resumption is well defined: continue from the last recorded node.
- Cannot handle a case the graph does not model; those must escalate.

### Durability: in-memory vs. Postgres checkpointer

In-memory is free and loses everything on restart. A Postgres checkpointer
persists every node transition, costs a write per node, and grows a table that
needs a retention policy.

## Decision

**An explicit LangGraph workflow with a Postgres checkpointer, plus a separate
idempotency contract for side effects.**

The checkpointer alone is not sufficient, and treating it as sufficient is the
mistake most implementations make. The contract every side-effecting node must
follow:

1. **Declare an idempotency key** derived from workflow identity plus step
   identity — stable across retries and resumptions of the same logical step.
2. **Record the attempt before performing it**, and record the outcome after.
3. **On resume, check whether the effect already completed** and skip rather
   than repeat.
4. **Reconcile, never guess, when the outcome is unknown.** "Attempted, result
   unrecorded" is its own state. It is resolved by querying the downstream
   system, not by assuming either way.
5. **Surface indeterminate cases to a human** rather than resolving them
   silently.

Escalation on exhausted retries is mandatory. A ticket may never end in silent
failure — the customer is waiting either way.

## Consequences

**What this buys**

- A deploy mid-resolution loses no work.
- "Refunded exactly once" becomes testable: crash injected immediately before,
  during and immediately after the refund must all yield exactly one refund
  (KAN-32).
- A stalled ticket is diagnosable from its persisted state.
- Deterministic routing means cost per ticket is boundable and behaviour is
  explicable to a customer.

**What it costs**

- **Every future node author must know this contract.** It is not enforced by
  the type system. Mitigated by documenting it on the node base class and
  auditing side-effecting nodes in review, but it remains a discipline problem,
  which is the weakest kind of guarantee.
- A database write per node transition, on the latency budget.
- The checkpoint table grows with every ticket and needs a retention policy
  before it becomes the largest table in the system.
- A state schema change risks corrupting in-flight workflows, so state is
  versioned and migration of in-flight work needs a plan.
- The graph cannot handle unmodelled cases. Some tickets a free agent might
  have muddled through will escalate instead. We accept that: a predictable
  escalation is better than an unpredictable action.

**Revisit this if** the graph starts accumulating edges faster than features,
which would indicate the problem is genuinely more open-ended than a workflow
suits.

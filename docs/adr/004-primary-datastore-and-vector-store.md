# ADR-004 — Primary datastore and vector store

**Status:** Accepted · **Date:** 2026-10-17 · **Owner:** Tech Lead / Architect

## Context

The system needs relational storage for tenants, customers, tickets, actions
and audit records, and vector storage for semantic search over each tenant's
knowledge base.

These can be the same system or two systems. The choice affects operational
burden, transactional guarantees, and how tenant isolation is enforced for
retrieval.

## Options considered

### A. Postgres with pgvector for both

- **One system to run, back up, monitor and secure.** For a small team this is
  the dominant consideration.
- Tenant isolation for retrieval comes free from the same RLS policies as
  everything else (ADR-001). With a separate vector store, isolation must be
  implemented and tested *twice*, in two different systems.
- A document and its embedding can be written in one transaction, so there is
  no window where a chunk exists without its vector.
- Lower raw vector performance ceiling than a purpose-built store.
- Index build times and memory use become a real concern at tens of millions
  of vectors.

### B. Postgres plus a dedicated vector database (Qdrant, Weaviate, Pinecone)

- Better vector performance at scale, richer filtering and hybrid features.
- **A second system to operate**, with its own backup story, failure modes,
  access control and client library.
- Isolation must be re-implemented in the second system. Two implementations of
  the same security property is two chances to get it wrong.
- No cross-system transaction: a chunk can be written to Postgres and fail to
  land in the vector store, leaving silent gaps in retrieval.
- A managed option removes operational burden but adds per-tenant data
  residency questions and recurring cost.

### C. Postgres plus an in-process index (FAISS) rebuilt on deploy

- Fast and dependency-free.
- Rebuild time grows with corpus; no incremental updates.
- Does not survive horizontal scaling without a shared store. Effectively a
  single-node design.

## Decision

**Option A: PostgreSQL with the `pgvector` extension for both relational and
vector storage. Redis for queueing, caching and rate limiting.**

The deciding argument is not performance — it is that **isolation is the
hardest property in this system to get right, and this option requires
implementing it once instead of twice.**

Expected scale (see the targets in the ADR index) is 5,000 tickets/day with
knowledge bases in the low tens of thousands of chunks per tenant. That is well
inside pgvector's comfortable range. Choosing a dedicated vector database for
this volume would be solving a problem we do not have, at the cost of a problem
we would then have.

## Consequences

**What this buys**

- One datastore to back up, restore, monitor and secure.
- Retrieval isolation inherits from ADR-001 with no additional mechanism.
- Chunks and embeddings are written atomically.
- `JOIN` between vectors and relational data, which makes metadata filtering
  (tenant, document, recency) ordinary SQL rather than a two-system dance.

**What it costs**

- **A performance ceiling we will eventually meet** if a tenant's corpus grows
  by orders of magnitude. The migration path then is real work, not a config
  change.
- Vector index choice and tuning (HNSW vs IVFFlat, and their parameters)
  becomes our problem rather than a vendor's. KAN-20 covers measuring the
  recall/latency curve rather than guessing.
- Heavy vector queries and transactional writes share one database's resources.
  Under load they contend, and the mitigation is read replicas, which is itself
  added complexity.
- Index rebuilds after re-embedding are expensive and need to happen without
  taking retrieval down.

**Revisit this if** measured recall at the required latency falls below target
at realistic corpus size, or if vector workload starts degrading transactional
performance. The retrieval layer is deliberately written behind an interface
so the store can be swapped without rewriting the agent.

-- Runs once, on first initialisation of an empty data directory.
-- The pgvector/pgvector image ships the extension binaries; this enables the
-- extension inside the application database so retrieval (E2) can use it.

CREATE EXTENSION IF NOT EXISTS vector;

-- Deterministic UUID generation for primary keys (KAN-15).
CREATE EXTENSION IF NOT EXISTS pgcrypto;

"""PostgreSQL connectivity checks.

These use the *synchronous* driver on a worker thread rather than
``psycopg.AsyncConnection``. psycopg's async mode refuses to run on asyncio's
``ProactorEventLoop``, which is the default on Windows, so the async path
reports a healthy database as unreachable on every Windows development
machine — a false negative that looks exactly like a real outage.

The cost is one thread per probe, which is irrelevant for a readiness check.
When real async data access arrives with the data model (KAN-15), that will
need either a Linux-only async path or an explicit SelectorEventLoop policy.
"""

from __future__ import annotations

import asyncio
import logging

import psycopg

logger = logging.getLogger(__name__)

#: A readiness probe must answer quickly or it is useless to an orchestrator.
DEFAULT_TIMEOUT_SECONDS = 2.0

#: Backstop for the await itself. asyncio cannot cancel the worker thread, so
#: the driver's own connect_timeout is the real bound; this just stops the
#: coroutine hanging if the driver ignores it.
_AWAIT_GRACE_SECONDS = 1.0


def _connect_and_query_sync(dsn: str, timeout: float) -> None:
    with psycopg.connect(dsn, connect_timeout=max(1, int(timeout))) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")


def _vector_extension_sync(dsn: str, timeout: float) -> bool:
    with psycopg.connect(dsn, connect_timeout=max(1, int(timeout))) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            return cur.fetchone() is not None


async def ping(dsn: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
    """Open a connection and run a trivial query.

    Raises:
        Exception: any driver or timeout error, for the caller to classify.
    """
    await asyncio.wait_for(
        asyncio.to_thread(_connect_and_query_sync, dsn, timeout),
        timeout=timeout + _AWAIT_GRACE_SECONDS,
    )


async def has_vector_extension(dsn: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> bool:
    """Return whether the ``vector`` extension is enabled on this database."""
    return await asyncio.wait_for(
        asyncio.to_thread(_vector_extension_sync, dsn, timeout),
        timeout=timeout + _AWAIT_GRACE_SECONDS,
    )

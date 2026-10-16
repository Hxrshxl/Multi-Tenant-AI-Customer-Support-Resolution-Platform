"""Redis connectivity checks."""

from __future__ import annotations

import asyncio
import logging

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 2.0


async def ping(url: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
    """Connect and issue PING.

    Socket timeouts are set explicitly so a refused or black-holed connection
    fails fast and is reported as unreachable, rather than sitting until the
    outer timeout fires and being misreported as slow.

    Raises:
        Exception: any driver or timeout error, for the caller to classify.
    """

    async def _ping() -> None:
        client: Redis = Redis.from_url(
            url,
            socket_connect_timeout=timeout,
            socket_timeout=timeout,
            retry_on_timeout=False,
        )
        try:
            await client.ping()
        finally:
            await client.aclose()

    await asyncio.wait_for(_ping(), timeout=timeout + 1.0)

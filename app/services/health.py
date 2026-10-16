"""Liveness and readiness logic.

Liveness answers "is this process alive". Readiness answers "can it actually
serve traffic", which means asking its dependencies. Conflating the two gets
healthy containers killed during a brief database blip, so they stay separate.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.clients import postgres, redis
from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DependencyStatus:
    """Outcome of one dependency check.

    ``detail`` is deliberately coarse. Driver errors routinely contain the
    connection string, so the specific error is logged and only a safe
    summary is returned.
    """

    name: str
    healthy: bool
    detail: str | None = None


@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    dependencies: tuple[DependencyStatus, ...]


class HealthService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def readiness(self) -> ReadinessReport:
        """Check every dependency concurrently and summarise."""
        statuses = await asyncio.gather(
            self._check("postgres", lambda: postgres.ping(str(self._settings.database_url))),
            self._check("redis", lambda: redis.ping(str(self._settings.redis_url))),
        )
        return ReadinessReport(
            ready=all(status.healthy for status in statuses),
            dependencies=tuple(statuses),
        )

    @staticmethod
    async def _check(name: str, probe: Callable[[], Awaitable[None]]) -> DependencyStatus:
        try:
            await probe()
        except TimeoutError:
            logger.warning("dependency check timed out", extra={"dependency": name})
            return DependencyStatus(name=name, healthy=False, detail="timed out")
        except Exception:
            # Full detail server-side; the caller gets a safe summary.
            logger.warning("dependency check failed", exc_info=True, extra={"dependency": name})
            return DependencyStatus(name=name, healthy=False, detail="unreachable")
        return DependencyStatus(name=name, healthy=True)

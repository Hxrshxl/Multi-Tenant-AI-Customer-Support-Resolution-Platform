"""Database engine and session management."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings

#: The configured DSN uses the plain ``postgresql://`` scheme, because that is
#: what psql, Alembic and every operator tool expects. SQLAlchemy needs the
#: driver named explicitly for async, so the translation happens here, once,
#: rather than being duplicated into every environment file.
_ASYNC_SCHEME = "postgresql+psycopg://"


def async_dsn(settings: Settings) -> str:
    dsn = str(settings.database_url)
    if dsn.startswith("postgresql+"):
        return dsn
    return dsn.replace("postgresql://", _ASYNC_SCHEME, 1)


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        async_dsn(settings),
        # Verifies a pooled connection is alive before handing it out. Costs a
        # round trip; saves the first query after an idle period failing.
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        echo=False,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """One unit of work: commit on success, roll back on any failure."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

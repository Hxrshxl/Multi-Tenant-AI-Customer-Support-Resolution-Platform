"""Developer command line.

    python -m app.cli --help

``check``  verifies the local stack is reachable.
``seed``   loads sample tenants, customers and tickets.
"""

from __future__ import annotations

import asyncio
import sys

import psycopg
import redis
import typer

from app.config import ConfigurationError, Settings, get_settings
from app.core.runtime import configure_event_loop_policy
from app.db.seed import seed as seed_data
from app.db.session import create_engine, create_session_factory, session_scope

cli = typer.Typer(add_completion=False, help="Developer tasks for the support platform.")


def _settings_or_exit() -> Settings:
    try:
        return get_settings()
    except ConfigurationError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@cli.command()
def check() -> None:
    """Verify that Postgres and Redis are reachable with the current settings."""
    settings = _settings_or_exit()
    failures: list[str] = []

    try:
        with psycopg.connect(str(settings.database_url), connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
                has_vector = cur.fetchone() is not None
        typer.echo("  postgres: reachable")
        if has_vector:
            typer.echo("  pgvector: enabled")
        else:
            failures.append("pgvector extension is not enabled on this database")
    except Exception as exc:  # report any connectivity failure, do not crash
        failures.append(f"postgres: {exc}")

    try:
        client = redis.Redis.from_url(str(settings.redis_url), socket_connect_timeout=5)
        client.ping()
        typer.echo("  redis: reachable")
    except Exception as exc:  # report any connectivity failure, do not crash
        failures.append(f"redis: {exc}")

    if failures:
        typer.echo("", err=True)
        for failure in failures:
            typer.echo(f"  FAILED  {failure}", err=True)
        typer.echo("\nIs the stack running?  docker compose up -d", err=True)
        raise typer.Exit(code=1)

    typer.echo("\nAll dependencies reachable.")


@cli.command()
def seed(
    tickets: int = typer.Option(50, help="Tickets to create per tenant."),
    customers: int = typer.Option(8, help="Customers to create per tenant."),
) -> None:
    """Load sample tenants, customers and tickets.

    Seeds two tenants deliberately: a single tenant hides isolation bugs,
    because a query missing its tenant filter still looks correct.

    Safe to re-run; existing data is left alone rather than duplicated.
    """
    settings = _settings_or_exit()
    configure_event_loop_policy()

    async def _run() -> dict[str, int]:
        engine = create_engine(settings)
        factory = create_session_factory(engine)
        try:
            async with session_scope(factory) as session:
                return await seed_data(
                    session, tickets_per_tenant=tickets, customers_per_tenant=customers
                )
        finally:
            await engine.dispose()

    try:
        created = asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"\nSeeding failed: {exc}", err=True)
        typer.echo("Has the migration been applied?  alembic upgrade head", err=True)
        raise typer.Exit(code=1) from exc

    if not any(created.values()):
        typer.echo("Nothing to do: sample data is already present.")
        return

    typer.echo("Seeded:")
    for entity, count in created.items():
        typer.echo(f"  {entity}: {count}")


def main() -> None:
    try:
        cli()
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

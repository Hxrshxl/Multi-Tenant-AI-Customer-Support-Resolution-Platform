"""Developer command line.

``check``  verifies the local stack is reachable.
``seed``   loads sample tenants, customers and tickets.

Run with:  python -m app.cli --help
"""

from __future__ import annotations

import sys

import psycopg
import redis
import typer

from app.config import ConfigurationError, get_settings

cli = typer.Typer(add_completion=False, help="Developer tasks for the support platform.")


@cli.command()
def check() -> None:
    """Verify that Postgres and Redis are reachable with the current settings."""
    try:
        settings = get_settings()
    except ConfigurationError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

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
def seed() -> None:
    """Load sample tenants, customers and tickets into the database.

    The data model lands with KAN-15, so there are no tables to populate yet.
    This command verifies connectivity and reports that, rather than failing or
    pretending to have seeded something.
    """
    check()
    typer.echo(
        "\nNothing seeded: the schema arrives with KAN-15 (core data model).\n"
        "This command will populate two tenants, sample customers and tickets\n"
        "across all four intent classes once those tables exist."
    )


def main() -> None:
    try:
        cli()
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

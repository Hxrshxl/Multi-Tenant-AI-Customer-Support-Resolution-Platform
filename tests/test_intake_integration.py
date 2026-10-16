"""The vertical slice, end to end, against a real database.

Skipped automatically when Postgres is not reachable, so the suite still runs
on a machine with no stack up. When it does run it uses a throwaway tenant with
a random slug and deletes it afterwards, so it never disturbs seeded data.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.correlation import HEADER_NAME
from app.main import create_app
from app.services.intake import IntakeService
from app.services.resolution import PlaceholderResolver, ResolutionDraft


def _settings_from_environment() -> Settings | None:
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception:
        return None


def _database_reachable(settings: Settings | None) -> bool:
    if settings is None:
        return False
    try:
        with psycopg.connect(str(settings.database_url), connect_timeout=3):
            return True
    except Exception:
        return False


SETTINGS = _settings_from_environment()
pytestmark = pytest.mark.skipif(
    not _database_reachable(SETTINGS),
    reason="Postgres not reachable; run `docker compose up -d` to include these tests",
)


@pytest.fixture
def tenant_slug() -> Iterator[str]:
    """A throwaway tenant, removed afterwards by cascade."""
    assert SETTINGS is not None
    slug = f"itest-{uuid.uuid4().hex[:10]}"
    dsn = str(SETTINGS.database_url)
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenant (id, slug, name, is_active, created_at, updated_at)"
                " VALUES (gen_random_uuid(), %s, %s, true, now(), now())",
                (slug, f"Integration Test {slug}"),
            )
        conn.commit()
    yield slug
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tenant WHERE slug = %s", (slug,))
        conn.commit()


@pytest.fixture
def client() -> Iterator[TestClient]:
    assert SETTINGS is not None
    with TestClient(create_app(SETTINGS)) as test_client:
        yield test_client


def _payload(ref: str) -> dict[str, object]:
    return {
        "external_ref": ref,
        "channel": "email",
        "subject": "Export keeps failing with error E_4210",
        "body": "Every export since Tuesday has failed. Please help.",
        "customer": {
            "external_id": "cust-itest-1",
            "email": "itest@example.com",
            "display_name": "Integration Test",
        },
    }


def _count(dsn: str, sql: str, params: tuple[object, ...]) -> int:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
    return int(row[0]) if row else 0


def test_ticket_travels_the_whole_path(client: TestClient, tenant_slug: str) -> None:
    """Request in, persisted reply out, terminal state, one correlation ID."""
    assert SETTINGS is not None
    ref = f"ref-{uuid.uuid4().hex[:8]}"

    response = client.post(
        "/v1/tickets",
        json=_payload(ref),
        headers={"X-Tenant-Slug": tenant_slug},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "resolved"
    assert body["reply"] == PlaceholderResolver.REPLY
    # The reply is traceable back to this exact request.
    assert response.headers[HEADER_NAME]

    dsn = str(SETTINGS.database_url)
    ticket_id = body["ticket_id"]

    # The ticket reached a terminal state *with* its completion timestamp —
    # the database would have refused the row otherwise.
    assert (
        _count(
            dsn,
            "SELECT count(*) FROM ticket WHERE id = %s AND status = 'resolved'"
            " AND resolved_at IS NOT NULL",
            (ticket_id,),
        )
        == 1
    )
    # Both sides of the conversation were persisted.
    assert _count(dsn, "SELECT count(*) FROM message WHERE ticket_id = %s", (ticket_id,)) == 2
    assert _count(dsn, "SELECT count(*) FROM resolution WHERE ticket_id = %s", (ticket_id,)) == 1


def test_resubmitting_the_same_reference_does_not_duplicate(
    client: TestClient, tenant_slug: str
) -> None:
    """Webhooks retry. The second delivery must not create a second ticket."""
    assert SETTINGS is not None
    ref = f"ref-{uuid.uuid4().hex[:8]}"
    headers = {"X-Tenant-Slug": tenant_slug}

    first = client.post("/v1/tickets", json=_payload(ref), headers=headers)
    second = client.post("/v1/tickets", json=_payload(ref), headers=headers)

    assert first.status_code == 201
    # 200, not 201: the caller can tell nothing new was created.
    assert second.status_code == 200
    assert first.json()["ticket_id"] == second.json()["ticket_id"]

    dsn = str(SETTINGS.database_url)
    assert _count(dsn, "SELECT count(*) FROM ticket WHERE external_ref = %s", (ref,)) == 1


def test_unknown_tenant_returns_the_standard_envelope(client: TestClient) -> None:
    response = client.post(
        "/v1/tickets",
        json=_payload("ref-nope"),
        headers={"X-Tenant-Slug": "no-such-tenant"},
    )

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["requestId"]


def test_failure_mid_flow_leaves_no_partial_ticket(tenant_slug: str) -> None:
    """The transaction boundary is what makes 'no partial state' true."""
    assert SETTINGS is not None
    ref = f"ref-{uuid.uuid4().hex[:8]}"

    class ExplodingResolver:
        async def resolve(self, ticket: object, messages: object) -> ResolutionDraft:
            raise RuntimeError("resolver blew up")

    # A fresh app with the failing resolver swapped in at the seam, and a
    # client that returns the 500 rather than re-raising it.
    app = create_app(SETTINGS)
    app.state.intake_service = IntakeService(resolver=ExplodingResolver())
    with TestClient(app, raise_server_exceptions=False) as failing_client:
        response = failing_client.post(
            "/v1/tickets",
            json=_payload(ref),
            headers={"X-Tenant-Slug": tenant_slug},
        )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"

    # The ticket and its inbound message were written before the resolver ran.
    # Both must have been rolled back.
    dsn = str(SETTINGS.database_url)
    assert _count(dsn, "SELECT count(*) FROM ticket WHERE external_ref = %s", (ref,)) == 0

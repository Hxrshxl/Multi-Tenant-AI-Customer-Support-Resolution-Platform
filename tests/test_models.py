"""The data model's own invariants, checked without a database."""

from __future__ import annotations

from sqlalchemy import DateTime

from app.db.base import NAMING_CONVENTION, Base
from app.db.models import (
    TERMINAL_TICKET_STATUSES,
    TICKET_TRANSITIONS,
    Action,
    AuditEntry,
    Customer,
    Message,
    Resolution,
    Ticket,
    TicketStatus,
)

TENANT_SCOPED = (Customer, Ticket, Message, Resolution, Action, AuditEntry)


def test_every_tenant_scoped_table_has_a_non_null_tenant_fk() -> None:
    """ADR-001: isolation is impossible if a table cannot be scoped at all."""
    for model in TENANT_SCOPED:
        column = model.__table__.columns["tenant_id"]
        assert column.nullable is False, f"{model.__tablename__}.tenant_id must be NOT NULL"
        targets = {fk.column.table.name for fk in column.foreign_keys}
        assert targets == {"tenant"}, f"{model.__tablename__}.tenant_id must reference tenant"


def test_every_foreign_key_declares_on_delete() -> None:
    """An unspecified referential action is a decision nobody made."""
    missing = [
        f"{table.name}.{fk.parent.name}"
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
        if fk.ondelete is None
    ]
    assert missing == [], f"foreign keys without ON DELETE: {missing}"


def test_money_columns_are_never_floating_point() -> None:
    """Binary floating point cannot represent 0.10. Money uses numeric."""
    money_columns = [
        (table.name, column.name, type(column.type).__name__)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.name in {"amount", "cost_usd"}
    ]
    assert money_columns, "expected monetary columns to exist"
    for table_name, column_name, type_name in money_columns:
        assert type_name == "Numeric", f"{table_name}.{column_name} is {type_name}, not Numeric"


def test_all_timestamps_are_timezone_aware() -> None:
    """A naive timestamp is a bug waiting for a daylight-saving boundary."""
    naive = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, DateTime) and not column.type.timezone
    ]
    assert naive == [], f"timestamps without a timezone: {naive}"


def test_terminal_statuses_have_no_outgoing_transitions() -> None:
    """Terminal means terminal. A resolved ticket cannot start resolving again."""
    for status in TERMINAL_TICKET_STATUSES:
        assert TICKET_TRANSITIONS[status] == frozenset(), f"{status} should be terminal"


def test_transition_map_covers_every_status() -> None:
    """A status missing from the map would silently permit nothing, or anything."""
    assert set(TICKET_TRANSITIONS) == set(TicketStatus)


def test_every_status_except_the_entry_point_is_reachable() -> None:
    """An unreachable status is dead weight that will mislead whoever reads it."""
    reachable = {TicketStatus.RECEIVED}
    for targets in TICKET_TRANSITIONS.values():
        reachable |= targets
    assert reachable == set(TicketStatus)


def test_constraint_naming_convention_is_applied() -> None:
    """Unnamed constraints get server-invented names that Alembic cannot drop."""
    assert Base.metadata.naming_convention == NAMING_CONVENTION
    unnamed = [
        f"{table.name}.{constraint!r}"
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if constraint.name is None
    ]
    assert unnamed == [], f"unnamed constraints: {unnamed}"

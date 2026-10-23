"""Ledger references must identify the same paid item and assignment epoch."""

from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.postgres_financial.test_financial_ledger_schema import put
from ugc_bot.infrastructure.db.models import ItemAssignmentModel, OrderItemModel

pytest_plugins = ("tests.postgres_financial.test_financial_ledger_schema",)


def assignment(seed, item, *, version=1, closed=False):
    return ItemAssignmentModel(
        assignment_id=uuid4(),
        paid_item_id=item,
        version=version,
        creator_id=seed["user"],
        manager_id=None,
        actor_id=seed["user"],
        valid_from=seed["now"],
        valid_to=seed["now"] if closed else None,
        reason="synthetic assignment scope",
    )


def test_snapshot_rejects_assignment_from_another_item(
    financial_pg_engine, ledger_seed
):
    seed = ledger_seed["seed"]
    foreign_item = uuid4()
    with Session(financial_pg_engine) as db, db.begin():
        db.add(
            OrderItemModel(
                paid_item_id=foreign_item,
                order_id=seed["order"],
                ordinal=2,
                currency="RUB",
                selection_minor=50000,
                accompaniment_minor=0,
                policy_version=seed["version"],
                selection_due_at=seed["now"],
                quote_key="foreign-assignment",
                quote_payload={},
            )
        )
        db.flush()
        other = assignment(seed, foreign_item)
        db.add(other)
        db.flush()
        other_id = other.assignment_id
    payload = ledger_seed["rate"] | dict(
        id=uuid4(), side="creator", assignment_id=other_id
    )
    with (
        financial_pg_engine.begin() as conn,
        pytest.raises(DBAPIError, match="fk_snapshot_assignment_scope"),
        conn.begin_nested(),
    ):
        put(conn, "rate_snapshots", payload)


@pytest.mark.parametrize("matching", [False, True])
def test_obligation_uses_exact_snapshot_assignment(
    financial_pg_engine, ledger_seed, matching
):
    seed = ledger_seed["seed"]
    with Session(financial_pg_engine) as db, db.begin():
        first = assignment(seed, seed["item"], closed=True)
        second = assignment(seed, seed["item"], version=2)
        db.add_all([first, second])
        db.flush()
        first_id, second_id = first.assignment_id, second.assignment_id
    rate = ledger_seed["rate"] | dict(
        id=uuid4(), side="creator", assignment_id=first_id
    )
    basis = ledger_seed["basis"] | dict(
        id=uuid4(),
        business_key=str(uuid4()),
        snapshot_id=rate["id"],
        kind="creator_referral",
        assignment_id=first_id if matching else second_id,
    )
    with financial_pg_engine.begin() as conn:
        put(conn, "rate_snapshots", rate)
        if matching:
            put(conn, "financial_obligations", basis)
        else:
            with (
                pytest.raises(DBAPIError, match="snapshot_assignment_mismatch"),
                conn.begin_nested(),
            ):
                put(conn, "financial_obligations", basis)

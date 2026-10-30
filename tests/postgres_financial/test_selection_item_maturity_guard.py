"""Per-item selection schedules are grounded in immutable delivery facts."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.helpers.corrections import captured_order, deliver_original_positions
from tests.postgres_financial.test_order_intake import intake_env
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import FinancialPolicyVersionModel

__all__ = ["intake_env"]


@pytest.mark.asyncio
@pytest.mark.parametrize("run_metadata_create_all", [False, True])
async def test_per_item_schedule_requires_delivery_and_exact_policy_dates(
    intake_env, run_metadata_create_all
):
    env = intake_env
    version = "item-maturity-" + uuid4().hex
    with Session(env["pg"]) as db, db.begin():
        db.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=env["admin"].user_id,
                approved_at=env["clock"].at - timedelta(days=2),
                effective_from=env["clock"].at - timedelta(days=1),
                refund_window_seconds=604800,
                rules={
                    "terms_reference": "synthetic-approved-terms",
                    "allowed_clients": [str(env["user"].user_id)],
                    "maturity_mode": "per_item_v1",
                    "selection_refund_window_anchor": (
                        "per_item_delivery_accepted_at"
                    ),
                    "hold_seconds": 1209600,
                },
            )
        )
    env["policy"] = version
    facts = await captured_order(env)
    delivered = await deliver_original_positions(env, facts, count=1)
    if run_metadata_create_all:
        Base.metadata.create_all(env["pg"])
        Base.metadata.create_all(env["pg"])
    item = delivered[0]
    with Session(env["pg"]) as db:
        delivery = (
            db.execute(
                select(
                    Base.metadata.tables["paid_selection_accepted_deliveries"]
                ).filter_by(paid_item_id=item)
            )
            .mappings()
            .one()
        )
    deadline = delivery["accepted_at"] + timedelta(days=7)
    values = dict(
        source_id=uuid4(),
        closure_id=None,
        paid_item_id=item,
        order_id=facts["order"].order_id,
        payment_id=facts["payment"].payment_id,
        client_id=env["user"].user_id,
        policy_version=version,
        refund_deadline_at=deadline,
        hold_started_at=deadline,
        release_at=deadline + timedelta(days=14),
    )
    schedules = Base.metadata.tables["financial_selection_schedules"]
    # A different undelivered item cannot borrow another item's delivery.
    undelivered = facts["order"].items[-1].paid_item_id
    with pytest.raises(IntegrityError), Session(env["pg"]) as db, db.begin():
        db.execute(
            insert(schedules).values(**(values | {"paid_item_id": undelivered}))
        )
    with pytest.raises(IntegrityError), Session(env["pg"]) as db, db.begin():
        db.execute(
            insert(schedules).values(
                **(
                    values
                    | {"refund_deadline_at": deadline + timedelta(seconds=1)}
                )
            )
        )
    for wrong in (
        {"client_id": env["admin"].user_id},
        {"payment_id": uuid4()},
        {"closure_id": uuid4()},
        {"release_at": deadline + timedelta(days=15)},
    ):
        with (
            pytest.raises(IntegrityError),
            Session(env["pg"]) as db,
            db.begin(),
        ):
            db.execute(insert(schedules).values(**(values | wrong)))
    with Session(env["pg"]) as db, db.begin():
        db.execute(insert(schedules).values(**values))
    with (
        pytest.raises(
            IntegrityError, match="financial_selection_fact_immutable"
        ),
        Session(env["pg"]) as db,
        db.begin(),
    ):
        db.execute(
            update(schedules)
            .where(schedules.c.source_id == values["source_id"])
            .values(release_at=deadline + timedelta(days=15))
        )
    # A rollback may not discard either the new schedule or its policy.
    from importlib import import_module

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0128_selection_per_item"
    )
    with env["pg"].begin() as connection:
        context = MigrationContext.configure(connection)
        with (
            Operations.context(context),
            pytest.raises(RuntimeError, match="Cannot downgrade per-item"),
        ):
            migration.downgrade()
    with Session(env["pg"]) as db:
        assert (
            db.execute(
                select(schedules).filter_by(source_id=values["source_id"])
            )
            .mappings()
            .one()["closure_id"]
            is None
        )


@pytest.mark.asyncio
async def test_service_moves_delivered_position_at_seven_and_21_days(
    intake_env,
):
    from tests.helpers.corrections import assess_original
    from ugc_bot.application.services.financial_ledger_service import (
        FinancialLedgerService,
    )
    from ugc_bot.application.services.selection_maturity_service import (
        SelectionMaturityService,
    )
    from ugc_bot.domain.refund_rules import RefundRules
    from ugc_bot.infrastructure.db.repositories.selection_maturity import (
        SqlAlchemySelectionMaturityRepository,
    )

    env = intake_env
    version = "item-service-" + uuid4().hex
    with Session(env["pg"]) as db, db.begin():
        db.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=env["admin"].user_id,
                approved_at=env["clock"].at - timedelta(days=2),
                effective_from=env["clock"].at - timedelta(days=1),
                refund_window_seconds=604800,
                rules={
                    "terms_reference": "synthetic-approved-terms",
                    "allowed_clients": [str(env["user"].user_id)],
                    "maturity_mode": "per_item_v1",
                    "selection_refund_window_anchor": (
                        "per_item_delivery_accepted_at"
                    ),
                    "hold_seconds": 1209600,
                    "refund_rules": RefundRules(
                        604800, "item_delivered", "manual", (), "retain_earned"
                    ).to_document(),
                },
            )
        )
    env["policy"] = version
    facts = await captured_order(env)
    await assess_original(env, facts)
    delivered = (await deliver_original_positions(env, facts, count=1))[0]
    with Session(env["pg"]) as db:
        delivery_at = (
            db.execute(
                select(
                    Base.metadata.tables["paid_selection_accepted_deliveries"]
                ).filter_by(paid_item_id=delivered)
            )
            .mappings()
            .one()["accepted_at"]
        )
    ledger = FinancialLedgerService(env["repos"]["financial_ledger_repo"])
    service = SelectionMaturityService(
        SqlAlchemySelectionMaturityRepository(), ledger, env["clock"]
    )
    tm = env["container"].transaction_manager

    async def refresh_at(when):
        env["clock"].at = when
        async with tm.transaction() as db:
            result = await service.refresh(facts["order"].order_id, session=db)
            wallet = await ledger.repository.read_projection(
                facts["partner"], "RUB", session=db
            )
            return result, wallet

    result, wallet = await refresh_at(
        delivery_at + timedelta(days=7, microseconds=-1)
    )
    assert result["state"] == "per_item" and len(result["items"]) == 1
    assert (wallet["pending"], wallet["hold"], wallet["available"]) == (
        150000,
        0,
        0,
    )
    _, wallet = await refresh_at(delivery_at + timedelta(days=7))
    assert (wallet["pending"], wallet["hold"], wallet["available"]) == (
        145000,
        5000,
        0,
    )
    _, wallet = await refresh_at(delivery_at + timedelta(days=21))
    assert (wallet["pending"], wallet["hold"], wallet["available"]) == (
        145000,
        0,
        5000,
    )
    _, repeated = await refresh_at(delivery_at + timedelta(days=21))
    assert repeated == wallet
    with Session(env["pg"]) as db:
        assert (
            db.execute(
                select(
                    Base.metadata.tables["financial_selection_closures"]
                ).filter_by(order_id=facts["order"].order_id)
            ).first()
            is None
        )


def test_migration_downgrades_when_no_per_item_facts_exist():
    import os
    from importlib import import_module

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    from tests.helpers.financial_environment import isolated_financial_database

    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Explicit isolated financial test PostgreSQL is required")
    migration = import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0128_selection_per_item"
    )
    with (
        isolated_financial_database(url) as engine,
        engine.begin() as connection,
    ):
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.downgrade()
            column = next(
                col
                for col in inspect(connection).get_columns(
                    "financial_selection_schedules"
                )
                if col["name"] == "closure_id"
            )
            assert column["nullable"] is False
            migration.upgrade()
            column = next(
                col
                for col in inspect(connection).get_columns(
                    "financial_selection_schedules"
                )
                if col["name"] == "closure_id"
            )
            assert column["nullable"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("day", [5, 13])
async def test_per_item_durations_survive_dst_and_repeated_create_all(
    intake_env, day
):
    from datetime import datetime, timezone

    from sqlalchemy import text

    env = intake_env
    version = "item-dst-" + uuid4().hex
    with Session(env["pg"]) as db, db.begin():
        db.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=env["admin"].user_id,
                approved_at=env["clock"].at - timedelta(days=2),
                effective_from=env["clock"].at - timedelta(days=1),
                refund_window_seconds=604800,
                rules={
                    "terms_reference": "synthetic-approved-terms",
                    "allowed_clients": [str(env["user"].user_id)],
                    "maturity_mode": "per_item_v1",
                    "selection_refund_window_anchor": (
                        "per_item_delivery_accepted_at"
                    ),
                    "hold_seconds": 1209600,
                },
            )
        )
    env["policy"] = version
    facts = await captured_order(env)
    item = (await deliver_original_positions(env, facts, count=1))[0]
    accepted = datetime(2027, 3, day, 12, tzinfo=timezone.utc)
    delivery = Base.metadata.tables["paid_selection_accepted_deliveries"]
    # Build synthetic historical source facts with a fixed DST boundary; the
    # test database is private and this transaction restores normal triggers.
    with Session(env["pg"]) as db, db.begin():
        db.execute(text("SET LOCAL session_replication_role = replica"))
        db.execute(
            update(delivery)
            .where(delivery.c.paid_item_id == item)
            .values(accepted_at=accepted)
        )
    Base.metadata.create_all(env["pg"])
    Base.metadata.create_all(env["pg"])
    deadline = accepted + timedelta(seconds=604800)
    values = dict(
        source_id=uuid4(),
        closure_id=None,
        paid_item_id=item,
        order_id=facts["order"].order_id,
        payment_id=facts["payment"].payment_id,
        client_id=env["user"].user_id,
        policy_version=version,
        refund_deadline_at=deadline,
        hold_started_at=deadline,
        release_at=deadline + timedelta(seconds=1209600),
    )
    with Session(env["pg"]) as db, db.begin():
        db.execute(text("SET LOCAL TIME ZONE 'America/New_York'"))
        db.execute(
            insert(
                Base.metadata.tables["financial_selection_schedules"]
            ).values(**values)
        )


def test_dst_migration_preserves_legacy_facts_across_session_timezones():
    import os
    from importlib import import_module

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    from tests.helpers.financial_environment import isolated_financial_database

    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Explicit isolated financial test PostgreSQL is required")
    migration = import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0128_selection_per_item"
    )
    source_id = uuid4()
    with isolated_financial_database(
        url, target_revision="0127_public_policy_scope"
    ) as engine:
        # Synthetic historical record: bypass fixture provenance FKs but keep
        # the original 14-calendar-day CHECK, using the creator's time zone.
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL TIME ZONE 'America/New_York'"))
            connection.execute(
                text("SET LOCAL session_replication_role=replica")
            )
            connection.execute(
                text(
                    "INSERT INTO financial_selection_schedules "
                    "(source_id, closure_id, paid_item_id, order_id, "
                    "payment_id, client_id, policy_version, "
                    "refund_deadline_at, "
                    "hold_started_at, release_at) VALUES "
                    "(:source, :closure, :item, :order_id, :payment, :client, "
                    "'synthetic-legacy', '2027-03-12 07:00-05', "
                    "'2027-03-12 07:00-05', "
                    "'2027-03-12 07:00-05'::timestamptz + INTERVAL '14 days')"
                ),
                dict(
                    source=source_id,
                    closure=uuid4(),
                    item=uuid4(),
                    order_id=uuid4(),
                    payment=uuid4(),
                    client=uuid4(),
                ),
            )
        # A UTC deployment must not reject a row originally created in a
        # different time zone when replacing either check during up or down.
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()
                assert connection.execute(
                    text(
                        "SELECT 1 FROM financial_selection_schedules "
                        "WHERE source_id=:source"
                    ),
                    {"source": source_id},
                ).one()
                migration.downgrade()
                assert connection.execute(
                    text(
                        "SELECT 1 FROM financial_selection_schedules "
                        "WHERE source_id=:source"
                    ),
                    {"source": source_id},
                ).one()

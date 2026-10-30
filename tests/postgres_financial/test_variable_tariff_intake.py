"""Variable tariffs retain quote and replay evidence in PostgreSQL."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from tests.postgres_financial.test_order_intake import (
    command,
    intake_env,
    scoped_rows,
    service,
)
from ugc_bot.infrastructure.db.models import FinancialPolicyVersionModel
from ugc_bot.infrastructure.db.repositories.order_intake import (
    SqlAlchemyOrderIntakeRepository,
)

__all__ = ["intake_env"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "count,selection,accompaniment,total",
    [(10, 50000, 120000, 860000), (200, 79000, 170000, 16310000)],
)
async def test_published_tariff_and_count_determine_saved_items(
    intake_env, count, selection, accompaniment, total
):
    env = intake_env
    version = "variable-" + uuid4().hex
    with Session(env["pg"]) as db, db.begin():
        old = db.get(FinancialPolicyVersionModel, env["policy"])
        db.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=old.approved_by,
                approved_at=old.approved_at,
                effective_from=old.effective_from,
                refund_window_seconds=old.refund_window_seconds,
                rules=old.rules
                | {
                    "selection_minor": selection,
                    "accompaniment_minor": accompaniment,
                },
            )
        )
    request = command(
        env,
        policy_version=version,
        position_count=count,
        service_mode="with_manager",
        accompaniment_ordinals=frozenset({1, 2, 3}),
    )
    result = await service(env).create(request)
    assert len(result.items) == count
    assert result.total_minor == total
    assert len(scoped_rows(env, "order_items", result.order_id)) == count
    assert (
        scoped_rows(env, "orders", result.order_id)[0]["bloggers_needed"]
        == count
    )
    env["config"].financial.selection_price_minor = 88000
    env["config"].financial.accompaniment_price_minor = 190000
    assert await service(env).create(request) == result
    assert {i.selection_minor for i in result.items} == {selection}
    policy = next(
        p
        for p in (
            await service(env).eligible_policies(env["user"].user_id)
        ).policies
        if p.version == version
    )
    assert (policy.selection_minor, policy.accompaniment_minor) == (
        selection,
        accompaniment,
    )
    assert (policy.min_position_count, policy.max_position_count) == (10, 200)
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        await service(env).create(replace(request, position_count=20))


@pytest.mark.asyncio
async def test_legacy_receipt_hash_replays_only_its_original_thirty_positions(
    intake_env,
):
    env = intake_env
    request = command(env)

    class LegacyReceipt(SqlAlchemyOrderIntakeRepository):
        async def save(self, receipt, lead, *, session):
            await super().save(
                replace(receipt, payload_hash=request.legacy_payload_hash),
                lead,
                session=session,
            )

    result = await service(env, repository=LegacyReceipt()).create(request)
    stored = scoped_rows(env, "order_intake_receipts", result.order_id)[0]
    assert stored["payload_hash"] != request.payload_hash
    assert await service(env).create(request) == result
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        await service(env).create(replace(request, position_count=10))
    assert (
        scoped_rows(env, "order_intake_receipts", result.order_id)[0][
            "payload_hash"
        ]
        == stored["payload_hash"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [9, 201, True, 10.5, "10"])
async def test_signed_api_rejects_non_integer_or_out_of_range_count(
    intake_env, count
):
    import httpx

    from tests.postgres_financial.test_order_intake_api import app, body

    env = intake_env
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(env, env["container"])),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/miniapp/api/financial/orders",
            json=body(env) | {"position_count": count},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selection,accompaniment,count",
    [
        (79000, 120000, 10),
        (1, 120000, 30),
        (50000, 170000, 30),
        (50000, 120000, 200),
    ],
)
async def test_downgrade_rejects_incompatible_history_before_ddl(
    intake_env, selection, accompaniment, count
):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import event as sqlalchemy_event
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from tests.postgres_financial.test_financial_issue_defensive import (
        persisted_state,
    )

    env = intake_env
    version = "downgrade-" + uuid4().hex
    with Session(env["pg"]) as db, db.begin():
        old = db.get(FinancialPolicyVersionModel, env["policy"])
        db.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=old.approved_by,
                approved_at=old.approved_at,
                effective_from=old.effective_from,
                refund_window_seconds=old.refund_window_seconds,
                rules=old.rules
                | {
                    "selection_minor": selection,
                    "accompaniment_minor": accompaniment,
                },
            )
        )
    result = await service(env).create(
        command(env, policy_version=version, position_count=count)
    )
    before = persisted_state(env["pg"])
    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0120_variable_tariff"
    )
    with env["pg"].begin() as db:
        old_guard = db.scalar(
            text(
                "SELECT pg_get_functiondef("
                "'intake_validate_source()'::regprocedure)"
            )
        )
        # Catch inside a savepoint: a preflight failure must precede any DDL,
        # and the caller can safely retain the surrounding transaction.
        statements = []

        def observe_sql(connection, cursor, statement, *args):
            statements.append(statement)

        sqlalchemy_event.listen(db, "before_cursor_execute", observe_sql)
        savepoint = db.begin_nested()
        try:
            with (
                pytest.raises(
                    DBAPIError,
                    match="variable_tariff_downgrade_incompatible_history",
                ),
                Operations.context(MigrationContext.configure(db)),
            ):
                migration.downgrade()
        finally:
            savepoint.rollback()
            sqlalchemy_event.remove(db, "before_cursor_execute", observe_sql)
        assert not any(
            "DROP TRIGGER" in sql or "ALTER TABLE" in sql for sql in statements
        )
        assert (
            db.scalar(
                text(
                    "SELECT pg_get_functiondef("
                    "'intake_validate_source()'::regprocedure)"
                )
            )
            == old_guard
        )
        assert db.scalar(
            text(
                "SELECT to_regprocedure("
                "'financial_policy_tariff_guard()') IS NOT NULL"
            )
        )
    assert persisted_state(env["pg"]) == before
    assert len(result.items) == count


@pytest.mark.asyncio
async def test_invoice_storage_accepts_largest_supported_pair(intake_env):
    from decimal import Decimal

    env = intake_env
    version = "invoice-limit-" + uuid4().hex
    with Session(env["pg"]) as db, db.begin():
        old = db.get(FinancialPolicyVersionModel, env["policy"])
        db.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=old.approved_by,
                approved_at=old.approved_at,
                effective_from=old.effective_from,
                refund_window_seconds=old.refund_window_seconds,
                rules=old.rules
                | {
                    "selection_minor": 49_879_999,
                    "accompaniment_minor": 120000,
                },
            )
        )
    result = await service(env).create(
        command(
            env,
            policy_version=version,
            position_count=200,
            service_mode="with_manager",
        )
    )
    from ugc_bot.application.services.financial_policy_service import (
        FinancialPolicyService,
    )
    from ugc_bot.infrastructure.db.repositories.financial_capture import (
        SqlAlchemyFinancialCaptureRepository,
    )

    repo = SqlAlchemyFinancialCaptureRepository(
        FinancialPolicyService(env["config"].financial)
    )
    async with env["container"].transaction_manager.transaction() as db:
        issued = await repo.issue(
            result.order_id, env["user"].user_id, "test", session=db
        )
    assert issued == (Decimal("99999998.00"), "RUB")
    assert scoped_rows(env, "payments", result.order_id)[0][
        "amount"
    ] == Decimal("99999998.00")


@pytest.mark.parametrize(
    "selection,accompaniment",
    [(49_880_000, 120000), (1, 49_999_999), (1_000_000_000, 120000)],
)
def test_sql_policy_rejects_pair_that_overflows_full_invoice(
    financial_pg_engine, selection, accompaniment
):
    from types import SimpleNamespace

    from sqlalchemy import insert
    from sqlalchemy.exc import DBAPIError

    from tests.postgres_financial.test_financial_items_schema import seed

    data = seed.__wrapped__(financial_pg_engine, SimpleNamespace())
    with (
        pytest.raises(DBAPIError, match="invalid_policy_tariff"),
        Session(financial_pg_engine) as db,
        db.begin(),
    ):
        old = db.get(FinancialPolicyVersionModel, data["version"])
        db.execute(
            insert(FinancialPolicyVersionModel).values(
                version="overflow-" + uuid4().hex,
                approved_by=old.approved_by,
                approved_at=old.approved_at,
                effective_from=old.effective_from,
                refund_window_seconds=old.refund_window_seconds,
                rules={
                    "selection_minor": selection,
                    "accompaniment_minor": accompaniment,
                },
            )
        )

"""A real customer refund respects all permanent manager cancellations."""

import os
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.helpers.financial_environment import isolated_financial_database
from tests.postgres_financial.test_accompaniment_reserved_payout import (
    REVIEW_RULES,
    actual_refund,
)
from tests.postgres_financial.test_financial_reviews import (
    management_key,
    open_ground,
    resolve_command,
    reviewed_service,
)
from tests.postgres_financial.test_payout_runtime import (
    capture_env,
    payout_env,
    prepare,
    result_command,
    wallet,
)
from ugc_bot.application.accompaniment_refund_ports import (
    ApplyAccompanimentRefund,
    ObserveAccompanimentRefund,
)
from ugc_bot.application.debt_recovery_ports import (
    ApplyDebtRecovery,
    RecordDebtRepayment,
)
from ugc_bot.container.debt_recovery_factory import build_debt_recovery
from ugc_bot.infrastructure.db.base import Base

__all__ = ["capture_env", "payout_env"]


@pytest.fixture(scope="module")
def financial_pg_engine():
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Explicit isolated financial PostgreSQL required")
    with isolated_financial_database(url) as engine:
        yield engine


async def recover_previous_cancellation(env, opened, key, amount):
    service = build_debt_recovery(env["config"])
    service.clock = env["service"].clock
    service.physical_proofs.clock = service.clock
    tm = env["flow"]["container"].transaction_manager
    async with tm.transaction() as db:
        observed = await service.observe(
            RecordDebtRepayment(
                actor_id=env["client"],
                operation_key="prior-correction-incoming:" + uuid4().hex,
                recipient_id=env["flow"]["manager"],
                case_id=UUID(opened["case_id"]),
                amount_minor=amount,
                currency="RUB",
                bank_account_label="synthetic-origin-account",
                bank_reference="synthetic-prior-repayment:" + uuid4().hex,
                occurred_at=service.clock.now(),
                reason="Actual incoming for previous cancelled liability",
                evidence_reference="synthetic:repayment-bank-proof",
                evidence_hash="c" * 64,
            ),
            session=db,
        )
    async with tm.transaction() as db:
        applied = await service.apply(
            ApplyDebtRecovery(
                actor_id=env["client"],
                operation_key="prior-correction-repaid:" + uuid4().hex,
                observation_id=UUID(observed["observation_id"]),
                business_key=key,
                case_id=UUID(opened["case_id"]),
                expected_debt_minor=amount,
                reason="Review actual repayment of original case",
                evidence_reference="synthetic:repayment-reviewed",
                evidence_hash="d" * 64,
            ),
            session=db,
        )
    assert applied["remaining_debt_minor"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("capture_env", [REVIEW_RULES], indirect=True)
@pytest.mark.parametrize(
    "paid,recovered,prior,increment",
    [
        (False, False, 10000, 20000),
        (True, False, 10000, 20000),
        (True, True, 10000, 20000),
        (False, False, 40000, 0),
        (True, True, 40000, 0),
    ],
)
async def test_actual_refund_after_independent_manager_correction(
    payout_env, paid, recovered, prior, increment
):
    env = payout_env
    tm = env["flow"]["container"].transaction_manager
    manager = env["flow"]["manager"]
    if paid:
        prepared = await prepare(env)
        assert (await env["execute"](result_command(env, prepared)))[
            "state"
        ] == "paid"
    reviews = await reviewed_service(env)
    key = management_key(env)
    opened = await open_ground(env, reviews, key)
    async with tm.transaction() as db:
        resolved = await reviews.resolve(
            resolve_command(env, opened, "cumulative_cancel", prior),
            session=db,
        )
    assert resolved["buckets"]["cancelled"] == prior
    if recovered:
        await recover_previous_cancellation(env, opened, key, prior)
    before = dict(wallet(env, manager))
    refunds, command = await actual_refund(env)
    async with tm.transaction() as db:
        result = await refunds.apply(command, session=db)
        assert await refunds.apply(command, session=db) == result
    assert result["customer_refund_minor"] == 60000
    assert result["manager_adjustment_minor"] == increment
    after = wallet(env, manager)
    assert after["cancelled_minor"] == max(prior, 30000)
    assert after["paid_minor"] == before["paid_minor"] == (60000 if paid else 0)
    assert after["debt_minor"] == before["debt_minor"] + (
        increment if paid else 0
    )
    applications = Base.metadata.tables[
        "financial_accompaniment_refund_applications"
    ]
    with Session(env["pg"]) as db:
        stored = (
            db.execute(
                select(applications).where(
                    applications.c.application_id
                    == UUID(result["application_id"])
                )
            )
            .mappings()
            .one()
        )
    assert stored["manager_target_minor"] == 30000
    assert stored["manager_delta_minor"] == increment


async def next_refund(env, service, *, manager_target):
    tm = env["flow"]["container"].transaction_manager
    async with tm.transaction() as db:
        scope = await service.repository.load_scope(
            env["flow"]["item"], session=db
        )
        observation = await service.observe(
            ObserveAccompanimentRefund(
                actor_id=env["client"],
                operation_key="next-actual-refund-report:" + uuid4().hex,
                paid_item_id=scope.paid_item_id,
                original_payment_reference=scope.original_payment_reference,
                amount_minor=30000,
                currency="RUB",
                bank_account_label="synthetic-origin-account",
                bank_reference="synthetic-next-outgoing:" + uuid4().hex,
                occurred_at=service.clock.now(),
                reason="Actual second partial customer refund",
                evidence_reference="synthetic:second-bank-proof",
                evidence_hash="e" * 64,
            ),
            session=db,
        )
    return ApplyAccompanimentRefund(
        actor_id=env["client"],
        operation_key="next-actual-refund-apply:" + uuid4().hex,
        observation_id=UUID(observation["observation_id"]),
        paid_item_id=scope.paid_item_id,
        expected_work_version=scope.work_version,
        reviewed_customer_target_minor=90000,
        reviewed_manager_target_minor=manager_target,
        reason="Cumulative actual customer refund after another review",
        evidence_reference="synthetic:second-reviewed-refund",
        evidence_hash="f" * 64,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("capture_env", [REVIEW_RULES], indirect=True)
@pytest.mark.parametrize(
    "prior,next_target,increment", [(10000, 45000, 15000), (40000, 35000, 0)]
)
async def test_later_refund_preserves_nominal_manager_target(
    payout_env, monkeypatch, prior, next_target, increment
):
    env = payout_env
    tm = env["flow"]["container"].transaction_manager
    reviews = await reviewed_service(env)
    opened = await open_ground(env, reviews, management_key(env))
    async with tm.transaction() as db:
        await reviews.resolve(
            resolve_command(env, opened, "cumulative_cancel", prior),
            session=db,
        )
    refunds, first = await actual_refund(env)
    async with tm.transaction() as db:
        await refunds.apply(first, session=db)
        assert await refunds.repository.totals(
            first.paid_item_id, session=db
        ) == (60000, 30000)
    command = await next_refund(env, refunds, manager_target=20000)
    with pytest.raises(
        ValueError, match="accompaniment_cumulative_target_conflict"
    ):
        async with tm.transaction() as db:
            await refunds.apply(command, session=db)
    real_totals = refunds.repository.totals

    async def false_previous_target(item_id, *, session):
        return 60000, 0

    monkeypatch.setattr(refunds.repository, "totals", false_previous_target)
    with pytest.raises(
        IntegrityError, match="accompaniment_refund_cumulative_mismatch"
    ):
        async with tm.transaction() as db:
            await refunds.apply(command, session=db)
    monkeypatch.setattr(refunds.repository, "totals", real_totals)
    async with tm.transaction() as db:
        result = await refunds.apply(
            replace(command, reviewed_manager_target_minor=next_target),
            session=db,
        )
    assert result["customer_refund_minor"] == 30000
    assert result["manager_adjustment_minor"] == increment
    assert wallet(env, env["flow"]["manager"])["cancelled_minor"] == max(
        prior, next_target
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("capture_env", [REVIEW_RULES], indirect=True)
async def test_refund_guard_migration_round_trip(payout_env):
    import importlib

    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0119_accompaniment_prior"
    )
    service, command = await actual_refund(payout_env)
    tm = payout_env["flow"]["container"].transaction_manager
    async with tm.transaction() as db:
        await service.apply(command, session=db)
    # Retained history cannot downgrade to the previous delta interpretation.
    with (
        pytest.raises(
            RuntimeError, match="accompaniment_refund_history_exists"
        ),
        payout_env["pg"].begin() as db,
        Operations.context(MigrationContext.configure(db)),
    ):
        migration.downgrade()
    with (
        isolated_financial_database(
            os.environ["FINANCIAL_TEST_DATABASE_URL"]
        ) as empty,
        empty.begin() as db,
        Operations.context(MigrationContext.configure(db)),
    ):
        migration.downgrade()
        definition = db.scalar(
            text(
                "SELECT pg_get_functiondef("
                "'accompaniment_refund_check_application()'::regprocedure)"
            )
        )
        assert "greatest(0,NEW.manager_target_minor-prior_manager)" not in (
            definition
        )
        migration.upgrade()
        definition = db.scalar(
            text(
                "SELECT pg_get_functiondef("
                "'accompaniment_refund_check_application()'::regprocedure)"
            )
        )
        assert (
            "greatest(0,NEW.manager_target_minor-prior_manager)" in definition
        )

"""A released partial reservation cannot strand the case's remaining block."""

import os
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from tests.helpers.financial_environment import isolated_financial_database
from tests.helpers.payout_contracts import acceptance_fields
from tests.postgres_financial.test_accompaniment_reserved_payout import (
    REVIEW_RULES,
)
from tests.postgres_financial.test_financial_reviews import (
    open_ground,
    resolve_command,
    reviewed_service,
)
from tests.postgres_financial.test_payout_runtime import (
    capture_env,
    payout_env,
    request_command,
    review_command,
)
from ugc_bot.application.payout_ports import StorePayoutRequisites
from ugc_bot.infrastructure.db.base import Base

__all__ = ["capture_env", "payout_env"]


@pytest.fixture(scope="module")
def financial_pg_engine(request):
    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision=getattr(
            request, "param", "0118_financial_review_restore"
        ),
        current_order_model=True,
    ) as engine:
        yield engine


async def creator_ground(env):
    partner = env["flow"]["partner"]
    requisites = await env["execute"](
        StorePayoutRequisites(
            actor_id=partner,
            operation_key="creator-details",
            requirements_id=env["requirements"]["requirements_id"],
            accepted_terms_reference="synthetic:payout-terms",
            details=env["details"],
            **acceptance_fields(env["requirements"]),
        )
    )
    payable = dict(
        env, flow=dict(env["flow"], manager=partner), requisites=requisites
    )
    table = Base.metadata.tables["financial_obligations"]
    with Session(env["pg"]) as db:
        key = db.scalar(
            select(table.c.business_key).where(
                table.c.recipient_id == partner,
                table.c.kind == "creator_referral",
            )
        )
    return payable, key


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [1000, 2000, 3000])
async def test_rejected_partial_reservation_restores_actual_uncancelled_block(
    payout_env, target
):
    env = payout_env
    payable, key = await creator_ground(env)
    app = await reviewed_service(env)
    tm = env["flow"]["container"].transaction_manager
    request = await env["execute"](request_command(payable, amount_minor=2000))
    opened = await open_ground(env, app, key)
    assert opened["buckets"]["reserved"] == 2000
    assert opened["buckets"]["blocked"] == 3000
    rejected = await env["execute"](review_command(env, request, "reject"))
    assert rejected["state"] == "rejected"
    async with tm.transaction() as db:
        current = await app.view(
            env["client"], UUID(opened["case_id"]), session=db
        )
        result = await app.resolve(
            resolve_command(env, current, "cumulative_cancel", target),
            session=db,
        )
    assert result["buckets"]["cancelled"] == target
    assert result["buckets"]["available"] == 5000 - target
    assert result["buckets"]["blocked"] == 0
    assert result["buckets"]["reserved"] == 0


@pytest.mark.asyncio
async def test_sql_rejects_nominal_restoration_after_partial_reservation(
    payout_env, monkeypatch
):
    from sqlalchemy.exc import IntegrityError

    env = payout_env
    payable, key = await creator_ground(env)
    app = await reviewed_service(env)
    tm = env["flow"]["container"].transaction_manager
    request = await env["execute"](request_command(payable, amount_minor=2000))
    opened = await open_ground(env, app, key)
    await env["execute"](review_command(env, request, "reject"))
    append = app.repository.append_resolution

    async def nominal_restore(fact, *, session):
        await append(
            dict(
                fact, restored_buckets=dict(pending=0, hold=0, available=1000)
            ),
            session=session,
        )

    monkeypatch.setattr(app.repository, "append_resolution", nominal_restore)
    with pytest.raises(
        IntegrityError, match="financial_review_restore_maturity_mismatch"
    ):
        async with tm.transaction() as db:
            current = await app.view(
                env["client"], UUID(opened["case_id"]), session=db
            )
            await app.resolve(
                resolve_command(env, current, "cumulative_cancel", 2000),
                session=db,
            )
    async with tm.transaction() as db:
        current = await app.view(
            env["client"], UUID(opened["case_id"]), session=db
        )
    assert current["state"] == "open"
    assert current["buckets"]["blocked"] == 3000
    assert current["buckets"]["available"] == 2000
    assert current["buckets"]["cancelled"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "capture_env",
    [REVIEW_RULES],
    indirect=True,
)
async def test_real_accompaniment_cancellation_during_open_review(payout_env):
    from tests.postgres_financial.test_accompaniment_reserved_payout import (
        actual_refund,
    )
    from tests.postgres_financial.test_financial_reviews import management_key

    env = payout_env
    app = await reviewed_service(env)
    tm = env["flow"]["container"].transaction_manager
    request = await env["execute"](request_command(env, amount_minor=20000))
    opened = await open_ground(env, app, management_key(env))
    assert opened["buckets"]["blocked"] == 40000
    refunds, command = await actual_refund(env)
    async with tm.transaction() as db:
        applied = await refunds.apply(command, session=db)
    assert applied["manager_adjustment_minor"] == 30000
    rejected = await env["execute"](review_command(env, request, "reject"))
    assert rejected["state"] == "rejected"
    async with tm.transaction() as db:
        current = await app.view(
            env["client"], UUID(opened["case_id"]), session=db
        )
        assert current["buckets"]["blocked"] == 10000
        assert current["buckets"]["available"] == 20000
        result = await app.resolve(
            resolve_command(env, current, "cumulative_cancel", 40000),
            session=db,
        )
    assert result["buckets"]["blocked"] == 0
    assert result["buckets"]["available"] == 20000
    assert result["buckets"]["cancelled"] == 40000
    assert result["buckets"]["paid"] == result["buckets"]["debt"] == 0


def restoration_functions(engine):
    with engine.connect() as db:
        return db.execute(
            text(
                "SELECT proname,prosrc FROM pg_proc "
                "WHERE pronamespace=current_schema()::regnamespace "
                "AND proname IN ('financial_review_blocked_cancelled',"
                "'financial_review_before_resolution',"
                "'financial_review_check_application') ORDER BY proname"
            )
        ).all()


def review_history(engine):
    names = (
        "financial_review_cases",
        "financial_review_commands",
        "financial_review_resolutions",
        "financial_movements",
    )
    with engine.connect() as db:
        return {
            name: db.execute(
                select(Base.metadata.tables[name]).order_by(
                    *Base.metadata.tables[name].primary_key.columns
                )
            ).all()
            for name in names
        }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "financial_pg_engine", ["0117_financial_reviews"], indirect=True
)
async def test_additive_upgrade_and_metadata_preserve_review_history(
    payout_env, monkeypatch
):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from tests.helpers.financial_environment import upgrade_financial_schema
    from tests.postgres_financial.test_financial_reviews import management_key

    env = payout_env
    app = await reviewed_service(env)
    tm = env["flow"]["container"].transaction_manager
    opened = await open_ground(env, app, management_key(env))
    async with tm.transaction() as db:
        await app.resolve(resolve_command(env, opened), session=db)
    # Reproduce the old 0117 source check's nominal cancellation semantics.
    with env["pg"].begin() as db:
        old = db.scalar(
            text(
                "SELECT pg_get_functiondef("
                "'financial_review_before_resolution()'::regprocedure)"
            )
        )
        assert "c.blocked_buckets,removed,maturity" in old
        db.exec_driver_sql(
            old.replace(
                "c.blocked_buckets,removed,maturity",
                "c.blocked_buckets,NEW.target_minor-c.prior_cancelled_minor,maturity",
            )
        )
    payable, key = await creator_ground(env)
    request = await env["execute"](request_command(payable, amount_minor=2000))
    opened = await open_ground(env, app, key)
    await env["execute"](review_command(env, request, "reject"))
    async with tm.transaction() as db:
        current = await app.view(
            env["client"], UUID(opened["case_id"]), session=db
        )
    command = resolve_command(env, current, "cumulative_cancel", 2000)
    with pytest.raises(
        IntegrityError, match="financial_review_restore_maturity_mismatch"
    ):
        async with tm.transaction() as db:
            await app.resolve(command, session=db)
    history = review_history(env["pg"])
    upgrade_financial_schema(
        env["pg"], target_revision="0118_financial_review_restore"
    )
    assert review_history(env["pg"]) == history
    functions = restoration_functions(env["pg"])
    assert len(functions) == 3
    for _ in range(2):
        Base.metadata.create_all(env["pg"])
        assert restoration_functions(env["pg"]) == functions
        assert review_history(env["pg"]) == history
    async with tm.transaction() as db:
        result = await app.resolve(command, session=db)
    assert result["buckets"]["available"] == 3000
    assert result["buckets"]["blocked"] == 0
    assert result["buckets"]["cancelled"] == 2000
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions."
        "0118_financial_review_restore"
    )
    history = review_history(env["pg"])
    with env["pg"].begin() as db:
        monkeypatch.setattr(
            migration, "op", Operations(MigrationContext.configure(db))
        )
        with pytest.raises(
            RuntimeError, match="financial_review_history_exists"
        ):
            migration.downgrade()
    assert review_history(env["pg"]) == history


def test_restore_fix_downgrade_is_allowed_without_case_history(monkeypatch):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions."
        "0118_financial_review_restore"
    )
    with (
        isolated_financial_database(
            os.environ["FINANCIAL_TEST_DATABASE_URL"],
            target_revision="0118_financial_review_restore",
        ) as engine,
        engine.begin() as db,
    ):
        monkeypatch.setattr(
            migration, "op", Operations(MigrationContext.configure(db))
        )
        migration.downgrade()
        source = db.scalar(
            text(
                "SELECT prosrc FROM pg_proc WHERE "
                "oid='financial_review_before_resolution()'::regprocedure"
            )
        )
        assert "NEW.target_minor-c.prior_cancelled_minor,maturity" in source
        assert (
            db.scalar(
                text(
                    "SELECT to_regprocedure("
                    "'financial_review_blocked_cancelled(uuid,jsonb)')"
                )
            )
            is None
        )
        migration.upgrade()
        assert (
            db.scalar(
                text(
                    "SELECT to_regprocedure("
                    "'financial_review_blocked_cancelled(uuid,jsonb)')"
                )
            )
            is not None
        )

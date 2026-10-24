"""Immutable correction facts and deferred original-source checks."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.helpers.correction_approval_pg import (
    genuine_approved_match as approved_match,
)
from tests.helpers.corrections import (
    append_application,
    assess_original,
    captured_order,
)
from tests.postgres_financial.test_order_intake import intake_env as intake_env

__all__ = ["intake_env"]


@pytest.mark.asyncio
async def test_unknown_early_report_preserves_untrusted_scope_and_signed_money(
    intake_env,
):
    from sqlalchemy import select

    from ugc_bot.application.correction_ports import (
        RecordManualRefundObservation,
        correction_command_hash,
    )
    from ugc_bot.infrastructure.db.correction_models import TABLE_MAP
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    unknown = uuid4()
    command = RecordManualRefundObservation(
        actor_id=env["admin"].user_id,
        operation_key="synthetic-unknown-early",
        reason="Retain an unsupported actual report",
        case_id=None,
        known_order_id=unknown,
        known_capture_intent_id=uuid4(),
        original_payment_reference="",
        bank_account_label="unrecognized",
        bank_reference="synthetic-reported",
        amount_minor=-1,
        currency="unknown",
        occurred_at=None,
        reported_component="unknown",
        evidence_reference="synthetic:reported",
        evidence_hash="a" * 64,
        expected_version=None,
    )
    repo = SqlAlchemyCorrectionRepository()
    observation = uuid4()
    async with env["container"].transaction_manager.transaction() as db:
        await repo.save_command(
            command,
            correction_command_hash(command),
            {"applied": False},
            session=db,
        )
        receipt = await repo.command(
            command.actor_id, command.operation_key, session=db
        )
        await repo.append_fact(
            "observations",
            dict(
                observation_id=observation,
                case_id=None,
                intent_id=None,
                command_id=receipt["command_id"],
                known_order_id=unknown,
                known_capture_intent_id=command.known_capture_intent_id,
                original_payment_reference="",
                bank_account_label="unrecognized",
                bank_reference="synthetic-reported",
                amount_minor=-1,
                currency="unknown",
                occurred_at=None,
                reported_component="unknown",
                provenance="manual_admin_observation",
                evidence_reference="synthetic:reported",
                evidence_hash="a" * 64,
                recorded_at=env["clock"].at,
            ),
            session=db,
        )
    async with env["container"].transaction_manager.transaction() as db:
        row = (
            (
                await db.execute(
                    select(TABLE_MAP["observations"]).where(
                        TABLE_MAP["observations"].c.observation_id
                        == observation
                    )
                )
            )
            .mappings()
            .one()
        )
        assert row["known_order_id"] == unknown and row["amount_minor"] == -1
        assert row["currency"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("referred", [True, False])
async def test_full_bundle_applies_only_actual_pending_or_covered_absence(
    intake_env, referred
):
    from sqlalchemy import select

    from ugc_bot.infrastructure.db.base import Base
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    facts = await captured_order(env, referred=referred)
    if referred:
        from tests.helpers.corrections import deliver_original_positions, rows

        delivered = await deliver_original_positions(env, facts)
        assert len(delivered) == 25
        assert (
            len(
                rows(
                    env,
                    "paid_selection_accepted_deliveries",
                    order_id=facts["order"].order_id,
                )
            )
            == 25
        )
    await assess_original(env, facts)
    repo = SqlAlchemyCorrectionRepository()
    async with env["container"].transaction_manager.transaction() as db:
        match = await approved_match(env, facts, repo, db)
        async with repo.application_savepoint(session=db):
            await append_application(env, facts, repo, match, db)
        await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    async with env["container"].transaction_manager.transaction() as db:
        funding = await repo.live_funding(
            match["scope"].selected_paid_item_ids[0], session=db
        )
        assert funding[0].net_minor == 0
        if referred:
            wallet = Base.metadata.tables["financial_wallets"]
            actual = (
                (
                    await db.execute(
                        select(wallet).where(
                            wallet.c.recipient_id == facts["partner"]
                        )
                    )
                )
                .mappings()
                .one()
            )
            assert actual["pending_minor"] == 125_000
            assert actual["cancelled_minor"] == 25_000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tamper",
    ["partial", "issuance", "target", "business", "assignment", "projection"],
)
async def test_deferred_guard_refuses_partial_or_unrelated_original_sources(
    intake_env, tamper
):
    from datetime import timedelta

    from ugc_bot.infrastructure.db.models import ItemAssignmentModel
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    facts = await captured_order(env)
    await assess_original(env, facts)
    repo = SqlAlchemyCorrectionRepository()
    with pytest.raises(DBAPIError, match="correction_"):
        async with env["container"].transaction_manager.transaction() as db:
            match = await approved_match(env, facts, repo, db)
            if tamper == "assignment":
                db.add(
                    ItemAssignmentModel(
                        assignment_id=uuid4(),
                        paid_item_id=match["scope"].selected_paid_item_ids[0],
                        version=1,
                        creator_id=facts["stranger"],
                        actor_id=env["admin"].user_id,
                        valid_from=env["clock"].at - timedelta(days=1),
                        valid_to=env["clock"].at,
                        reason="Synthetic historical assignment",
                    )
                )
                await db.flush()

            def mutate(value):
                if tamper == "issuance":
                    return {"issuance_entry_id": value["movement_id"]}
                if tamper == "target":
                    return {"target_minor": 5001, "delta_minor": 5001}
                if tamper == "business":
                    return {"business_key": "foreign:original"}
                return {}

            await append_application(
                env,
                facts,
                repo,
                match,
                db,
                omit_last=tamper == "partial",
                mutate_liability=mutate,
                skip_projection=tamper == "projection",
            )
            await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_correction_storage_exists_and_rejects_all_fact_mutations(
    financial_pg_engine,
):
    from ugc_bot.infrastructure.db.correction_models import TABLE_MAP

    assert len(TABLE_MAP) == 12
    with Session(financial_pg_engine) as db, db.begin():
        for key, table in TABLE_MAP.items():
            if key == "states":
                continue
            for operation in (
                f"UPDATE {table.name} SET "
                f"{list(table.c)[0].name}={list(table.c)[0].name}",
                f"DELETE FROM {table.name}",
                f"TRUNCATE {table.name} CASCADE",
            ):
                with (
                    pytest.raises(
                        DBAPIError, match="correction_fact_immutable"
                    ),
                    db.begin_nested(),
                ):
                    db.execute(text(operation))


def test_command_unique_actor_key_and_signed_observation_bounds(
    financial_pg_engine,
):
    from ugc_bot.domain.enums import MessengerType, UserStatus
    from ugc_bot.infrastructure.db.correction_models import TABLE_MAP
    from ugc_bot.infrastructure.db.models import UserModel

    actor, identity = uuid4(), uuid4()
    with Session(financial_pg_engine) as db, db.begin():
        db.add(
            UserModel(
                user_id=actor,
                username="synthetic-correction",
                messenger_type=MessengerType.TELEGRAM,
                status=UserStatus.ACTIVE,
            )
        )

        db.flush()
        data = dict(
            command_id=identity,
            actor_id=actor,
            operation_key="correction-test",
            action="RecordManualRefundObservation",
            payload_hash="a" * 64,
            recorded_at=datetime.now(timezone.utc),
            result={"retained": True},
        )
        db.execute(insert(TABLE_MAP["commands"]).values(**data))
        with pytest.raises(DBAPIError), db.begin_nested():
            db.execute(
                insert(TABLE_MAP["commands"]).values(
                    **(data | {"command_id": uuid4()})
                )
            )


@pytest.mark.asyncio
async def test_independent_connections_cannot_refund_the_same_component_twice(
    intake_env,
):
    import asyncio

    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    facts = await captured_order(env, referred=False)
    await assess_original(env, facts)
    repo = SqlAlchemyCorrectionRepository()
    ready = asyncio.Event()
    pids = set()
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ugc_bot.infrastructure.db.session import SessionTransactionManager

    engine = create_async_engine(env["pg"].url, pool_size=2, max_overflow=0)
    tm = SessionTransactionManager(
        async_sessionmaker(engine, expire_on_commit=False)
    )

    async def worker():
        try:
            async with tm.transaction() as db:
                pids.add(await db.scalar(text("SELECT pg_backend_pid()")))
                if len(pids) == 2:
                    ready.set()
                await asyncio.wait_for(ready.wait(), timeout=5)
                match = await approved_match(env, facts, repo, db)
                await append_application(env, facts, repo, match, db)
                await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            return "applied"
        except DBAPIError as error:
            assert "correction_component_capacity" in str(error)
            return "capacity_refused"

    try:
        outcomes = await asyncio.gather(worker(), worker())
    finally:
        await engine.dispose()
    assert len(pids) == 2
    assert sorted(outcomes) == ["applied", "capacity_refused"]


@pytest.mark.asyncio
async def test_deferred_refusal_preserves_observation_in_outer_transaction(
    intake_env,
):
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    facts = await captured_order(env)
    await assess_original(env, facts)
    repo = SqlAlchemyCorrectionRepository()
    async with env["container"].transaction_manager.transaction() as db:
        match = await approved_match(env, facts, repo, db)
        with pytest.raises(DBAPIError, match="correction_partial_bundle"):
            async with repo.application_savepoint(session=db):
                await append_application(
                    env, facts, repo, match, db, omit_last=True
                )
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM financial_refund_applications "
                    "WHERE match_id=:id"
                ),
                {"id": match["match_id"]},
            )
            == 0
        )
    async with env["container"].transaction_manager.transaction() as db:
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM financial_refund_observations "
                    "WHERE observation_id=:id"
                ),
                {"id": match["observation_id"]},
            )
            == 1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("referred", [True, False])
@pytest.mark.parametrize(
    "wrong_source", ["invoice_intent", "other_order_capture"]
)
async def test_application_rejects_real_event_outside_its_actual_capture(
    intake_env, referred, wrong_source
):
    from copy import copy

    from sqlalchemy import select

    from tests.helpers.corrections import rows
    from ugc_bot.infrastructure.db.base import Base
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )
    from ugc_bot.infrastructure.db.repositories.financial_capture import (
        intent_id,
    )

    env = intake_env
    facts = await captured_order(env, referred=referred)
    await assess_original(env, facts)
    if wrong_source == "invoice_intent":
        wrong = intent_id(facts["order"].order_id)
    else:
        other_env = env | {"clock": copy(env["clock"])}
        other_env["clock"].at = facts["capture_at"]
        other = await captured_order(other_env, referred=False)
        events = Base.metadata.tables["outbox_events"]
        with Session(env["pg"]) as db:
            wrong = db.scalar(
                select(events.c.event_id).where(
                    events.c.aggregate_id == str(other["order"].order_id),
                    events.c.event_type
                    == "financial.client_snapshot_requested",
                )
            )
        assert wrong is not None

    class WrongCaptureRepository(SqlAlchemyCorrectionRepository):
        async def append_fact(self, name, values, *, session):
            if name in ("matches", "applications"):
                values = values | {"capture_id": wrong}
            await super().append_fact(name, values, session=session)

    repo = WrongCaptureRepository()
    with pytest.raises(DBAPIError, match="correction_"):
        async with env["container"].transaction_manager.transaction() as db:
            match = await approved_match(env, facts, repo, db)
            async with repo.application_savepoint(session=db):
                await append_application(env, facts, repo, match, db)
    assert not rows(
        env, "financial_refund_applications", match_id=match["match_id"]
    )
    movements = Base.metadata.tables["financial_movements"]
    obligations = Base.metadata.tables["financial_obligations"]
    with Session(env["pg"]) as db:
        assert not db.scalars(
            select(movements.c.id)
            .join(obligations, obligations.c.id == movements.c.obligation_id)
            .where(
                obligations.c.order_id == facts["order"].order_id,
                movements.c.movement_type == "reversal",
            )
        ).all()
    if referred:
        wallet = rows(env, "financial_wallets", recipient_id=facts["partner"])[
            0
        ]
        assert wallet["pending_minor"] == 150_000
        assert wallet["cancelled_minor"] == 0

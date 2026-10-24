"""PostgreSQL delivery leases, unlocked I/O and crash recovery."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import delete, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from tests.postgres_financial.test_collaboration_persistence import (
    collaboration_pg as collaboration_fixture,
)
from tests.postgres_financial.test_collaboration_persistence import (
    command,
    execute,
    start,
)
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    DeliveryReceipt,
)
from ugc_bot.application.services.collaboration_notice_delivery import (
    CollaborationNoticeDelivery,
)
from ugc_bot.domain.enums import UserStatus
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    ItemAssignmentModel,
    OutboxEventModel,
    UserModel,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager

collaboration_pg = collaboration_fixture


async def environment(pg, *, claim=True):
    try:
        from ugc_bot.infrastructure.db.repositories.notice_delivery import (
            SqlAlchemyNoticeDeliveryRepository,
        )
    except ModuleNotFoundError:
        pytest.fail("Durable SQL notice repository is missing")
    factory, lifecycle, _, clock, data = pg
    await start(pg)
    await execute(
        factory,
        lifecycle,
        command(
            data,
            "claim" if claim else "request_confirmation",
            "creator" if claim else "manager",
            2,
            evidence="https://example.test/real-synthetic-proof"
            if claim
            else None,
        ),
    )
    async with factory.begin() as db:
        for role in ("client", "creator"):
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == data[role])
                .values(telegram_id=data[role].int % 10**14, language="en")
            )
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == data["manager"])
            .values(admin=True)
        )
        ids = tuple(
            await db.scalars(
                select(OutboxEventModel.event_id).where(
                    OutboxEventModel.aggregate_id == str(data["assignment"]),
                    OutboxEventModel.event_type
                    == "financial.collaboration.notice_requested",
                )
            )
        )
    repository = SqlAlchemyNoticeDeliveryRepository()

    class Transport:
        def __init__(self):
            self.sent = []

        async def send(self, attempt):
            # The committed attempt is visible to an independent connection and
            # the item lock can be acquired by it NOWAIT before provider I/O.
            assert factory.kw["bind"].pool.checkedout() == 0
            async with factory.begin() as db:
                assert (
                    await db.scalar(
                        text(
                            "select count(*) from financial_notice_attempts "
                            "where attempt_id=:id"
                        ),
                        {"id": attempt.attempt_id},
                    )
                    == 1
                )
                await db.execute(
                    text(
                        "select paid_item_id from order_items where "
                        "paid_item_id=:id for update nowait"
                    ),
                    {"id": data["item"]},
                )
            self.sent.append(attempt)
            return DeliveryReceipt(
                attempt.channel, "actual-synthetic-provider-reference"
            )

    transport = Transport()
    worker = CollaborationNoticeDelivery(
        lifecycle,
        repository,
        SessionTransactionManager(factory),
        transport,
        "https://example.test/miniapp/app.html",
        lease_seconds=60,
    )
    return worker, repository, transport, ids


async def dispatch(worker, event_id):
    attempt = await worker.prepare(event_id)
    if attempt is not None:
        await worker.deliver(attempt)
    return attempt


@pytest.mark.asyncio
async def test_notice_pg_native_action_is_committed_before_io_and_immutable(
    collaboration_pg,
):
    worker, _, transport, ids = await environment(collaboration_pg)
    factory, _, _, _, data = collaboration_pg
    expected = (
        f"https://example.test/miniapp/app.html?assignment={data['assignment']}"
    )

    class InspectCommittedAction:
        async def send(self, attempt):
            assert factory.kw["bind"].pool.checkedout() == 0
            async with factory.begin() as db:
                row = (
                    (
                        await db.execute(
                            text(
                                "select * from financial_notice_attempts "
                                "where attempt_id=:id"
                            ),
                            {"id": attempt.attempt_id},
                        )
                    )
                    .mappings()
                    .one()
                )
                assert row.get("action_url") == expected
                assert row.get("action_label") == "Open collaboration"
                assert attempt.action_url == row["action_url"]
            return await transport.send(attempt)

    worker.transport = InspectCommittedAction()
    attempt = await worker.prepare(ids[0])
    worker.miniapp_url = "https://changed.example.test/"
    await worker.deliver(attempt)
    assert len(transport.sent) == 1
    with pytest.raises(IntegrityError, match="notice_fact_immutable"):
        async with factory.begin() as db:
            await db.execute(
                text(
                    "update financial_notice_attempts set "
                    "action_url='https://tampered.example.test/' "
                    "where attempt_id=:id"
                ),
                {"id": attempt.attempt_id},
            )


async def work(pg):
    factory, _, repo, _, data = pg
    async with factory.begin() as db:
        return await repo.get(data["assignment"], session=db)


@pytest.mark.asyncio
async def test_notice_pg_committed_io_and_atomic_receipt(
    collaboration_pg, financial_pg_engine
):
    worker, repository, transport, ids = await environment(collaboration_pg)
    assert {
        "financial_notice_jobs",
        "financial_notice_attempts",
        "financial_notice_outcomes",
    } <= set(inspect(financial_pg_engine).get_table_names())
    await dispatch(worker, ids[0])
    record = await work(collaboration_pg)
    assert (
        record.version == 4
        and record.collaboration.notice_delivered_at is not None
    )
    assert record.collaboration.notice_failed_at is None
    factory, _, _, clock, _ = collaboration_pg
    async with factory.begin() as db:
        row = (
            await db.execute(
                text(
                    "select provider_reference,applied from "
                    "financial_notice_outcomes where attempt_id=:id"
                ),
                {"id": transport.sent[0].attempt_id},
            )
        ).one()
        assert row == ("actual-synthetic-provider-reference", True)
        candidates = await repository.candidates(clock.at, 1000, session=db)
        assert ids[0] not in candidates
    await dispatch(worker, ids[0])
    assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_notice_pg_failure_then_authorized_retry_keeps_silence_blocked(
    collaboration_pg,
):
    worker, _, transport, ids = await environment(collaboration_pg)
    factory, lifecycle, _, clock, data = collaboration_pg

    class Failed:
        async def send(self, attempt):
            raise DeliveryFailure("provider_rejected", uncertain=False)

    worker.transport = Failed()
    await dispatch(worker, ids[0])
    failure = (await work(collaboration_pg)).collaboration.notice_failed_at
    worker.transport = transport
    await worker.retry_notice(
        ids[0],
        actor_id=data["manager"],
        reason="reviewed failed contact",
        operation_key="manual-1",
    )
    clock.at += timedelta(minutes=1)
    await dispatch(worker, ids[0])
    record = await work(collaboration_pg)
    assert record.collaboration.notice_delivered_at == clock.at
    assert record.collaboration.notice_failed_at == failure
    clock.at += timedelta(hours=73)
    result = await execute(
        factory,
        lifecycle,
        command(
            data,
            "advance",
            None,
            record.version,
            system_actor="collaboration_scheduler",
        ),
    )
    assert result.collaboration.state.value == "success_claimed"


@pytest.mark.asyncio
@pytest.mark.parametrize("after_send", [False, True])
async def test_notice_pg_crash_recovery_without_resend(
    collaboration_pg, after_send
):
    worker, _, transport, ids = await environment(collaboration_pg)
    factory, _, _, clock, _ = collaboration_pg
    attempt = await worker.prepare(ids[0])

    class Crash(BaseException):
        pass

    class Interrupted:
        async def send(self, attempt):
            await transport.send(attempt)
            raise Crash()

    if after_send:
        worker.transport = Interrupted()
        with pytest.raises(Crash):
            await worker.deliver(attempt)
    clock.at += timedelta(seconds=61)
    assert await worker.prepare(ids[0]) is None
    assert (
        await work(collaboration_pg)
    ).collaboration.notice_failed_at == clock.at
    worker.transport = transport
    await worker.deliver(attempt)
    await dispatch(worker, ids[0])
    assert len(transport.sent) == int(after_send)
    async with factory.begin() as db:
        assert (
            await db.scalar(
                text(
                    "select status from financial_notice_outcomes where "
                    "attempt_id=:id and kind='recovery'"
                ),
                {"id": attempt.attempt_id},
            )
            == "unknown"
        )


@pytest.mark.asyncio
async def test_notice_pg_competing_workers_serialize_one_external_send(
    collaboration_pg,
):
    worker, _, transport, ids = await environment(collaboration_pg)
    await asyncio.gather(dispatch(worker, ids[0]), dispatch(worker, ids[0]))
    assert (
        len(transport.sent) == 1 and (await work(collaboration_pg)).version == 4
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["assignment", "role", "contact"])
async def test_notice_pg_current_scope_role_and_contact_rechecked_after_prepare(
    collaboration_pg, change
):
    worker, _, transport, ids = await environment(collaboration_pg)
    factory, _, _, clock, data = collaboration_pg
    attempt = await worker.prepare(ids[0])
    async with factory.begin() as db:
        if change == "assignment":
            await db.execute(
                update(ItemAssignmentModel)
                .where(ItemAssignmentModel.assignment_id == data["assignment"])
                .values(valid_to=clock.at)
            )
        elif change == "role":
            await db.execute(
                delete(AdvertiserProfileModel).where(
                    AdvertiserProfileModel.user_id == data["client"]
                )
            )
        else:
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == data["client"])
                .values(status=UserStatus.BOT_BLOCKED)
            )
    await worker.deliver(attempt)
    assert not transport.sent
    record = await work(collaboration_pg)
    assert record.collaboration.notice_delivered_at is None
    assert record.version == (4 if change == "contact" else 3)


@pytest.mark.asyncio
async def test_notice_pg_party_decision_wins_during_io(
    collaboration_pg,
):
    worker, _, transport, ids = await environment(collaboration_pg)
    factory, service, _, _, data = collaboration_pg

    class Decide:
        async def send(self, attempt):
            await transport.send(attempt)
            await execute(
                factory,
                service,
                command(
                    data, "dispute", "client", 3, reason="actual objection"
                ),
            )
            return DeliveryReceipt("telegram", "accepted-before-dispute")

    worker.transport = Decide()
    await dispatch(worker, ids[0])
    record = await work(collaboration_pg)
    assert (
        record.version == 4 and record.collaboration.state.value == "disputed"
    )
    assert record.collaboration.notice_delivered_at is None
    async with factory.begin() as db:
        assert (
            await db.scalar(
                text(
                    "select applied from financial_notice_outcomes where "
                    "attempt_id=:id"
                ),
                {"id": transport.sent[0].attempt_id},
            )
            is False
        )


@pytest.mark.asyncio
async def test_notice_pg_history_immutable_and_retained(
    collaboration_pg, financial_pg_engine
):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from ugc_bot.infrastructure.db.migrations.versions import (
        financial_notices_v1,
    )

    worker, _, transport, ids = await environment(collaboration_pg)
    await dispatch(worker, ids[0])
    factory = collaboration_pg[0]
    for table in ("financial_notice_attempts", "financial_notice_outcomes"):
        for operation in (
            f"update {table} set attempt_id=attempt_id",
            f"delete from {table}",
            f"truncate {table} cascade",
        ):
            with pytest.raises(IntegrityError, match="notice_fact_immutable"):
                async with factory.begin() as db:
                    await db.execute(text(operation))
    with (
        financial_pg_engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="notice delivery history"),
    ):
        financial_notices_v1.downgrade()


@pytest.mark.asyncio
async def test_notice_pg_does_not_take_or_wait_for_user_row_locks(
    collaboration_pg,
):
    worker, _, transport, ids = await environment(collaboration_pg)
    factory, _, _, _, data = collaboration_pg
    async with factory.begin() as other:
        await other.execute(
            select(UserModel.user_id)
            .where(UserModel.user_id.in_((data["client"], data["creator"])))
            .with_for_update()
        )
        attempt = await asyncio.wait_for(worker.prepare(ids[0]), timeout=3)
    assert attempt is not None
    await worker.deliver(attempt)
    assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_notice_pg_direct_attempt_forgery_rejected_by_authoritative_proof(
    collaboration_pg,
):
    from dataclasses import asdict
    from uuid import uuid4

    from ugc_bot.infrastructure.db.notice_delivery_models import (
        NoticeDeliveryAttemptModel,
    )

    worker, _, _, ids = await environment(collaboration_pg)
    factory, _, _, _, data = collaboration_pg
    attempt = await worker.prepare(ids[0])
    forged = replace(
        attempt, attempt_id=uuid4(), number=2, recipient_id=data["creator"]
    )
    with pytest.raises(IntegrityError, match="notice_attempt_proof_invalid"):
        async with factory.begin() as db:
            await db.execute(
                NoticeDeliveryAttemptModel.__table__.insert().values(
                    **asdict(forged)
                )
            )


@pytest.mark.asyncio
async def test_notice_pg_confirmation_is_receipted_without_objection_mutation(
    collaboration_pg,
):
    worker, _, transport, ids = await environment(collaboration_pg, claim=False)
    for key in ids:
        await dispatch(worker, key)
    assert len(transport.sent) == 2
    record = await work(collaboration_pg)
    assert (
        record.version == 3 and record.collaboration.notice_delivered_at is None
    )
    assert record.collaboration.notice_failed_at is None


@pytest.mark.asyncio
async def test_notice_pg_max_current_chat_and_user_fallback_are_server_owned(
    collaboration_pg,
):
    from ugc_bot.domain.enums import MessengerType

    worker, repository, _, _ = await environment(collaboration_pg)
    factory, _, _, _, data = collaboration_pg
    async with factory.begin() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == data["client"])
            .values(
                messenger_type=MessengerType.MAX,
                max_chat_id="123",
                max_id="456",
                language="kk",
            )
        )
    async with worker.transactions.transaction() as db:
        contact = await repository.contact(data["client"], session=db)
        assert (
            contact.channel,
            contact.address,
            contact.address_kind,
            contact.locale,
        ) == ("max", "123", "chat_id", "kk")
    async with factory.begin() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == data["client"])
            .values(max_chat_id=None)
        )
    async with worker.transactions.transaction() as db:
        contact = await repository.contact(data["client"], session=db)
        assert (contact.address, contact.address_kind) == ("456", "user_id")


@pytest.mark.asyncio
async def test_notice_pg_candidates_keep_other_owners_and_unknown_attempts_out(
    collaboration_pg,
):
    worker, repository, _, ids = await environment(collaboration_pg)
    factory, _, _, clock, data = collaboration_pg
    async with worker.transactions.transaction() as db:
        candidates = await repository.candidates(clock.at, 1000, session=db)
        other = set(
            await db.scalars(
                select(OutboxEventModel.event_id).where(
                    OutboxEventModel.aggregate_id == str(data["assignment"]),
                    OutboxEventModel.event_type
                    != "financial.collaboration.notice_requested",
                )
            )
        )
        assert ids[0] in candidates and not other.intersection(candidates)
    await worker.prepare(ids[0])
    clock.at += timedelta(seconds=61)
    async with worker.transactions.transaction() as db:
        assert ids[0] in await repository.candidates(clock.at, 1000, session=db)
    await worker.prepare(ids[0])
    async with worker.transactions.transaction() as db:
        assert ids[0] not in await repository.candidates(
            clock.at, 1000, session=db
        )
        assert await repository.origin(next(iter(other)), session=db) is None
        assert await repository.contact(data["assignment"], session=db) is None
        assert (
            await repository.retry_outcome("never-requested", session=db)
            is None
        )
        with pytest.raises(ValueError, match="limit"):
            await repository.candidates(clock.at, 0, session=db)


@pytest.mark.asyncio
async def test_notice_pg_result_commit_failure_recovers_unknown(
    collaboration_pg,
):
    from ugc_bot.infrastructure.db.repositories.notice_delivery import (
        SqlAlchemyNoticeDeliveryRepository,
    )

    worker, _, transport, ids = await environment(collaboration_pg)
    factory, _, _, clock, _ = collaboration_pg

    class FailingOutcome(SqlAlchemyNoticeDeliveryRepository):
        async def save_outcome(self, outcome, *, session):
            raise RuntimeError("crash while committing actual result")

    worker.repository = FailingOutcome()
    with pytest.raises(RuntimeError, match="committing actual result"):
        await dispatch(worker, ids[0])
    assert len(transport.sent) == 1
    record = await work(collaboration_pg)
    assert (
        record.version == 3 and record.collaboration.notice_delivered_at is None
    )
    clock.at += timedelta(seconds=61)
    worker.repository = SqlAlchemyNoticeDeliveryRepository()
    await dispatch(worker, ids[0])
    record = await work(collaboration_pg)
    assert record.collaboration.notice_failed_at == clock.at
    assert record.collaboration.notice_delivered_at is None
    await dispatch(worker, ids[0])
    assert len(transport.sent) == 1
    async with factory.begin() as db:
        assert (
            await db.scalar(
                text(
                    "select count(*) from financial_notice_outcomes "
                    "where attempt_id=:id"
                ),
                {"id": transport.sent[0].attempt_id},
            )
            == 1
        )


def test_notice_pg_empty_migration_roundtrip(financial_pg_engine):
    import os
    import subprocess
    import sys

    from tests.helpers.financial_environment import isolated_financial_database

    names = {
        "financial_notice_jobs",
        "financial_notice_attempts",
        "financial_notice_outcomes",
    }
    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="financial_lifecycle_v1",
    ) as engine:
        # Use the actual Alembic process, with a fresh import/DDL listener
        # registry exactly as production migrations do. Test-process global
        # GeoAlchemy listeners can be registered repeatedly by legacy imports.
        env = dict(
            os.environ,
            DATABASE_URL=engine.url.render_as_string(hide_password=False),
        )
        code = (
            "from alembic import command; from alembic.config import Config; "
            "c=Config('alembic.ini'); "
            "command.upgrade(c, 'financial_notices_v1'); "
            "command.downgrade(c, 'financial_lifecycle_v1'); "
            "command.upgrade(c, 'financial_notices_v1')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert names <= set(inspect(engine).get_table_names())


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_notice_pg_production_factory_records_actual_adapter_receipt(
    collaboration_pg, platform
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from ugc_bot.config import AppConfig
    from ugc_bot.container import Container
    from ugc_bot.domain.enums import MessengerType

    _, _, _, ids = await environment(collaboration_pg)
    factory, _, _, clock, data = collaboration_pg
    address = str(data["client"].int % 10**14)
    if platform == "max":
        async with factory.begin() as db:
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == data["client"])
                .values(messenger_type=MessengerType.MAX, max_chat_id=address)
            )
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": factory.kw["bind"].url.render_as_string(
                hide_password=False
            ),
            "FINANCIAL_CORE_ENABLED": True,
            "KAFKA_ENABLED": False,
            "USE_REDIS_STORAGE": False,
            "REDIS_URL": "",
            "WEBHOOK_BASE_URL": "https://telegram.example.test",
            "MAX_BOT_TOKEN": "synthetic-max-token" if platform == "max" else "",
            "MAX_BOT_WEBHOOK_URL": "https://max.example.test/max/webhook",
        }
    )
    container = Container(config)
    sent = []

    async def telegram_send(**request):
        assert container.session_factory.kw["bind"].pool.checkedout() == 0
        sent.append(request)
        return SimpleNamespace(
            message_id=777, chat=SimpleNamespace(id=request["chat_id"])
        )

    bot = SimpleNamespace(send_message=AsyncMock(side_effect=telegram_send))

    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def json(self):
            return {"message": {"body": {"mid": "max.provider.actual.777"}}}

    class MaxSession:
        def post(self, url, **request):
            assert container.session_factory.kw["bind"].pool.checkedout() == 0
            assert url == "https://platform-api2.max.ru/messages"
            assert request["params"] == {"chat_id": int(address)}
            sent.append(request)
            return Response()

    try:
        worker = container.build_collaboration_notice_delivery(
            bot, max_session=MaxSession() if platform == "max" else None
        )
        worker.lifecycle.clock = clock
        attempt = await dispatch(worker, ids[0])
        assert len(sent) == 1
        assert attempt.recipient_id == data["client"]
        expected_url = (
            "https://telegram.example.test/miniapp/app.html"
            if platform == "telegram"
            else "https://max.example.test/miniapp/max_app.html"
        )
        message = (
            sent[0]["text"]
            if platform == "telegram"
            else sent[0]["json"]["text"]
        )
        assert expected_url + f"?assignment={data['assignment']}" in message
        action_url = expected_url + f"?assignment={data['assignment']}"
        assert getattr(attempt, "action_url", None) == action_url
        if platform == "telegram":
            assert sent[0]["parse_mode"] is None
            assert (
                sent[0]["reply_markup"].inline_keyboard[0][0].web_app.url
                == action_url
            )
        else:
            bot.send_message.assert_not_awaited()
            assert sent[0]["json"]["attachments"] == [
                {
                    "type": "inline_keyboard",
                    "payload": {
                        "buttons": [
                            [
                                {
                                    "type": "open_app",
                                    "text": "Open collaboration",
                                    "web_app": action_url,
                                }
                            ]
                        ]
                    },
                }
            ]
        record = await work(collaboration_pg)
        assert (
            record.version == 4
            and record.collaboration.notice_delivered_at == clock.at
        )
        async with factory.begin() as db:
            reference = await db.scalar(
                text(
                    "select provider_reference from financial_notice_outcomes "
                    "where attempt_id=:id"
                ),
                {"id": attempt.attempt_id},
            )
            assert reference == (
                address + ":777"
                if platform == "telegram"
                else "max.provider.actual.777"
            )
    finally:
        await container.dispose()

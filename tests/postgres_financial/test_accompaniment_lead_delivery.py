"""An unpaid accompaniment request is durable before unlocked admin I/O."""

import asyncio
import os
from dataclasses import replace
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.postgres_financial.test_order_intake import (
    command,
    scoped_rows,
    service,
)
from tests.postgres_financial.test_order_intake import (
    intake_env as _intake_env,
)
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    DeliveryReceipt,
)
from ugc_bot.infrastructure.db.base import Base


@pytest_asyncio.fixture
async def intake_env(financial_pg_engine):
    from tests.helpers.financial_environment import isolated_financial_database

    # Admin recipients and pending lead jobs are global worker state; each
    # provider-boundary case needs a private schema, not fixture data filtering.
    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"]
    ) as isolated:
        async for env in _intake_env.__wrapped__(isolated):
            yield env


class Receiver:
    def __init__(self, env, failure=None, *, verify_unlocked=True):
        self.env, self.failure, self.messages = env, failure, []
        self.verify_unlocked = verify_unlocked

    async def send(self, message):
        self.messages.append(message)
        engine = self.env["container"].session_factory.kw["bind"]
        if self.verify_unlocked:
            assert engine.pool.checkedout() == 0
        # Preparation is committed and owns no row lock during provider I/O.
        with Session(self.env["pg"]) as db, db.begin():
            attempts = Base.metadata.tables["accompaniment_lead_attempts"]
            assert (
                db.execute(
                    select(attempts).where(
                        attempts.c.attempt_id == message.attempt_id
                    )
                ).first()
                is not None
            )
            jobs = Base.metadata.tables["accompaniment_lead_deliveries"]
            if self.verify_unlocked:
                db.execute(
                    select(jobs)
                    .where(jobs.c.job_id == message.job_id)
                    .with_for_update(nowait=True)
                ).one()
        await asyncio.sleep(0)
        if self.failure:
            raise self.failure
        return DeliveryReceipt(
            message.channel, "provider:actual-test-reference"
        )


def worker(env, receiver, *, repository=None):
    from ugc_bot.application.services.accompaniment_lead_delivery import (
        AccompanimentLeadDelivery,
    )
    from ugc_bot.infrastructure.db.repositories import (
        accompaniment_lead_delivery as lead_repo,
    )

    return AccompanimentLeadDelivery(
        repository or lead_repo.SqlAlchemyAccompanimentLeadDeliveryRepository(),
        env["container"].transaction_manager,
        receiver,
        env["clock"],
        lease_seconds=30,
    )


async def request(env):
    return await service(env).create(command(env, service_mode="with_manager"))


@pytest.mark.asyncio
async def test_current_admin_receives_notice_after_attempt_commit(
    intake_env,
):
    env = intake_env
    result = await request(env)
    receiver = Receiver(env)
    assert await worker(env, receiver).run_once() == 1
    message = receiver.messages[0]
    assert message.recipient_id == env["admin"].user_id
    assert message.address == env["admin"].telegram_id
    assert message.address != "client supplied protected contact"
    assert message.action_url is None
    jobs = scoped_rows(env, "accompaniment_lead_deliveries", result.order_id)
    assert len(jobs) == 1 and jobs[0]["state"] == "accepted"
    assert (
        scoped_rows(env, "accompaniment_leads", result.order_id)[0]["state"]
        == "requested_unpaid"
    )
    assert scoped_rows(env, "financial_obligations", result.order_id) == []
    outcomes = scoped_rows(env, "accompaniment_lead_outcomes", result.order_id)
    assert outcomes[0]["provider_reference"] == "provider:actual-test-reference"
    assert await worker(env, receiver).run_once() == 0
    assert len(receiver.messages) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "uncertain,state", [(False, "failed"), (True, "unknown")]
)
async def test_send_failure_preserves_lead_and_requires_reviewed_retry(
    intake_env, uncertain, state
):
    env = intake_env
    result = await request(env)
    receiver = Receiver(
        env, DeliveryFailure("provider_failed", uncertain=uncertain)
    )
    delivery = worker(env, receiver)
    await delivery.run_once()
    job = scoped_rows(env, "accompaniment_lead_deliveries", result.order_id)[0]
    assert job["state"] == state
    assert scoped_rows(env, "accompaniment_leads", result.order_id)
    assert await delivery.run_once() == 0
    assert len(receiver.messages) == 1
    with pytest.raises(PermissionError):
        await delivery.retry(
            job["job_id"],
            actor_id=env["user"].user_id,
            reason="review",
            operation_key="retry-non-admin",
        )
    await delivery.retry(
        job["job_id"],
        actor_id=env["admin"].user_id,
        reason="checked operator delivery",
        operation_key="retry-1",
    )
    receiver.failure = None
    await delivery.run_once()
    # A replayed operator command cannot reset accepted to ready.
    await delivery.retry(
        job["job_id"],
        actor_id=env["admin"].user_id,
        reason="checked operator delivery",
        operation_key="retry-1",
    )
    assert await delivery.run_once() == 0
    assert len(receiver.messages) == 2
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        await delivery.retry(
            job["job_id"],
            actor_id=env["admin"].user_id,
            reason="changed review",
            operation_key="retry-1",
        )


@pytest.mark.asyncio
async def test_crashed_prepared_attempt_becomes_unknown_without_sending(
    intake_env,
):
    env = intake_env
    result = await request(env)
    receiver = Receiver(env)
    delivery = worker(env, receiver)
    attempt = await delivery.prepare()
    assert attempt is not None
    env["clock"].at += timedelta(seconds=31)
    await delivery.run_once()
    assert receiver.messages == []
    assert (
        scoped_rows(env, "accompaniment_lead_deliveries", result.order_id)[0][
            "state"
        ]
        == "unknown"
    )
    assert (
        scoped_rows(env, "accompaniment_lead_outcomes", result.order_id)[0][
            "kind"
        ]
        == "recovery"
    )


@pytest.mark.asyncio
async def test_two_workers_send_one_admin_notification(intake_env):
    env = intake_env
    result = await request(env)
    # Another worker may hold a connection while this worker sends. The first
    # single-worker test proves that the sender releases its own transaction.
    receiver = Receiver(env, verify_unlocked=False)
    await asyncio.gather(
        worker(env, receiver).run_once(), worker(env, receiver).run_once()
    )
    assert len(receiver.messages) == 1
    assert (
        len(scoped_rows(env, "accompaniment_lead_attempts", result.order_id))
        == 1
    )
    assert (
        len(scoped_rows(env, "accompaniment_lead_outcomes", result.order_id))
        == 1
    )


@pytest.mark.asyncio
async def test_no_current_admin_keeps_intent_for_future_admin_configuration(
    intake_env,
):
    from ugc_bot.infrastructure.db.models import UserModel

    env = intake_env
    result = await request(env)
    with Session(env["pg"]) as db, db.begin():
        db.query(UserModel).filter_by(user_id=env["admin"].user_id).update(
            {"admin": False}
        )
    receiver = Receiver(env)
    assert await worker(env, receiver).run_once() == 0
    assert receiver.messages == []
    assert (
        scoped_rows(env, "accompaniment_lead_outbox", result.order_id)[0][
            "expanded_at"
        ]
        is None
    )
    with Session(env["pg"]) as db, db.begin():
        db.query(UserModel).filter_by(user_id=env["admin"].user_id).update(
            {"admin": True}
        )
    await worker(env, receiver).run_once()
    assert len(receiver.messages) == 1


@pytest.mark.asyncio
async def test_accepted_result_requires_real_provider_reference(intake_env):
    from sqlalchemy.exc import IntegrityError

    env = intake_env
    await request(env)
    delivery = worker(env, Receiver(env))
    attempt = await delivery.prepare()
    with pytest.raises(IntegrityError, match="ck_lead_acceptance_reference"):
        await delivery.finish(attempt, reference=None, failure=None)


@pytest.mark.asyncio
async def test_contact_change_after_send_is_audited_without_accepting_job(
    intake_env,
):
    from ugc_bot.infrastructure.db.models import UserModel

    env = intake_env
    result = await request(env)
    delivery = worker(env, Receiver(env))
    attempt = await delivery.prepare()
    with Session(env["pg"]) as db, db.begin():
        db.query(UserModel).filter_by(user_id=env["admin"].user_id).update(
            {"admin": False}
        )
    await delivery.finish(attempt, reference="provider:receipt", failure=None)
    assert (
        scoped_rows(env, "accompaniment_lead_deliveries", result.order_id)[0][
            "state"
        ]
        == "obsolete"
    )
    outcomes = scoped_rows(env, "accompaniment_lead_outcomes", result.order_id)
    assert outcomes[0]["applied"] is False
    assert outcomes[0]["provider_reference"] == "provider:receipt"
    assert await delivery.run_once() == 0


@pytest.mark.asyncio
async def test_late_receipt_preserves_unknown_and_rejects_forged_attempt(
    intake_env,
):
    env = intake_env
    result = await request(env)
    delivery = worker(env, Receiver(env))
    attempt = await delivery.prepare()
    with pytest.raises(ValueError, match="lead_attempt_source_mismatch"):
        await delivery.finish(
            replace(attempt, address="forged"),
            reference="provider:receipt",
            failure=None,
        )
    env["clock"].at += timedelta(seconds=31)
    assert await delivery.run_once() == 0
    await delivery.finish(attempt, reference="provider:late", failure=None)
    assert (
        scoped_rows(env, "accompaniment_lead_deliveries", result.order_id)[0][
            "state"
        ]
        == "unknown"
    )
    outcomes = scoped_rows(env, "accompaniment_lead_outcomes", result.order_id)
    assert len(outcomes) == 2
    assert (
        next(row for row in outcomes if row["kind"] == "result")["applied"]
        is False
    )


@pytest.mark.asyncio
async def test_provider_proof_replay_is_immutable(intake_env):
    env = intake_env
    result = await request(env)
    delivery = worker(env, Receiver(env))
    attempt = await delivery.prepare()
    await delivery.finish(attempt, reference="provider:first", failure=None)
    await delivery.finish(attempt, reference="provider:first", failure=None)
    with pytest.raises(ValueError, match="lead_outcome_payload_conflict"):
        await delivery.finish(
            attempt, reference="provider:changed", failure=None
        )
    outcomes = scoped_rows(env, "accompaniment_lead_outcomes", result.order_id)
    assert len(outcomes) == 1
    assert outcomes[0]["provider_reference"] == "provider:first"


@pytest.mark.asyncio
async def test_success_before_failed_result_commit_becomes_unknown_no_resend(
    intake_env,
):
    from contextlib import asynccontextmanager

    env = intake_env
    result = await request(env)
    receiver = Receiver(env)
    delivery = worker(env, receiver)
    transactions = delivery.transactions

    class CommitFailure:
        count = 0

        @asynccontextmanager
        async def transaction(self):
            async with transactions.transaction() as session:
                self.count += 1
                yield session
                if self.count == 2:
                    raise RuntimeError("result_commit_failure")

    delivery.transactions = CommitFailure()
    with pytest.raises(RuntimeError, match="result_commit_failure"):
        await delivery.run_once()
    assert len(receiver.messages) == 1
    assert (
        scoped_rows(env, "accompaniment_lead_outcomes", result.order_id) == []
    )
    env["clock"].at += timedelta(seconds=31)
    delivery.transactions = transactions
    assert await delivery.run_once() == 0
    assert len(receiver.messages) == 1
    assert (
        scoped_rows(env, "accompaniment_lead_deliveries", result.order_id)[0][
            "state"
        ]
        == "unknown"
    )


@pytest.mark.asyncio
async def test_notification_intent_and_recipient_scope_cannot_change(
    intake_env,
):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    env = intake_env
    result = await request(env)
    other = await service(env).create(command(env))
    delivery = worker(env, Receiver(env))
    await delivery.prepare()
    operations = [
        (
            "UPDATE accompaniment_lead_outbox SET order_id=:other "
            "WHERE order_id=:order",
            "lead_notification_source_mismatch",
        ),
        (
            "UPDATE accompaniment_lead_deliveries SET recipient_id=:user "
            "WHERE order_id=:order",
            "lead_delivery_scope_immutable",
        ),
        (
            "DELETE FROM accompaniment_lead_outbox WHERE order_id=:order",
            "order_intake_fact_immutable",
        ),
        (
            "DELETE FROM accompaniment_lead_deliveries WHERE order_id=:order",
            "order_intake_fact_immutable",
        ),
    ]
    for sql, reason in operations:
        with (
            pytest.raises(DBAPIError, match=reason),
            Session(env["pg"]) as db,
            db.begin(),
        ):
            db.execute(
                text(sql),
                {
                    "order": result.order_id,
                    "other": other.order_id,
                    "user": env["user"].user_id,
                },
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["exception", "channel", "empty_receipt"])
async def test_ambiguous_or_invalid_provider_proof_stays_unknown(
    intake_env, mode
):
    env = intake_env
    result = await request(env)

    class InvalidProof(Receiver):
        async def send(self, attempt):
            await super().send(attempt)
            if mode == "exception":
                raise RuntimeError("untrusted provider response")
            return DeliveryReceipt(
                "max" if mode == "channel" else "telegram",
                "" if mode == "empty_receipt" else "provider:ref",
            )

    receiver = InvalidProof(env)
    delivery = worker(env, receiver)
    assert await delivery.run_once() == 1
    assert await delivery.run_once() == 0
    assert len(receiver.messages) == 1
    assert (
        scoped_rows(env, "accompaniment_lead_deliveries", result.order_id)[0][
            "state"
        ]
        == "unknown"
    )


@pytest.mark.asyncio
async def test_missing_admin_contact_obsoletes_delivery_without_attempt(
    intake_env,
):
    from ugc_bot.infrastructure.db.models import UserModel

    env = intake_env
    result = await request(env)
    with Session(env["pg"]) as db, db.begin():
        db.query(UserModel).filter_by(user_id=env["admin"].user_id).update(
            {"telegram_id": None, "max_id": None, "max_chat_id": None}
        )
    receiver = Receiver(env)
    delivery = worker(env, receiver)
    assert await delivery.run_once() == 0
    assert receiver.messages == []
    assert (
        scoped_rows(env, "accompaniment_lead_deliveries", result.order_id)[0][
            "state"
        ]
        == "obsolete"
    )
    assert (
        scoped_rows(env, "accompaniment_lead_attempts", result.order_id) == []
    )


@pytest.mark.asyncio
async def test_max_admin_contact_uses_actual_shared_receipt_adapter(intake_env):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from tests.unit.test_notice_receipt_adapters import Response
    from ugc_bot.infrastructure.db.models import UserModel
    from ugc_bot.infrastructure.messenger.notice_receipts import (
        MaxNoticeReceipts,
    )

    env = intake_env
    result = await request(env)
    with Session(env["pg"]) as db, db.begin():
        db.query(UserModel).filter_by(user_id=env["admin"].user_id).update(
            {"telegram_id": None, "max_id": "123456", "max_chat_id": "654321"}
        )
    session = SimpleNamespace(
        post=Mock(
            return_value=Response(
                200, {"message": {"body": {"mid": "actual-max-reference"}}}
            )
        )
    )
    delivery = worker(env, MaxNoticeReceipts(session, "synthetic-token"))
    assert await delivery.run_once() == 1
    assert session.post.call_count == 1
    assert session.post.call_args.kwargs["params"] == {"chat_id": 654321}
    outcomes = scoped_rows(env, "accompaniment_lead_outcomes", result.order_id)
    assert outcomes[0]["provider_reference"] == "actual-max-reference"

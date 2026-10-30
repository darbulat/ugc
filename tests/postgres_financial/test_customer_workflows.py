"""Real PostgreSQL request atomicity, leased delivery, activity and payment."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tests.helpers.factories import create_test_order
from tests.postgres_financial.test_order_intake import intake_env as _intake_env
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    DeliveryReceipt,
)
from ugc_bot.application.services.customer_workflow_delivery import (
    CustomerWorkflowDelivery,
)
from ugc_bot.container.customer_workflow_factory import build_customer_workflows
from ugc_bot.domain.customer_workflows import ServiceLeadInput, SupportInput
from ugc_bot.infrastructure.db.customer_workflow_models import (
    JOBS,
    REQUESTS,
    SERIES,
)
from ugc_bot.infrastructure.db.models import PaymentModel, UserModel
from ugc_bot.infrastructure.db.repositories.customer_workflows import (
    SqlAlchemyCustomerWorkflowRepository,
)


@pytest_asyncio.fixture
async def intake_env(financial_pg_engine):
    # Only this module's new operational tables in its private UUID schema.
    with Session(financial_pg_engine) as db, db.begin():
        for table in (JOBS, SERIES, REQUESTS):
            db.execute(table.delete())
    async for env in _intake_env.__wrapped__(financial_pg_engine):
        yield env


class Receiver:
    def __init__(self, env, failure=None):
        self.env, self.messages, self.failure = env, [], failure

    async def send(self, message):
        assert (
            self.env["container"].session_factory.kw["bind"].pool.checkedout()
            == 0
        )
        self.messages.append(message)
        if self.failure:
            raise self.failure
        return DeliveryReceipt(message.channel, "synthetic:accepted")


def services(env):
    return build_customer_workflows(
        env["container"].transaction_manager, env["clock"]
    )


def worker(env, receiver):
    return CustomerWorkflowDelivery(
        SqlAlchemyCustomerWorkflowRepository(),
        env["container"].transaction_manager,
        receiver,
        env["clock"],
        {
            "telegram": "https://example.test/miniapp/app.html",
            "max": "https://example.test/miniapp/max_app.html",
        },
        lease_seconds=10,
    )


def rows(env, table):
    with Session(env["pg"]) as db:
        return [dict(row) for row in db.execute(select(table)).mappings()]


async def order(env):
    return await create_test_order(
        env["repos"]["order_repo"], advertiser_id=env["user"].user_id
    )


@pytest.mark.asyncio
async def test_support_replay_conflict_owner_and_failed_delivery(intake_env):
    env = intake_env
    support = services(env)["order_support_service"]
    owned = await order(env)
    command = SupportInput(
        order_id=owned.order_id,
        operation_key="same",
        reason="Need help",
        contact_reference="@client",
    )
    result, replay = await asyncio.gather(
        support.create(env["user"].user_id, command),
        support.create(env["user"].user_id, command),
    )
    assert result["request_id"] == replay["request_id"]
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        await support.create(
            env["user"].user_id,
            command.model_copy(update={"reason": "different"}),
        )
    with pytest.raises(PermissionError):
        await support.create(
            env["user"].user_id,
            command.model_copy(update={"order_id": uuid4()}),
        )
    receiver = Receiver(env, DeliveryFailure("synthetic", uncertain=True))
    await worker(env, receiver).run_once()
    own = [
        row
        for row in rows(env, REQUESTS)
        if row["request_id"] == result["request_id"]
    ]
    assert own[0]["state"] == "new"
    assert [
        row
        for row in rows(env, JOBS)
        if row["request_id"] == result["request_id"]
    ][0]["state"] == "unknown"
    assert await worker(env, receiver).run_once() == 0
    assert len(await support.list(env["user"].user_id, owned.order_id)) == 1


@pytest.mark.asyncio
async def test_result_lead_preserves_all_fields_and_sends_full_payload(
    intake_env,
):
    env = intake_env
    lead = services(env)["service_lead_service"]
    payload = dict(
        name="Name",
        telegram="@client",
        company="Brand",
        niche="Niche",
        product="Product",
        expected_benefit="Leads",
        website="https://example.test",
        geography="Earth",
        average_check="100",
        margin_or_cac="10",
        current_sales="5",
        goal="CPL",
        tracking="UTM",
    )
    result = await lead.create(
        env["user"].user_id,
        ServiceLeadInput(
            service_code="result",
            operation_key=str(uuid4()),
            contact_reference="@client",
            source="miniapp",
            parameters=payload,
            consent=True,
        ),
    )
    assert result["payload"]["parameters"] == payload
    assert result["order_id"] is None
    receiver = Receiver(env)
    await worker(env, receiver).run_once()
    delivered = "".join(message.text for message in receiver.messages)
    for value in payload.values():
        assert value in delivered


@pytest.mark.asyncio
async def test_followup_absolute_boundaries_remaining_stages_and_workers(
    intake_env,
):
    env = intake_env
    follow = services(env)["client_followup_service"]
    start = env["clock"].at
    series = await follow.record_activity(env["user"].user_id, "menu")
    current = await follow.state(env["user"].user_id)
    assert current["next_stage"] == 1 and current["next_action"] == "orders"
    receiver = Receiver(env)
    env["clock"].at = start + timedelta(seconds=3599)
    assert await worker(env, receiver).run_once() == 0
    env["clock"].at = start + timedelta(hours=1)
    # Separate commits prove restart and cross-worker ownership.
    jobs = await asyncio.gather(
        worker(env, receiver).prepare(), worker(env, receiver).prepare()
    )
    assert len([job for job in jobs if job]) == 1
    await worker(env, receiver).deliver(next(job for job in jobs if job))
    env["clock"].at = start + timedelta(hours=2)
    await follow.record_activity(env["user"].user_id, "brief_changed")
    env["clock"].at = start + timedelta(hours=25, seconds=3599)
    assert await worker(env, receiver).run_once() == 0
    env["clock"].at = start + timedelta(hours=26)
    assert await worker(env, receiver).run_once() == 1
    env["clock"].at = start + timedelta(hours=74)
    assert await worker(env, receiver).run_once() == 1
    assert len(receiver.messages) == 3
    assert (await follow.state(env["user"].user_id))["next_stage"] is None
    assert (
        len(
            [
                row
                for row in rows(env, JOBS)
                if row["series_id"] == series["series_id"]
            ]
        )
        == 3
    )


@pytest.mark.asyncio
async def test_activity_between_claim_and_send_reschedules_not_discards(
    intake_env,
):
    env = intake_env
    follow = services(env)["client_followup_service"]
    series = await follow.record_activity(env["user"].user_id, "menu")
    env["clock"].at += timedelta(hours=1)
    receiver = Receiver(env)
    job = await worker(env, receiver).prepare()
    assert job is not None
    await follow.record_activity(env["user"].user_id, "brief_opened")
    assert await worker(env, receiver).deliver(job) is False
    own = [
        row
        for row in rows(env, JOBS)
        if row["series_id"] == series["series_id"] and row["stage"] == 1
    ][0]
    assert own["state"] == "ready" and own["generation"] == 2
    env["clock"].at += timedelta(hours=1)
    assert await worker(env, receiver).run_once() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stop", ["optout", "paid", "blocked", "expired_lease", "expired_send"]
)
async def test_presend_stop_and_expired_lease(intake_env, stop):
    env = intake_env
    follow = services(env)["client_followup_service"]
    owned = await order(env)
    series = await follow.record_activity(
        env["user"].user_id, "order_created", owned.order_id
    )
    env["clock"].at += timedelta(hours=1)
    receiver = Receiver(env)
    job = await worker(env, receiver).prepare()
    assert job is not None
    if stop == "optout":
        await follow.optout(env["user"].user_id)
    elif stop == "paid":
        with Session(env["pg"]) as db, db.begin():
            db.add(
                PaymentModel(
                    payment_id=uuid4(),
                    order_id=owned.order_id,
                    provider="test",
                    status="paid",
                    amount=100,
                    currency="RUB",
                    external_id=str(uuid4()),
                    paid_at=env["clock"].at,
                )
            )
    elif stop == "blocked":
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == env["user"].user_id)
                .values(status="blocked")
            )
    else:
        if stop == "expired_send":
            with Session(env["pg"]) as db, db.begin():
                db.execute(
                    update(JOBS)
                    .where(JOBS.c.job_id == job["job_id"])
                    .values(state="sending")
                )
        env["clock"].at += timedelta(seconds=11)
        assert await worker(env, receiver).run_once() == 0
    assert await worker(env, receiver).deliver(job) is False
    assert receiver.messages == []
    if stop in ("expired_lease", "expired_send"):
        own = [
            row
            for row in rows(env, JOBS)
            if row["series_id"] == series["series_id"] and row["stage"] == 1
        ][0]
        assert own["state"] == (
            "ready" if stop == "expired_lease" else "unknown"
        )


@pytest.mark.asyncio
async def test_owner_principal_status_and_blogger_permissions(intake_env):
    from ugc_bot.application.native_principal_ports import (
        AuthenticatedMessengerPrincipal,
    )

    env = intake_env
    support = services(env)["order_support_service"]
    own = await order(env)
    command = SupportInput(
        order_id=own.order_id,
        operation_key="new",
        reason="Help",
        contact_reference="@me",
    )
    principal = AuthenticatedMessengerPrincipal(
        env["user"].user_id, "telegram", env["user"].telegram_id
    )
    result = await support.create(
        env["user"].user_id, command, principal=principal
    )
    with pytest.raises(ValueError, match="financial_principal_changed"):
        await support.create(
            env["user"].user_id,
            command,
            principal=AuthenticatedMessengerPrincipal(
                env["user"].user_id, "telegram", "wrong"
            ),
        )
    with pytest.raises(PermissionError, match="customer_blogger_forbidden"):
        await support.create(
            env["user"].user_id,
            command.model_copy(update={"blogger_id": uuid4()}),
        )
    await support.update_status(
        env["admin"].user_id, result["request_id"], "in_progress"
    )
    assert (await support.list(env["user"].user_id, own.order_id))[0][
        "state"
    ] == "in_progress"
    with pytest.raises(PermissionError):
        await support.update_status(
            env["user"].user_id, result["request_id"], "resolved"
        )
    with pytest.raises(ValueError):
        await support.update_status(
            env["admin"].user_id, result["request_id"], "invalid"
        )
    with pytest.raises(ValueError, match="customer_request_not_found"):
        await support.update_status(env["admin"].user_id, uuid4(), "resolved")
    catalog = await services(env)["service_lead_service"].catalog(
        env["user"].user_id
    )
    assert catalog["services"][0]["title"] == "Автоподбор"
    with pytest.raises(PermissionError):
        await services(env)["service_lead_service"].catalog(uuid4())


@pytest.mark.asyncio
async def test_optout_before_activity_and_trusted_paid_hook(intake_env):
    env = intake_env
    follow = services(env)["client_followup_service"]
    assert await follow.state(env["user"].user_id) is None
    with pytest.raises(ValueError, match="followup_event_invalid"):
        await follow.record_activity(env["user"].user_id, "paid")
    await follow.optout(env["user"].user_id)
    assert (await follow.record_activity(env["user"].user_id, "menu"))[
        "stop_reason"
    ] == "optout"
    owned = await order(env)
    await follow.record_paid(env["user"].user_id, owned.order_id)
    assert (await follow.state(env["user"].user_id))["stop_reason"] == "paid"


@pytest.mark.asyncio
async def test_multiple_orders_one_series_max_and_double_dispatch(intake_env):
    from ugc_bot.application.native_principal_ports import (
        AuthenticatedMessengerPrincipal,
    )

    env = intake_env
    follow = services(env)["client_followup_service"]
    first, second = await order(env), await order(env)
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["user"].user_id)
            .values(max_id="999999", messenger_type="max")
        )
    principal = AuthenticatedMessengerPrincipal(
        env["user"].user_id, "max", "999999"
    )
    series = await follow.record_activity(
        env["user"].user_id,
        "order_created",
        first.order_id,
        principal=principal,
    )
    next_series = await follow.record_activity(
        env["user"].user_id,
        "order_created",
        second.order_id,
        principal=principal,
    )
    assert (
        next_series["series_id"] == series["series_id"]
        and next_series["order_id"] == second.order_id
    )
    env["clock"].at += timedelta(hours=1)
    receiver = Receiver(env)
    sender = worker(env, receiver)
    job = await sender.prepare()
    assert job
    assert await sender.deliver(job)
    assert not await sender.deliver(job)
    assert len(receiver.messages) == 1 and receiver.messages[0].channel == "max"
    assert receiver.messages[0].address_kind == "user_id"
    assert str(second.order_id) in receiver.messages[0].action_url


@pytest.mark.asyncio
async def test_admin_removed_before_send_and_no_admin_keeps_pending(intake_env):
    env = intake_env
    support = services(env)["order_support_service"]
    owned = await order(env)
    command = SupportInput(
        order_id=owned.order_id,
        operation_key="pending",
        reason="Why",
        contact_reference="@me",
    )
    result = await support.create(env["user"].user_id, command)
    with Session(env["pg"]) as db, db.begin():
        db.execute(update(UserModel).values(admin=False))
    receiver = Receiver(env)
    assert await worker(env, receiver).run_once() == 0
    assert [
        row
        for row in rows(env, REQUESTS)
        if row["request_id"] == result["request_id"]
    ][0]["expanded_at"] is None
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["admin"].user_id)
            .values(admin=True)
        )
    job = await worker(env, receiver).prepare()
    assert job
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["admin"].user_id)
            .values(admin=False)
        )
    assert not await worker(env, receiver).deliver(job)
    assert receiver.messages == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["optout", "paid", "activity", "blocked"])
async def test_followup_rechecks_changes_during_message_preparation(
    intake_env, change
):
    env = intake_env
    follow = services(env)["client_followup_service"]
    owned = await order(env)
    series = await follow.record_activity(
        env["user"].user_id, "order_created", owned.order_id
    )
    env["clock"].at += timedelta(hours=1)
    receiver = Receiver(env)
    delivery = worker(env, receiver)

    async def change_while_preparing(_current):
        if change == "optout":
            await follow.optout(env["user"].user_id)
        elif change == "activity":
            await follow.record_activity(env["user"].user_id, "brief_changed")
        else:
            with Session(env["pg"]) as db, db.begin():
                if change == "blocked":
                    db.execute(
                        update(UserModel)
                        .where(UserModel.user_id == env["user"].user_id)
                        .values(status="blocked")
                    )
                else:
                    db.add(
                        PaymentModel(
                            payment_id=uuid4(),
                            order_id=owned.order_id,
                            provider="test",
                            status="paid",
                            amount=100,
                            currency="RUB",
                            external_id=str(uuid4()),
                            paid_at=env["clock"].at,
                        )
                    )
        return

    delivery.offer_loader = change_while_preparing
    job = await delivery.prepare()
    assert job is not None
    assert not await delivery.deliver(job)
    assert receiver.messages == []
    current = next(
        row
        for row in rows(env, JOBS)
        if row["series_id"] == series["series_id"] and row["stage"] == 1
    )
    assert current["state"] == ("ready" if change == "activity" else "obsolete")


@pytest.mark.asyncio
async def test_preparation_failure_retries_with_delay_and_limit(intake_env):
    env = intake_env
    follow = services(env)["client_followup_service"]
    series = await follow.record_activity(env["user"].user_id, "menu")
    env["clock"].at += timedelta(hours=1)
    receiver = Receiver(env)
    delivery = worker(env, receiver)

    async def failed_preparation(_current):
        raise RuntimeError("temporary local failure")

    delivery.offer_loader = failed_preparation
    for attempt in range(3):
        assert await delivery.run_once() == 1
        current = next(
            row
            for row in rows(env, JOBS)
            if row["series_id"] == series["series_id"] and row["stage"] == 1
        )
        assert current["state"] == ("ready" if attempt < 2 else "failed")
        if attempt < 2:
            assert await delivery.run_once() == 0
            env["clock"].at = current["due_at"]
    assert not receiver.messages


@pytest.mark.asyncio
async def test_changed_address_before_transport_is_retried(intake_env):
    env = intake_env
    follow = services(env)["client_followup_service"]
    series = await follow.record_activity(env["user"].user_id, "menu")
    env["clock"].at += timedelta(hours=1)
    receiver = Receiver(env)
    delivery = worker(env, receiver)
    repository = delivery.repository

    class ChangedAddress:
        def __getattr__(self, name):
            return getattr(repository, name)

        async def eligible(self, job, at, *, session, mark_sending=True):
            result = await repository.eligible(
                job, at, session=session, mark_sending=mark_sending
            )
            if result is not None and mark_sending:
                result["address"] = "changed-address"
            return result

    delivery.repository = ChangedAddress()
    assert await delivery.run_once() == 0
    current = next(
        row
        for row in rows(env, JOBS)
        if row["series_id"] == series["series_id"] and row["stage"] == 1
    )
    assert current["state"] == "ready"
    assert current["due_at"] == env["clock"].at + timedelta(seconds=30)
    assert not receiver.messages


@pytest.mark.asyncio
async def test_expired_preparation_lease_is_retried_without_losing_followup(
    intake_env,
):
    env = intake_env
    follow = services(env)["client_followup_service"]
    series = await follow.record_activity(env["user"].user_id, "menu")
    env["clock"].at += timedelta(hours=1)
    receiver = Receiver(env)
    delivery = worker(env, receiver)
    job = await delivery.prepare()

    async def slow_preparation(_current):
        env["clock"].at += timedelta(seconds=11)

    delivery.offer_loader = slow_preparation
    assert not await delivery.deliver(job)
    current = next(
        row
        for row in rows(env, JOBS)
        if row["series_id"] == series["series_id"] and row["stage"] == 1
    )
    assert current["state"] == "ready"
    assert current["due_at"] == env["clock"].at + timedelta(seconds=30)
    assert not receiver.messages
    env["clock"].at = current["due_at"]
    delivery.offer_loader = None
    assert await delivery.run_once() == 1
    assert len(receiver.messages) == 1


@pytest.mark.asyncio
async def test_rate_limit_retries_after_delay_with_limit(
    intake_env,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aiogram.exceptions import TelegramRetryAfter
    from aiogram.methods import SendMessage

    from ugc_bot.infrastructure.messenger.notice_receipts import (
        TelegramNoticeReceipts,
    )

    env = intake_env
    follow = services(env)["client_followup_service"]
    series = await follow.record_activity(env["user"].user_id, "menu")
    env["clock"].at += timedelta(hours=1)
    error = TelegramRetryAfter(
        method=SendMessage(chat_id=123, text="test"),
        message="limited",
        retry_after=120,
    )
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=error))
    delivery = worker(env, TelegramNoticeReceipts(bot))
    for attempt in range(3):
        assert await delivery.run_once() == 1
        current = next(
            row
            for row in rows(env, JOBS)
            if row["series_id"] == series["series_id"] and row["stage"] == 1
        )
        assert current["state"] == ("ready" if attempt < 2 else "failed")
        if attempt < 2:
            assert current["due_at"] >= env["clock"].at + timedelta(seconds=120)
            assert await delivery.run_once() == 0
            env["clock"].at = current["due_at"]
    assert bot.send_message.await_count == 3

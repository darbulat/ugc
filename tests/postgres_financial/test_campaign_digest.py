"""Weekly aggregate delivery uses committed one-shot receipt attempts."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.postgres_financial.conftest import (
    financial_pg_engine as _shared_engine,
)
from tests.postgres_financial.test_paid_selection_interest import seed_creators
from tests.postgres_financial.test_v1_capture import capture_env as _capture_env
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    DeliveryReceipt,
)
from ugc_bot.application.services.campaign_digest_service import (
    CampaignDigestService,
)
from ugc_bot.infrastructure.db.campaign_digest_models import (
    ATTEMPTS,
    JOBS,
    OUTCOMES,
    REQUESTS,
)
from ugc_bot.infrastructure.db.models import (
    InteractionModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.campaign_digest import (
    SqlAlchemyCampaignDigestRepository,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager

capture_env = _capture_env


@pytest.fixture
def financial_pg_engine(request):
    # Discovery is global, so each scenario owns a fresh schema rather than
    # hiding accumulated orders behind a test-only production scope filter.
    yield from _shared_engine.__wrapped__(request)


class Clock:
    def __init__(self):
        self.at = datetime.now(timezone.utc)

    def now(self):
        return self.at


def legacy_order(env, clock):
    if "digest_creators" not in env:
        env["digest_creators"] = seed_creators(env, count=30)
    creators = env["digest_creators"]
    order = uuid4()
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["client"])
            .values(telegram_id=str(uuid4().int % 10**12 + 1), language="ru")
        )
        db.add(
            OrderModel(
                order_id=order,
                advertiser_id=env["client"],
                status="closed",
                product_link="https://example.test/product",
                offer_text="legacy",
                price=1,
                bloggers_needed=30,
            )
        )
        db.flush()
        db.add_all(
            [
                InteractionModel(
                    interaction_id=uuid4(),
                    order_id=order,
                    blogger_id=c,
                    advertiser_id=env["client"],
                    status="pending",
                    next_check_at=clock.at - timedelta(seconds=1),
                )
                for c in creators
            ]
        )
    return order


class RecordingTransport:
    def __init__(self, env, order):
        self.env, self.order, self.calls = env, order, []

    async def send(self, attempt):
        engine = getattr(self, "async_engine", self.env["factory"].kw["bind"])
        assert engine.pool.checkedout() == 0
        with Session(self.env["pg"]) as db:
            assert (
                db.scalar(
                    select(ATTEMPTS.c.attempt_id).where(
                        ATTEMPTS.c.attempt_id == attempt.attempt_id
                    )
                )
                == attempt.attempt_id
            )
            assert (
                db.scalar(
                    select(OUTCOMES.c.outcome_id).where(
                        OUTCOMES.c.attempt_id == attempt.attempt_id,
                        OUTCOMES.c.kind == "started",
                    )
                )
                is not None
            )
        self.calls.append(attempt)
        return DeliveryReceipt(
            attempt.channel, f"{attempt.address}:{len(self.calls)}"
        )


@pytest.mark.asyncio
async def test_30_creators_get_one_weekly_summary_without_silence_success(
    capture_env,
    monkeypatch,
):
    from tests.postgres_financial.test_selection_view_api import configuration
    from ugc_bot import campaign_digest_scheduler, feedback_scheduler
    from ugc_bot.container import Container, campaign_digest_factory

    env, clock = capture_env, Clock()
    order = legacy_order(env, clock)
    transport = RecordingTransport(env, order)
    config = configuration(env, enabled=False)
    config.feedback.feedback_enabled = True
    config.feedback.campaign_digest_enabled = True
    config.webhook.webhook_base_url = "https://example.test"
    container = Container(config)
    transport.async_engine = container.session_factory.kw["bind"]
    monkeypatch.setattr(campaign_digest_factory, "SystemClock", lambda: clock)
    monkeypatch.setattr(
        campaign_digest_factory, "TelegramNoticeReceipts", lambda bot: transport
    )

    async def retired(*args, **kwargs):
        raise AssertionError("retired per-author rating cascade")

    monkeypatch.setattr(feedback_scheduler, "run_once", retired)

    async def sweep():
        await campaign_digest_scheduler.run_enabled(
            config, container, object(), max_iterations=1
        )

    await sweep()
    assert len(transport.calls) == 1
    assert transport.calls[0].source["total"] == 30
    assert transport.calls[0].source["states"] == {"legacy_pending": 30}
    assert "summary=" + str(order) in transport.calls[0].action_url
    initial = clock.at
    for elapsed in (
        timedelta(hours=24),
        timedelta(hours=72),
        timedelta(days=7, seconds=-1),
    ):
        clock.at = initial + elapsed
        await sweep()
    assert len(transport.calls) == 1
    clock.at = initial + timedelta(days=7)
    await sweep()
    assert len(transport.calls) == 2
    await container.dispose()


def worker(env, clock, transport):
    return CampaignDigestService(
        SqlAlchemyCampaignDigestRepository(),
        SessionTransactionManager(env["factory"]),
        transport,
        clock,
        {
            "telegram": "https://example.test/miniapp/app.html",
            "max": "https://example.test/miniapp/max_app.html",
        },
    )


async def enqueue(service, order, actor):
    async with service.transactions.transaction() as db:
        source = await service.repository.lock_source(
            order, actor, service.clock.now(), session=db
        )
        assert source is not None
        return await service.repository.enqueue(
            source, service.clock.now(), session=db
        )


@pytest.mark.asyncio
async def test_financial_digest_uses_actual_capture_and_current_manager_scope(
    capture_env, monkeypatch
):
    from tests.postgres_financial.test_work_entitlement_runtime import (
        start_flow,
    )

    env, clock = capture_env, Clock()
    flow = await start_flow(env, monkeypatch)
    clock.at = flow["clock"].at
    order = env["order"]
    try:
        with Session(env["pg"]) as db, db.begin():
            for actor in (env["client"], flow["manager"]):
                db.execute(
                    update(UserModel)
                    .where(UserModel.user_id == actor)
                    .values(telegram_id=str(uuid4().int % 10**12 + 1))
                )
        transport = RecordingTransport(env, order)
        service = worker(env, clock, transport)
        await service.run_once()
        assert len(transport.calls) == 2
        assert {
            (a.source["role"], a.source["total"]) for a in transport.calls
        } == {("client", 2), ("manager", 1)}
        assert all(
            "success_final" not in a.source["states"] for a in transport.calls
        )
        assert all(a.source["contact_accepted"] == 0 for a in transport.calls)
        with Session(env["pg"]) as db:
            assert (
                db.scalar(
                    select(REQUESTS.c.request_id).where(
                        REQUESTS.c.recipient_id == flow["partner"]
                    )
                )
                is None
            )
    finally:
        await flow["container"].dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["pause", "contact", "scope", "deleted"])
async def test_prepared_digest_never_sends_to_changed_scope_or_contact(
    capture_env, change
):
    env, clock = capture_env, Clock()
    order = legacy_order(env, clock)
    transport = RecordingTransport(env, order)
    service = worker(env, clock, transport)
    request = await enqueue(service, order, env["client"])
    attempt = await service.prepare(request)
    assert attempt
    with Session(env["pg"]) as db, db.begin():
        if change == "scope":
            from ugc_bot.infrastructure.db.models import AdvertiserProfileModel

            db.execute(
                delete(AdvertiserProfileModel).where(
                    AdvertiserProfileModel.user_id == env["client"]
                )
            )
        elif change == "deleted":
            db.execute(
                update(OrderModel)
                .where(OrderModel.order_id == order)
                .values(status="deleted")
            )
        else:
            values = (
                {"status": "pause"}
                if change == "pause"
                else {"telegram_id": "987654321"}
            )
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == env["client"])
                .values(**values)
            )
    await service.deliver(attempt)
    assert transport.calls == []
    with Session(env["pg"]) as db:
        assert (
            db.scalar(select(JOBS.c.state).where(JOBS.c.request_id == request))
            == "obsolete"
        )
        assert (
            db.scalar(
                select(OUTCOMES.c.reason).where(
                    OUTCOMES.c.request_id == request
                )
            )
            == "digest_source_changed"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome", ["failed", "unknown", "exception", "invalid_receipt"]
)
async def test_failed_or_unknown_delivery_never_auto_resends(
    capture_env, outcome
):
    env, clock = capture_env, Clock()
    legacy_order(env, clock)

    class Transport:
        calls = 0

        async def send(self, attempt):
            self.calls += 1
            if outcome in ("failed", "unknown"):
                raise DeliveryFailure(
                    "safe_error", uncertain=outcome == "unknown"
                )
            if outcome == "exception":
                raise RuntimeError("private provider body")
            return DeliveryReceipt("max", "wrong-channel")

    transport = Transport()
    service = worker(env, clock, transport)
    await service.run_once()
    clock.at += timedelta(hours=72)
    await service.run_once()
    assert transport.calls == 1
    with Session(env["pg"]) as db:
        assert db.scalar(select(JOBS.c.state)) == (
            "failed" if outcome == "failed" else "unknown"
        )
        result = (
            db.execute(select(OUTCOMES).where(OUTCOMES.c.kind == "transport"))
            .mappings()
            .one()
        )
        assert not result["applied"] and result["provider_reference"] is None
        assert "private" not in repr(result)


@pytest.mark.asyncio
async def test_crash_after_committed_start_is_sticky_and_late_receipt_retained(
    capture_env,
):
    env, clock = capture_env, Clock()
    order = legacy_order(env, clock)
    entered, release = asyncio.Event(), asyncio.Event()

    class Slow(RecordingTransport):
        async def send(self, attempt):
            receipt = await super().send(attempt)
            entered.set()
            await release.wait()
            return receipt

    transport = Slow(env, order)
    service = worker(env, clock, transport)
    task = asyncio.create_task(service.run_once())
    await asyncio.wait_for(entered.wait(), 3)
    try:
        clock.at += timedelta(seconds=121)
        await service.run_once()
        release.set()
        await task
        await service.run_once()
        assert len(transport.calls) == 1
        with Session(env["pg"]) as db:
            assert db.scalar(select(JOBS.c.state)) == "unknown"
            results = db.execute(select(OUTCOMES)).mappings().all()
            assert {r["kind"] for r in results} == {
                "started",
                "recovery",
                "transport",
            }
            accepted = next(r for r in results if r["kind"] == "transport")
            assert accepted["status"] == "accepted" and not accepted["applied"]
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_two_workers_and_transaction_rollback_cannot_duplicate_send(
    capture_env,
):
    env, clock = capture_env, Clock()
    order = legacy_order(env, clock)
    transport = RecordingTransport(env, order)
    service = worker(env, clock, transport)
    with pytest.raises(RuntimeError, match="rollback"):
        async with service.transactions.transaction() as db:
            source = await service.repository.lock_source(
                order, env["client"], clock.at, session=db
            )
            await service.repository.enqueue(source, clock.at, session=db)
            raise RuntimeError("rollback")
    with Session(env["pg"]) as db:
        assert db.scalar(select(REQUESTS.c.request_id)) is None
    assert await enqueue(service, order, env["client"]) is not None
    assert await enqueue(service, order, env["client"]) is None
    await asyncio.gather(service.run_once(), service.run_once())
    assert len(transport.calls) == 1
    with Session(env["pg"]) as db:
        assert len(db.execute(select(REQUESTS)).all()) == 1
        assert len(db.execute(select(ATTEMPTS)).all()) == 1
    for table in (REQUESTS, ATTEMPTS, OUTCOMES):
        with (
            pytest.raises(IntegrityError, match="campaign_digest_immutable"),
            env["pg"].begin() as db,
        ):
            db.execute(text(f"TRUNCATE {table.name} CASCADE"))


@pytest.mark.asyncio
async def test_deleted_order_does_not_starve_a_later_eligible_order(
    capture_env,
):
    env, clock = capture_env, Clock()
    deleted = legacy_order(env, clock)
    later = legacy_order(env, clock)
    # Deterministically place the ineligible order first in a one-row batch.
    first, second = sorted((deleted, later), key=str)
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(OrderModel)
            .where(OrderModel.order_id == first)
            .values(status="deleted")
        )
    transport = RecordingTransport(env, second)
    await worker(env, clock, transport).run_once(limit=1)
    assert len(transport.calls) == 1
    assert transport.calls[0].source["order_id"] == str(second)


@pytest.mark.asyncio
@pytest.mark.parametrize("loss", ["scope", "launch", "expired"])
async def test_prepared_or_queued_crash_never_constructs_a_second_attempt(
    capture_env, loss
):
    env, clock = capture_env, Clock()
    order = legacy_order(env, clock)
    transport = RecordingTransport(env, order)
    service = worker(env, clock, transport)
    request = await enqueue(service, order, env["client"])
    if loss == "scope":
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == env["client"])
                .values(status="pause")
            )
    elif loss == "launch":
        service.launch_urls = {"telegram": "http://example.test/private"}
    else:
        attempt = await service.prepare(request)
        assert attempt
        clock.at += timedelta(seconds=121)
    assert await service.prepare(request) is None
    assert await service.prepare(request) is None
    assert transport.calls == []
    with Session(env["pg"]) as db:
        assert db.scalar(select(JOBS.c.state)) == (
            "unknown" if loss == "expired" else "obsolete"
        )
        assert (
            db.scalar(
                select(OUTCOMES.c.outcome_id).where(
                    OUTCOMES.c.kind == "started"
                )
            )
            is None
        )


@pytest.mark.asyncio
async def test_stored_snapshot_tampering_and_duplicate_delivery_are_fenced(
    capture_env,
):
    env, clock = capture_env, Clock()
    order = legacy_order(env, clock)
    transport = RecordingTransport(env, order)
    service = worker(env, clock, transport)
    request = await enqueue(service, order, env["client"])
    attempt = await service.prepare(request)
    with pytest.raises(ValueError, match="digest_attempt_snapshot_invalid"):
        await service.deliver(replace(attempt, text="forged message"))
    assert transport.calls == []
    await asyncio.gather(service.deliver(attempt), service.deliver(attempt))
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_revoked_manager_never_gets_a_queued_foreign_order_digest(
    capture_env, monkeypatch
):
    from tests.postgres_financial.test_work_entitlement_runtime import (
        start_flow,
    )
    from ugc_bot.infrastructure.db.models import ManagerOrderModel

    env = capture_env
    flow = await start_flow(env, monkeypatch)
    clock = Clock()
    clock.at = flow["clock"].at
    try:
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == flow["manager"])
                .values(telegram_id="987654321")
            )
        transport = RecordingTransport(env, env["order"])
        service = worker(env, clock, transport)
        request = await enqueue(service, env["order"], flow["manager"])
        attempt = await service.prepare(request)
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                delete(ManagerOrderModel).where(
                    ManagerOrderModel.user_id == flow["manager"],
                    ManagerOrderModel.order_id == env["order"],
                )
            )
        await service.deliver(attempt)
        assert transport.calls == []
    finally:
        await flow["container"].dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("first_late", [False, True])
async def test_reused_provider_reference_is_retained_without_second_application(
    capture_env,
    first_late,
):
    env, clock = capture_env, Clock()
    order = legacy_order(env, clock)

    class Reused(RecordingTransport):
        async def send(self, attempt):
            await super().send(attempt)
            if first_late and len(self.calls) == 1:
                clock.at += timedelta(seconds=121)
                await service.run_once()
            return DeliveryReceipt(attempt.channel, "synthetic-reused-receipt")

    transport = Reused(env, order)
    service = worker(env, clock, transport)
    await service.run_once()
    clock.at += timedelta(days=7)
    await service.run_once()
    with Session(env["pg"]) as db:
        outcomes = (
            db.execute(select(OUTCOMES).where(OUTCOMES.c.kind == "transport"))
            .mappings()
            .all()
        )
        assert len(outcomes) == 2
        assert sum(o["applied"] for o in outcomes) == (0 if first_late else 1)
        assert {o["provider_reference"] for o in outcomes} == {
            "synthetic-reused-receipt"
        }


@pytest.mark.asyncio
async def test_missing_unpaid_and_empty_own_scope_have_no_send_intent(
    capture_env,
):
    from ugc_bot.infrastructure.db.models import ManagerOrderModel

    env, clock = capture_env, Clock()
    order = legacy_order(env, clock)
    own_manager = env["digest_creators"][0]
    with Session(env["pg"]) as db, db.begin():
        db.add(
            ManagerOrderModel(
                user_id=own_manager, order_id=order, created_at=clock.at
            )
        )
    repo = SqlAlchemyCampaignDigestRepository()
    transactions = SessionTransactionManager(env["factory"])
    for target, actor in (
        (uuid4(), env["client"]),
        (env["order"], env["client"]),
        (order, own_manager),
    ):
        async with transactions.transaction() as db:
            assert (
                await repo.lock_source(target, actor, clock.at, session=db)
                is None
            )
    with Session(env["pg"]) as db:
        assert db.scalar(select(REQUESTS.c.request_id)) is None

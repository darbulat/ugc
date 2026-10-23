"""Task16 behavioral capture tests against migrated PostgreSQL."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.helpers.factories import create_test_advertiser
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus
from ugc_bot.infrastructure.db.models import (
    ContactPricingModel,
    FinancialPolicyVersionModel,
    OrderItemModel,
    OrderModel,
    PaymentItemAllocationModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.orders import (
    SqlAlchemyContactPricingRepository,
    SqlAlchemyOrderRepository,
    SqlAlchemyPaymentRepository,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager


@pytest_asyncio.fixture
async def capture_env(financial_pg_engine, user_repo, advertiser_repo):
    client = await create_test_advertiser(user_repo, advertiser_repo)
    now = datetime.now(timezone.utc) - timedelta(minutes=10)
    order, version = uuid4(), str(uuid4())
    with Session(financial_pg_engine) as db, db.begin():
        db.add(
            UserModel(
                user_id=client,
                messenger_type=MessengerType.TELEGRAM,
                username="capture",
                status=UserStatus.ACTIVE,
            )
        )
        db.flush()
        db.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=client,
                approved_at=now,
                effective_from=now,
                refund_window_seconds=3600,
                rules={
                    "terms_reference": "terms:test",
                    "allowed_clients": [str(client)],
                },
            )
        )
        db.add(
            OrderModel(
                order_id=order,
                advertiser_id=client,
                product_link="test",
                offer_text="test",
                price=1,
                bloggers_needed=2,
                status=OrderStatus.NEW,
                created_at=now,
                financial_version=version,
            )
        )
        db.merge(
            ContactPricingModel(
                country_code="ru",
                bloggers_count=2,
                price=Decimal("2200"),
                currency="RUB",
            )
        )
        db.flush()
        for ordinal, accompaniment in [(1, 120000), (2, 0)]:
            db.add(
                OrderItemModel(
                    paid_item_id=uuid4(),
                    order_id=order,
                    ordinal=ordinal,
                    currency="RUB",
                    selection_minor=50000,
                    accompaniment_minor=accompaniment,
                    policy_version=version,
                    selection_due_at=now + timedelta(days=3),
                    quote_key="capture-quote",
                    quote_payload={
                        "client_id": str(client),
                        "terms_reference": "terms:test",
                    },
                )
            )
    engine = create_async_engine(
        financial_pg_engine.url, pool_size=1, max_overflow=0
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = PaymentService(
        user_repo,
        advertiser_repo,
        SqlAlchemyOrderRepository(factory),
        SqlAlchemyPaymentRepository(factory),
        SqlAlchemyContactPricingRepository(factory),
        transaction_manager=SessionTransactionManager(factory),
    )
    from ugc_bot.application.services.financial_policy_service import (
        FinancialPolicyService,
    )
    from ugc_bot.config import FinancialConfig
    from ugc_bot.infrastructure.db.repositories.financial_capture import (
        SqlAlchemyFinancialCaptureRepository,
    )

    service.capture_repository = SqlAlchemyFinancialCaptureRepository(
        FinancialPolicyService(
            FinancialConfig(
                FINANCIAL_CORE_ENABLED=True, FINANCIAL_NEW_ORDERS_ENABLED=True
            )
        )
    )
    service.capture_account = "test-merchant"
    async with factory.begin() as session:
        await service.capture_repository.issue(
            order, client, service.capture_account, session=session
        )
    try:
        yield dict(
            service=service,
            factory=factory,
            client=client,
            order=order,
            now=now,
            version=version,
            pg=financial_pg_engine,
        )
    finally:
        await engine.dispose()


def telegram_receipt(env, **changes):
    from aiogram.types import Message

    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    payload = dict(
        message_id=1,
        date=int((env["now"] + timedelta(minutes=1)).timestamp()),
        chat={"id": 123, "type": "private"},
        from_user={"id": 123, "is_bot": False, "first_name": "Synthetic"},
        successful_payment=dict(
            currency="RUB",
            total_amount=220000,
            invoice_payload=str(env["order"]),
            telegram_payment_charge_id="tg-" + str(env["order"]),
            provider_payment_charge_id="provider-" + str(env["order"]),
        ),
    )
    payload["successful_payment"].update(changes)
    receipt = (
        TelegramEventAdapter()
        .from_message(Message.model_validate(payload))
        .successful_payment
    )
    assert receipt is not None
    return receipt


@pytest.mark.asyncio
async def test_v1_capture_allocations_are_atomic(capture_env):
    env = capture_env
    receipt = telegram_receipt(env)
    assert receipt.protocol_message_at == datetime.fromtimestamp(
        int((env["now"] + timedelta(minutes=1)).timestamp()), timezone.utc
    )
    assert receipt.telegram_payment_charge_id == "tg-" + str(env["order"])
    payment = await env["service"].confirm_telegram_payment(
        env["client"],
        env["order"],
        receipt.provider_payment_charge_id,
        220000,
        "RUB",
        receipt=receipt,
    )
    with Session(env["pg"]) as db:
        allocations = db.scalars(
            select(PaymentItemAllocationModel).where(
                PaymentItemAllocationModel.payment_id == payment.payment_id
            )
        ).all()
        assert len(allocations) == 3, (
            "v1 capture must persist exact quote component allocations"
        )
        assert sum(a.amount_minor for a in allocations) == 220000
        assert db.get(PaymentModel, payment.payment_id).captured_minor == 220000
        from ugc_bot.infrastructure.db.models import OutboxEventModel

        events = db.scalars(
            select(OutboxEventModel).where(
                OutboxEventModel.aggregate_id == str(env["order"]),
                OutboxEventModel.event_type
                == "financial.client_snapshot_requested",
            )
        ).all()
        assert len(events) == 1
        assert (
            events[0].payload["capture"]["captured_at_source"]
            == "telegram.message.date"
        )
        assert payment.paid_at == receipt.protocol_message_at
        assert all(
            i.captured_at == receipt.protocol_message_at
            and i.selection_state == "paid"
            for i in db.scalars(
                select(OrderItemModel).where(
                    OrderItemModel.order_id == env["order"]
                )
            )
        )


@pytest.mark.asyncio
async def test_payment_admin_rejects_v1_create_and_edit(capture_env):
    from starlette.requests import Request

    from ugc_bot.admin.app import PaymentAdmin
    from ugc_bot.application.errors import OrderCreationError

    env = capture_env
    view = PaymentAdmin()
    view.session_maker = env["factory"]
    view.is_async = True
    request = Request({"type": "http"})
    with Session(env["pg"]) as db:
        payment = db.scalar(
            select(PaymentModel).where(PaymentModel.order_id == env["order"])
        )
        pk = str(payment.payment_id)
    for action in ["edit", "create"]:
        if action == "create":
            with Session(env["pg"]) as db, db.begin():
                db.delete(db.get(PaymentModel, payment.payment_id))
        with pytest.raises(
            OrderCreationError, match="v1_payment_admin_forbidden"
        ):
            if action == "create":
                await view.insert_model(
                    request,
                    {
                        "order": str(env["order"]),
                        "amount": 1,
                        "provider": "manual",
                        "currency": "RUB",
                        "status": "paid",
                        "external_id": "admin-write",
                    },
                )
            else:
                await view.update_model(request, pk, {"amount": 1})


@pytest.mark.asyncio
async def test_v1_invoice_service_uses_durable_quote_not_current_tariff(
    capture_env,
):
    from ugc_bot.config import AppConfig

    env = capture_env
    with Session(env["pg"]) as db, db.begin():
        db.get(ContactPricingModel, ("ru", 2)).price = Decimal("999999")
    order = await env["service"].get_order(env["order"])
    result = await env["service"].calculate_invoice_data(
        order, "ru", AppConfig()
    )
    assert result.total == Decimal("2200")
    assert result.currency == "RUB"


@pytest.mark.asyncio
async def test_financial_outbox_is_not_claimed_by_legacy_order_worker(
    capture_env,
):
    from ugc_bot.infrastructure.db.repositories.outbox import (
        SqlAlchemyOutboxRepository,
    )

    env = capture_env
    receipt = telegram_receipt(env)
    await env["service"].confirm_telegram_payment(
        env["client"],
        env["order"],
        receipt.provider_payment_charge_id,
        receipt.total_amount,
        receipt.currency,
        receipt=receipt,
    )
    claimed = await SqlAlchemyOutboxRepository(
        env["factory"]
    ).claim_pending_events(limit=1000)
    assert not any(
        e.event_type
        in ("financial.capture_intent", "financial.client_snapshot_requested")
        for e in claimed
    ), "new consumer work must remain pending"


@pytest.mark.asyncio
async def test_capture_identity_survives_outbox_retention(capture_env):
    from ugc_bot.domain.enums import OutboxEventStatus
    from ugc_bot.infrastructure.db.models import OutboxEventModel
    from ugc_bot.infrastructure.db.repositories.outbox import (
        SqlAlchemyOutboxRepository,
    )

    env = capture_env
    receipt = telegram_receipt(env)
    assert receipt.protocol_message_at == datetime.fromtimestamp(
        int((env["now"] + timedelta(minutes=1)).timestamp()), timezone.utc
    )
    assert receipt.telegram_payment_charge_id == "tg-" + str(env["order"])
    payment = await env["service"].confirm_telegram_payment(
        env["client"],
        env["order"],
        receipt.provider_payment_charge_id,
        receipt.total_amount,
        receipt.currency,
        receipt=receipt,
    )
    with Session(env["pg"]) as db, db.begin():
        for event in db.scalars(
            select(OutboxEventModel).where(
                OutboxEventModel.aggregate_id == str(env["order"])
            )
        ):
            event.status = OutboxEventStatus.PUBLISHED
            event.processed_at = env["now"] - timedelta(days=100)
    await SqlAlchemyOutboxRepository(env["factory"]).delete_processed_events(
        7, 1000
    )
    with Session(env["pg"]) as db:
        assert (
            len(
                db.scalars(
                    select(OutboxEventModel).where(
                        OutboxEventModel.aggregate_id == str(env["order"])
                    )
                ).all()
            )
            == 2
        ), "financial identity must outlive delivery retention"
    assert (
        await env["service"].confirm_telegram_payment(
            env["client"],
            env["order"],
            receipt.provider_payment_charge_id,
            receipt.total_amount,
            receipt.currency,
            receipt=receipt,
        )
        == payment
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        "amount",
        "currency",
        "owner",
        "time",
        "charge",
        "provider",
        "account",
        "untrusted",
    ],
)
async def test_invalid_capture_does_not_mutate_money(
    capture_env, user_repo, advertiser_repo, bad
):
    from dataclasses import replace

    from ugc_bot.application.errors import OrderCreationError

    env = capture_env
    receipt = telegram_receipt(env)
    client = env["client"]
    if bad == "amount":
        receipt = replace(receipt, total_amount=219999)
    if bad == "currency":
        receipt = replace(receipt, currency="USD")
    if bad == "owner":
        client = await create_test_advertiser(
            user_repo, advertiser_repo, external_id="attacker"
        )
    if bad == "time":
        receipt = replace(receipt, protocol_message_at=None)
    if bad == "charge":
        receipt = replace(receipt, telegram_payment_charge_id=None)
    if bad == "account":
        env["service"].capture_account = "other-merchant"
    if bad == "provider":
        with Session(env["pg"]) as db, db.begin():
            db.scalar(
                select(PaymentModel).where(
                    PaymentModel.order_id == env["order"]
                )
            ).provider = "unsupported"
    with pytest.raises(OrderCreationError):
        await env["service"].confirm_telegram_payment(
            client,
            env["order"],
            receipt.provider_payment_charge_id,
            receipt.total_amount,
            receipt.currency,
            receipt=None if bad == "untrusted" else receipt,
        )
    with Session(env["pg"]) as db:
        payment = db.scalar(
            select(PaymentModel).where(PaymentModel.order_id == env["order"])
        )
        assert payment.captured_minor is None
        assert not db.scalars(
            select(PaymentItemAllocationModel).where(
                PaymentItemAllocationModel.order_id == env["order"]
            )
        ).all()
        assert all(
            i.captured_at is None
            for i in db.scalars(
                select(OrderItemModel).where(
                    OrderItemModel.order_id == env["order"]
                )
            )
        )
        assert db.get(OrderModel, env["order"]).status == OrderStatus.NEW


@pytest.mark.asyncio
async def test_rollback_after_real_partial_allocation_flush(capture_env):
    from ugc_bot.infrastructure.db.repositories.payment_allocations import (
        SqlAlchemyPaymentAllocationRepository,
    )

    env = capture_env
    receipt = telegram_receipt(env)
    observed = []

    class FailAfterFlush(SqlAlchemyPaymentAllocationRepository):
        async def add(self, allocation, *, session):
            await super().add(allocation, session=session)
            assert (
                await session.get(
                    PaymentItemAllocationModel, allocation.allocation_key
                )
                is not None
            )
            assert (
                await session.get(PaymentModel, allocation.payment_id)
            ).captured_minor == 220000
            assert (
                await session.get(OrderItemModel, allocation.paid_item_id)
            ).captured_at is not None
            observed.append(allocation.amount_minor)
            raise RuntimeError("failure after actual allocation flush")

    repo = env["service"].capture_repository
    repo.allocations = FailAfterFlush()
    with pytest.raises(RuntimeError, match="actual allocation flush"):
        await env["service"].confirm_telegram_payment(
            env["client"],
            env["order"],
            receipt.provider_payment_charge_id,
            receipt.total_amount,
            receipt.currency,
            receipt=receipt,
        )
    assert observed == [50000]
    with Session(env["pg"]) as db:
        assert (
            db.scalar(
                select(PaymentModel).where(
                    PaymentModel.order_id == env["order"]
                )
            ).captured_minor
            is None
        )
        assert not db.scalars(
            select(PaymentItemAllocationModel).where(
                PaymentItemAllocationModel.order_id == env["order"]
            )
        ).all()
        assert all(
            i.captured_at is None
            for i in db.scalars(
                select(OrderItemModel).where(
                    OrderItemModel.order_id == env["order"]
                )
            )
        )
        from ugc_bot.infrastructure.db.models import OutboxEventModel

        assert not db.scalars(
            select(OutboxEventModel).where(
                OutboxEventModel.aggregate_id == str(env["order"]),
                OutboxEventModel.event_type
                == "financial.client_snapshot_requested",
            )
        ).all()
    repo.allocations = SqlAlchemyPaymentAllocationRepository()
    assert (
        await env["service"].confirm_telegram_payment(
            env["client"],
            env["order"],
            receipt.provider_payment_charge_id,
            receipt.total_amount,
            receipt.currency,
            receipt=receipt,
        )
    ).paid_at == receipt.protocol_message_at


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", [False, True, "other_account"])
async def test_independent_postgres_capture_races(capture_env, conflict):
    import asyncio
    from contextlib import asynccontextmanager
    from dataclasses import replace

    from sqlalchemy import text

    from ugc_bot.application.errors import OrderCreationError

    env = capture_env
    second_order = env["order"]
    if conflict:
        second_order = uuid4()
        with Session(env["pg"]) as db, db.begin():
            db.add(
                OrderModel(
                    order_id=second_order,
                    advertiser_id=env["client"],
                    product_link="test",
                    offer_text="test",
                    price=1,
                    bloggers_needed=2,
                    status=OrderStatus.NEW,
                    created_at=env["now"],
                    financial_version=env["version"],
                )
            )
            db.flush()
            for row in db.scalars(
                select(OrderItemModel).where(
                    OrderItemModel.order_id == env["order"]
                )
            ).all():
                db.add(
                    OrderItemModel(
                        paid_item_id=uuid4(),
                        order_id=second_order,
                        ordinal=row.ordinal,
                        currency=row.currency,
                        selection_minor=row.selection_minor,
                        accompaniment_minor=row.accompaniment_minor,
                        policy_version=row.policy_version,
                        selection_due_at=row.selection_due_at,
                        quote_key=row.quote_key,
                        quote_payload=row.quote_payload,
                    )
                )
        async with env["factory"].begin() as db:
            await env["service"].capture_repository.issue(
                second_order,
                env["client"],
                "other-merchant"
                if conflict == "other_account"
                else env["service"].capture_account,
                session=db,
            )
    engine2 = create_async_engine(env["pg"].url, pool_size=1, max_overflow=0)
    factory2 = async_sessionmaker(engine2, expire_on_commit=False)
    pids = []
    ready = asyncio.Event()

    class ConcurrentTransaction:
        def __init__(self, factory):
            self.factory = factory

        @asynccontextmanager
        async def transaction(self):
            async with self.factory.begin() as session:
                pids.append(
                    await session.scalar(text("select pg_backend_pid()"))
                )
                if len(pids) == 2:
                    ready.set()
                await asyncio.wait_for(ready.wait(), 10)
                yield session

    first = replace(
        env["service"],
        transaction_manager=ConcurrentTransaction(env["factory"]),
    )
    second = replace(
        env["service"], transaction_manager=ConcurrentTransaction(factory2)
    )
    if conflict == "other_account":
        second.capture_account = "other-merchant"
    receipt = telegram_receipt(env)
    receipt2 = telegram_receipt(
        dict(env, order=second_order),
        provider_payment_charge_id=receipt.provider_payment_charge_id,
    )

    async def call(service, order, capture):
        return await service.confirm_telegram_payment(
            env["client"],
            order,
            capture.provider_payment_charge_id,
            capture.total_amount,
            capture.currency,
            receipt=capture,
        )

    try:
        if conflict == "other_account":
            ready.set()
            results = [
                await call(first, env["order"], receipt),
                await call(second, second_order, receipt2),
            ]
        else:
            results = await asyncio.gather(
                call(first, env["order"], receipt),
                call(second, second_order, receipt2),
                return_exceptions=True,
            )
        assert len(set(pids)) == 2, (
            "must exercise independent PostgreSQL backends"
        )
        if conflict == "other_account":
            assert not any(isinstance(r, Exception) for r in results), results
        elif conflict:
            assert sum(isinstance(r, OrderCreationError) for r in results) == 1
            assert sum(isinstance(r, Exception) for r in results) == 1
        else:
            assert results[0] == results[1]
            assert not isinstance(results[0], Exception)
        with Session(env["pg"]) as db:
            rows = db.scalars(
                select(PaymentItemAllocationModel).where(
                    PaymentItemAllocationModel.order_id.in_(
                        [env["order"], second_order]
                    )
                )
            ).all()
            assert len(rows) == (6 if conflict == "other_account" else 3)
            assert sum(r.amount_minor for r in rows) == (
                440000 if conflict == "other_account" else 220000
            )
            order = db.get(OrderModel, env["order"])
            order.status = OrderStatus.CLOSED
            db.commit()
        # Order status changes must not change the receipt.
        if not conflict:
            assert (
                await env["service"].confirm_telegram_payment(
                    env["client"],
                    env["order"],
                    receipt.provider_payment_charge_id,
                    receipt.total_amount,
                    receipt.currency,
                    receipt=receipt,
                )
                == results[0]
            )
    finally:
        await engine2.dispose()


@pytest.mark.asyncio
async def test_capture_waits_on_quote_order_row_lock(capture_env):
    import asyncio
    from contextlib import asynccontextmanager
    from dataclasses import replace

    from sqlalchemy import text

    from ugc_bot.application.services.paid_item_service import build_quote
    from ugc_bot.infrastructure.db.repositories.financial_items import (
        SqlAlchemyFinancialItemRepository,
    )

    env = capture_env
    engine2 = create_async_engine(env["pg"].url, pool_size=1, max_overflow=0)
    factory2 = async_sessionmaker(engine2, expire_on_commit=False)
    entered = asyncio.Event()
    pids = []

    class ObservedTransaction:
        @asynccontextmanager
        async def transaction(self):
            async with env["factory"].begin() as session:
                pids.append(
                    await session.scalar(text("select pg_backend_pid()"))
                )
                entered.set()
                yield session

    service = replace(env["service"], transaction_manager=ObservedTransaction())
    receipt = telegram_receipt(env)
    task = None
    try:
        async with factory2.begin() as locker:
            blocker = await locker.scalar(text("select pg_backend_pid()"))
            await locker.scalar(
                select(OrderModel)
                .where(OrderModel.order_id == env["order"])
                .with_for_update()
            )
            # Actual quote writer shares the exact order row lock and freezes
            # the already-issued invoice, rather than changing its components.
            quote = build_quote(
                order_id=env["order"],
                count=2,
                accompaniment_ordinals=frozenset({2}),
                currency="RUB",
                policy_version=env["version"],
                selection_due_at=env["now"] + timedelta(days=2),
                client_contact_reference="test",
                terms_reference="terms:test",
                idempotency_key="reprice",
            )
            with pytest.raises(
                ValueError, match="issued_payment_quote_immutable"
            ):
                await SqlAlchemyFinancialItemRepository().save_quote(
                    quote, session=locker
                )
            task = asyncio.create_task(
                service.confirm_telegram_payment(
                    env["client"],
                    env["order"],
                    receipt.provider_payment_charge_id,
                    receipt.total_amount,
                    receipt.currency,
                    receipt=receipt,
                )
            )
            await asyncio.wait_for(entered.wait(), 10)
            assert pids[0] != blocker
            for _ in range(200):
                with Session(env["pg"]) as observer:
                    blocked = observer.scalar(
                        text("select :blocker = ANY(pg_blocking_pids(:pid))"),
                        {"blocker": blocker, "pid": pids[0]},
                    )
                if blocked:
                    break
                await asyncio.sleep(0.01)
            assert blocked, (
                "capture must wait on the actual quote order FOR UPDATE lock"
            )
            assert not task.done()
        payment = await asyncio.wait_for(task, 10)
        assert payment.paid_at == receipt.protocol_message_at
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await engine2.dispose()


@pytest.mark.asyncio
async def test_conflicting_replays_do_not_add_allocations(capture_env):
    from dataclasses import replace

    from ugc_bot.application.errors import OrderCreationError

    env = capture_env
    receipt = telegram_receipt(env)
    payment = await env["service"].confirm_telegram_payment(
        env["client"],
        env["order"],
        receipt.provider_payment_charge_id,
        receipt.total_amount,
        receipt.currency,
        receipt=receipt,
    )
    for changed in [
        replace(receipt, total_amount=1),
        replace(receipt, currency="USD"),
        replace(receipt, provider_payment_charge_id="different-charge"),
        replace(
            receipt, telegram_payment_charge_id="different-telegram-charge"
        ),
        replace(
            receipt,
            protocol_message_at=receipt.protocol_message_at
            + timedelta(seconds=1),
        ),
    ]:
        with pytest.raises(OrderCreationError):
            await env["service"].confirm_telegram_payment(
                env["client"],
                env["order"],
                changed.provider_payment_charge_id,
                changed.total_amount,
                changed.currency,
                receipt=changed,
            )
    with Session(env["pg"]) as db:
        rows = db.scalars(
            select(PaymentItemAllocationModel).where(
                PaymentItemAllocationModel.payment_id == payment.payment_id
            )
        ).all()
        assert len(rows) == 3 and sum(r.amount_minor for r in rows) == 220000
        assert (
            db.get(PaymentModel, payment.payment_id).paid_at
            == receipt.protocol_message_at
        )


@pytest.mark.asyncio
async def test_failed_payment_is_not_new_captured_value(capture_env):
    from ugc_bot.application.errors import OrderCreationError
    from ugc_bot.domain.enums import PaymentStatus

    env = capture_env
    receipt = telegram_receipt(env)
    with Session(env["pg"]) as db, db.begin():
        payment = db.scalar(
            select(PaymentModel).where(PaymentModel.order_id == env["order"])
        )
        payment.status = PaymentStatus.FAILED
    with pytest.raises(OrderCreationError, match="capture_payment_conflict"):
        await env["service"].confirm_telegram_payment(
            env["client"],
            env["order"],
            receipt.provider_payment_charge_id,
            receipt.total_amount,
            receipt.currency,
            receipt=receipt,
        )
    with Session(env["pg"]) as db:
        assert not db.scalars(
            select(PaymentItemAllocationModel).where(
                PaymentItemAllocationModel.order_id == env["order"]
            )
        ).all()
        assert all(
            i.captured_at is None
            for i in db.scalars(
                select(OrderItemModel).where(
                    OrderItemModel.order_id == env["order"]
                )
            )
        )

"""The two production durable queues share one owner for paid admin cards."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.helpers.fakes import FakeCallback, FakeUser
from tests.postgres_financial.test_checkout_runtime import (
    checkout_env as _checkout_env,
)
from ugc_bot.application.notice_delivery_ports import DeliveryReceipt
from ugc_bot.application.services.checkout_paid_notices import (
    PaidNoticeDelivery,
)
from ugc_bot.application.services.checkout_paid_receipts import (
    PaidReceiptProcessor,
)
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.bot.telegram.handlers.admin_moderation import (
    handle_moderate_activate,
)
from ugc_bot.container.checkout_factory import build_checkout_service
from ugc_bot.container.order_notice_factory import build_order_notice_delivery
from ugc_bot.domain.checkout import NativePaidReceipt
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.infrastructure.db.checkout_models import NOTICE_JOBS
from ugc_bot.infrastructure.db.models import OutboxEventModel
from ugc_bot.infrastructure.db.order_notice_models import (
    ORDER_NOTICE_DELIVERIES,
)
from ugc_bot.infrastructure.db.repositories.order_notices import (
    SqlAlchemyOrderNoticeRepository,
)


@pytest_asyncio.fixture
async def checkout_env(financial_pg_engine):
    async for env in _checkout_env.__wrapped__(financial_pg_engine):
        yield env


@pytest.mark.asyncio
async def test_paid_order_notifies_once_and_activates_only_after_capture(
    checkout_env,
):
    env = checkout_env
    config = env["config"].model_copy(
        update={
            "admin": env["config"].admin.model_copy(
                update={"admin_base_url": "https://admin.example.test"}
            )
        }
    )
    services = env["container"].build_bot_services()

    async def activate():
        callback = FakeCallback(
            data=f"mod_activate:{env['order'].order_id.hex}",
            user=FakeUser(int(env["admin"].telegram_id), "admin"),
        )
        await handle_moderate_activate(
            callback,
            user_role_service=services["user_role_service"],
            content_moderation_service=ContentModerationService(),
            order_repo=env["repos"]["order_repo"],
            outbox_publisher=services["outbox_publisher"],
            transaction_manager=env["container"].transaction_manager,
            payment_repo=env["repos"]["payment_repo"],
        )
        return callback.answers

    assert await activate() == ["Заказ уже обработан."]
    assert (
        await env["repos"]["order_repo"].get_by_id(env["order"].order_id)
    ).status == OrderStatus.NEW
    # Use the production factory's ownership setting with the fixture gateway.
    checkout = build_checkout_service(config, env["transactions"])
    assert checkout.repository.admin_notices_enabled is False
    checkout = replace(checkout, gateway=env["gateway"])
    await checkout.request_invoice(
        env["order"].order_id, env["actor"], "runtime-dedup"
    )
    paid = NativePaidReceipt(
        env["actor"].external_id,
        "chat",
        "message",
        env["order"].order_id,
        "runtime-provider",
        "runtime-tg",
        1740000,
        "RUB",
        datetime.now(timezone.utc),
    )
    async with env["transactions"].transaction() as session:
        await checkout.repository.accept_receipt(paid, session=session)
    payment = replace(
        services["payment_service"],
        capture_repository=checkout.repository.capture,
        capture_account=config.bot.telegram_payment_account_id,
    )
    processor = PaidReceiptProcessor(
        checkout.repository, env["transactions"], payment
    )
    assert await processor.run_once()
    with Session(env["pg"]) as db:
        pending = (
            db.execute(
                select(NOTICE_JOBS).where(
                    NOTICE_JOBS.c.order_id == env["order"].order_id
                )
            )
            .mappings()
            .all()
        )
    assert len(pending) == 1 and pending[0]["kind"] == "client"
    receipt = SimpleNamespace(
        send=AsyncMock(
            return_value=DeliveryReceipt("telegram", "synthetic:receipt")
        )
    )
    client_delivery = PaidNoticeDelivery(
        checkout.repository, env["transactions"], receipt
    )
    assert await client_delivery.run_once()
    assert not await client_delivery.run_once()
    assert receipt.send.await_count == 1
    messenger = AsyncMock()
    notices = build_order_notice_delivery(
        config, env["transactions"], messenger, env["repos"]
    )
    for _ in range(100):
        if not await notices.run_once():
            break
    # Created + paid admin events are distinct; checkout sends only the receipt.
    assert messenger.send_text.await_count == 2
    cards = [call.kwargs for call in messenger.send_text.await_args_list]
    created = next(card for card in cards if "Новый заказ" in card["text"])
    paid_card = next(card for card in cards if "Заказ оплачен" in card["text"])
    assert (
        created["chat_id"] == paid_card["chat_id"] == env["admin"].telegram_id
    )
    created_buttons = [
        button for row in created["keyboard"].rows for button in row
    ]
    paid_buttons = [
        button for row in paid_card["keyboard"].rows for button in row
    ]
    callback_data = f"mod_activate:{env['order'].order_id.hex}"
    assert not any(
        button.callback_data == callback_data for button in created_buttons
    )
    assert any(button.callback_data == callback_data for button in paid_buttons)
    assert any(
        button.url
        == f"https://admin.example.test/admin/order-model/edit/{env['order'].order_id}"
        for button in paid_buttons
    )
    assert not await processor.run_once()
    assert not await notices.run_once()
    assert await activate() == ["Заказ активирован, уходит блогерам."]
    assert await activate() == ["Заказ уже обработан."]
    view = await services["client_order_view_service"].list(env["user"].user_id)
    order = next(
        row
        for row in view["orders"]
        if row["order_id"] == str(env["order"].order_id)
    )
    assert order["status"] == "active"
    assert order["customer_status"] == "selecting"
    assert order["payment_state"] == "paid"
    with Session(env["pg"]) as db:
        events = db.scalars(
            select(OutboxEventModel).where(
                OutboxEventModel.aggregate_id == str(env["order"].order_id),
                OutboxEventModel.event_type == "order.activated",
            )
        ).all()
        assert len(events) == 1


@pytest.mark.asyncio
async def test_postgres_notice_leases_recover_without_resending_unknown(
    checkout_env,
):
    env = checkout_env
    repo = SqlAlchemyOrderNoticeRepository()
    start = datetime.now(timezone.utc)
    async with env["transactions"].transaction() as session:
        first = await repo.claim(start, ("123",), "", session=session)
        assert first is not None
    async with env["transactions"].transaction() as session:
        assert (
            await repo.claim(
                start + timedelta(minutes=2, seconds=1),
                ("123",),
                "",
                session=session,
            )
            is None
        )
    async with env["transactions"].transaction() as session:
        second = await repo.claim(
            start + timedelta(minutes=3), ("123",), "", session=session
        )
        assert second is not None and second.attempt == 2
        assert second.job_id == first.job_id
        assert not await repo.begin(
            first, start + timedelta(minutes=3), session=session
        )
        assert await repo.begin(
            second, start + timedelta(minutes=3), session=session
        )
    async with env["transactions"].transaction() as session:
        assert (
            await repo.claim(
                start + timedelta(minutes=6), ("123",), "", session=session
            )
            is None
        )
        state = (
            await session.execute(
                select(ORDER_NOTICE_DELIVERIES.c.state).where(
                    ORDER_NOTICE_DELIVERIES.c.job_id == first.job_id
                )
            )
        ).scalar_one()
        assert state == "unknown"

"""Saved counteroffers produce private Telegram notices with live positions."""

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from tests.helpers.factories import create_test_order, create_test_user
from tests.postgres_financial.test_paid_selection_interest import (
    capture,
    seed_creators,
    service,
)
from tests.postgres_financial.test_v1_capture import capture_env as _capture_env
from ugc_bot import counteroffer_admin_delivery as delivery
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.domain.counteroffer import COUNTEROFFER_SUBMITTED
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    OutboxEventStatus,
    RejectionReason,
)
from ugc_bot.infrastructure.db.models import (
    OfferDispatchModel,
    OrderModel,
    OutboxEventModel,
    UserModel,
)

capture_env = _capture_env


@pytest.mark.asyncio
async def test_counteroffer_worker_delivers_only_to_kamil_after_order_closed(
    capture_env, monkeypatch
):
    env = capture_env
    placed, offered_price, without_offer = seed_creators(env)
    await capture(env)
    await service(env).respond(env["order"], placed)
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": env["pg"].url.render_as_string(hide_password=False),
            "ADMIN_BASE_URL": "https://admin.example.test/admin",
            "USE_REDIS_STORAGE": False,
            "KAFKA_ENABLED": False,
        }
    )
    container = Container(config)
    repos = container.build_repos()
    transactions = container.transaction_manager
    dispatch = container.build_bot_services()["offer_dispatch_service"]
    try:
        target, _ = await asyncio.gather(
            *(
                create_test_user(
                    repos["user_repo"],
                    external_id=str(uuid4().int % 10**12 + 1),
                    telegram=handle,
                    admin=True,
                )
                for handle in ("KamilBakhteev", "other_admin")
            )
        )
        async with transactions.transaction() as db:
            await db.execute(
                update(OrderModel)
                .where(OrderModel.order_id == env["order"])
                .values(status=OrderStatus.CLOSED)
            )
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == offered_price)
                .values(username="Автор", telegram="creator_example")
            )
            # The current assignment counts even if the legacy flag is clear.
            await db.execute(
                update(OfferDispatchModel)
                .where(
                    OfferDispatchModel.order_id == env["order"],
                    OfferDispatchModel.blogger_id == placed,
                )
                .values(in_offer=False)
            )
        await dispatch.record_offer_sent(
            env["order"], offered_price, channel=MessengerType.TELEGRAM
        )
        contenders = await asyncio.gather(
            *(
                dispatch.record_skip(
                    env["order"],
                    offered_price,
                    RejectionReason.LOW_PRICE,
                    Decimal("5.50"),
                    channel=channel,
                )
                for channel in (MessengerType.TELEGRAM, MessengerType.MAX)
            )
        )
        assert sorted(
            result.desired_price is not None for result in contenders
        ) == [False, True]
        bogus = await dispatch.record_skip(
            env["order"],
            without_offer,
            RejectionReason.LOW_PRICE,
            Decimal("5.50"),
        )
        assert bogus.desired_price is None

        bot = AsyncMock()
        bot.send_message.return_value = SimpleNamespace(
            message_id=12, chat=SimpleNamespace(id=int(target.telegram_id))
        )

        @asynccontextmanager
        async def bot_context():
            yield bot

        def make_bot(*, token):
            assert token == "test-token"
            return SimpleNamespace(context=bot_context)

        monkeypatch.setattr(delivery, "Bot", make_bot)
        notifier = delivery.CounterofferAdminDelivery(config)
        worker = OutboxPublisher(
            repos["outbox_repo"],
            repos["order_repo"],
            transactions,
            counteroffer_notifier=notifier,
        )

        def args():
            return bot.send_message.call_args.kwargs

        await worker.process_pending_events(None)
        await worker.process_pending_events(None)
        bot.send_message.assert_awaited_once()
        assert args()["chat_id"] == int(target.telegram_id)
        assert "Автор · @creator_example" in args()["text"]
        assert "Просит 5,50 ₽ (в оффере 1 ₽)" in args()["text"]
        assert "Занято 1 из 2 · Осталось 1" in args()["text"]
        assert "Закрыт" in args()["text"]
        button = args()["reply_markup"].inline_keyboard[0][0]
        assert button.text == "Открыть заказ"
        assert (
            button.url
            == f"https://admin.example.test/admin/orders/{env['order']}"
        )

        legacy = await create_test_order(
            repos["order_repo"], env["client"], status=OrderStatus.ACTIVE
        )
        await dispatch.record_offer_sent(
            legacy.order_id, offered_price, channel=MessengerType.MAX
        )
        await dispatch.record_skip(
            legacy.order_id,
            offered_price,
            RejectionReason.LOW_PRICE,
            Decimal(3000),
            channel=MessengerType.MAX,
        )
        bot.send_message.side_effect = TimeoutError
        await worker.process_pending_events(None)
        await worker.process_pending_events(None)
        assert bot.send_message.await_count == 2
        assert args()["chat_id"] == int(target.telegram_id)
        assert "Занято 0 из 3 · Осталось 3" in args()["text"]

        async with transactions.transaction() as db:
            events = (
                await db.scalars(
                    select(OutboxEventModel)
                    .where(
                        OutboxEventModel.event_type == COUNTEROFFER_SUBMITTED
                    )
                    .order_by(OutboxEventModel.created_at)
                )
            ).all()
            assert [event.status for event in events] == [
                OutboxEventStatus.PUBLISHED,
                OutboxEventStatus.FAILED,
            ]
            assert events[-1].last_error == "telegram_result_unknown"
    finally:
        await container.dispose()

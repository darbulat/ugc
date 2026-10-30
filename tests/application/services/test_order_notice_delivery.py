"""Durable order delivery does not repeat accepted or uncertain sends."""

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_order_notice_queue_keeps_one_card_per_recipient_event():
    from ugc_bot.application.services.order_notice_delivery import (
        OrderNoticeDelivery,
    )
    from ugc_bot.infrastructure.db.order_notice_models import metadata
    from ugc_bot.infrastructure.db.repositories.order_notices import (
        SqlAlchemyOrderNoticeRepository,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    factory = async_sessionmaker(engine)

    class Transactions:
        @asynccontextmanager
        async def transaction(self):
            async with factory.begin() as session:
                yield session

    tm = Transactions()
    repo = SqlAlchemyOrderNoticeRepository()
    order_id = uuid4()
    async with tm.transaction() as session:
        for kind in ("created", "created", "paid", "paid"):
            await repo.enqueue(order_id, kind, session=session)
    sent = []

    async def send(job):
        sent.append((job.order_id, job.event_kind, job.recipient))

    async def recipients():
        return ("123", "123")

    worker = OrderNoticeDelivery(repo, tm, send, recipients, "123")
    for _ in range(4):
        await worker.run_once()
    assert sorted((kind, address) for _, kind, address in sent) == [
        ("created", "123"),
        ("paid", "123"),
    ]
    await engine.dispose()


@pytest.mark.asyncio
async def test_uncertain_order_notice_failure_is_retained_without_resending():
    from sqlalchemy import select

    from ugc_bot.application.services.order_notice_delivery import (
        OrderNoticeDelivery,
    )
    from ugc_bot.infrastructure.db.order_notice_models import (
        ORDER_NOTICE_DELIVERIES,
        metadata,
    )
    from ugc_bot.infrastructure.db.repositories.order_notices import (
        SqlAlchemyOrderNoticeRepository,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    factory = async_sessionmaker(engine)

    class Transactions:
        active = False

        @asynccontextmanager
        async def transaction(self):
            async with factory.begin() as session:
                self.active = True
                try:
                    yield session
                finally:
                    self.active = False

    tm = Transactions()
    repo = SqlAlchemyOrderNoticeRepository()
    async with tm.transaction() as session:
        await repo.enqueue(uuid4(), "paid", session=session)
    attempts = []

    async def send(job):
        assert not tm.active
        attempts.append(job)
        raise TimeoutError("provider may have accepted")

    async def recipients():
        return ("123",)

    worker = OrderNoticeDelivery(repo, tm, send, recipients)
    await worker.run_once()
    await worker.run_once()
    assert len(attempts) == 1
    async with tm.transaction() as session:
        state = (
            await session.execute(select(ORDER_NOTICE_DELIVERIES.c.state))
        ).scalar_one()
    assert state == "unknown"
    await engine.dispose()


@pytest.mark.asyncio
async def test_order_card_preparation_retry_and_send_uncertainty(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from ugc_bot.application.notice_delivery_ports import DeliveryFailure
    from ugc_bot.application.order_notice_ports import OrderNoticeJob
    from ugc_bot.config import AppConfig
    from ugc_bot.container import order_notice_factory

    config = AppConfig.model_validate(
        {"BOT_TOKEN": "synthetic", "KAFKA_ENABLED": False}
    )
    order = SimpleNamespace(advertiser_id=uuid4())
    repos = {
        "user_repo": AsyncMock(),
        "order_repo": AsyncMock(),
        "advertiser_repo": AsyncMock(),
    }
    repos["order_repo"].get_by_id.return_value = order
    repos["advertiser_repo"].get_by_user_id.return_value = None
    job = OrderNoticeJob(uuid4(), uuid4(), "created", "123", 1)
    messenger = AsyncMock()

    class Transactions:
        @asynccontextmanager
        async def transaction(self):
            yield object()

    worker = order_notice_factory.build_order_notice_delivery(
        config, Transactions(), messenger, repos
    )
    worker.repository.begin = AsyncMock(return_value=True)
    monkeypatch.setattr(
        order_notice_factory.UserRoleService,
        "list_admins",
        AsyncMock(
            return_value=[SimpleNamespace(telegram_id="123", status="active")]
        ),
    )

    async def preparation_failure(*args, **kwargs):
        raise RuntimeError("cannot format")

    monkeypatch.setattr(
        order_notice_factory,
        "notify_admins_about_order_created",
        preparation_failure,
    )
    with pytest.raises(DeliveryFailure) as error:
        await worker.send(job)
    assert not error.value.uncertain

    async def classified_preparation_failure(*args, **kwargs):
        raise DeliveryFailure("local_loader_unavailable", uncertain=True)

    monkeypatch.setattr(
        order_notice_factory,
        "notify_admins_about_order_created",
        classified_preparation_failure,
    )
    with pytest.raises(DeliveryFailure) as error:
        await worker.send(job)
    assert not error.value.uncertain

    async def send_failure(_order, client, *args, **kwargs):
        await client.send_text(chat_id="123", text="body")

    messenger.send_text.side_effect = TimeoutError("provider may have accepted")
    monkeypatch.setattr(
        order_notice_factory, "notify_admins_about_order_created", send_failure
    )
    with pytest.raises(TimeoutError):
        await worker.send(job)


@pytest.mark.asyncio
async def test_order_notice_preparation_retries_are_delayed_and_bounded():
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select, update

    from ugc_bot.application.notice_delivery_ports import DeliveryFailure
    from ugc_bot.application.services.order_notice_delivery import (
        OrderNoticeDelivery,
    )
    from ugc_bot.infrastructure.db.order_notice_models import (
        ORDER_NOTICE_DELIVERIES,
        metadata,
    )
    from ugc_bot.infrastructure.db.repositories.order_notices import (
        SqlAlchemyOrderNoticeRepository,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    factory = async_sessionmaker(engine)

    class Transactions:
        @asynccontextmanager
        async def transaction(self):
            async with factory.begin() as session:
                yield session

    tm = Transactions()
    repo = SqlAlchemyOrderNoticeRepository()
    async with tm.transaction() as session:
        await repo.enqueue(uuid4(), "paid", session=session)
    attempts = []

    async def send(job):
        attempts.append(job.attempt)
        raise DeliveryFailure("local_preparation_failed", uncertain=False)

    async def recipients():
        return ("123",)

    worker = OrderNoticeDelivery(repo, tm, send, recipients)
    for number in (1, 2, 3):
        assert await worker.run_once()
        async with tm.transaction() as session:
            row = (
                (await session.execute(select(ORDER_NOTICE_DELIVERIES)))
                .mappings()
                .one()
            )
            assert row["state"] == ("pending" if number < 3 else "failed")
        if number < 3:
            assert not await worker.run_once()
            async with tm.transaction() as session:
                await session.execute(
                    update(ORDER_NOTICE_DELIVERIES).values(
                        lease_until=datetime.now(timezone.utc)
                        - timedelta(seconds=1)
                    )
                )
    assert attempts == [1, 2, 3]
    await engine.dispose()


@pytest.mark.asyncio
async def test_expired_preparation_retries_but_expired_send_is_unknown():
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from ugc_bot.infrastructure.db.order_notice_models import (
        ORDER_NOTICE_DELIVERIES,
        metadata,
    )
    from ugc_bot.infrastructure.db.repositories.order_notices import (
        SqlAlchemyOrderNoticeRepository,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    factory = async_sessionmaker(engine)
    repo = SqlAlchemyOrderNoticeRepository()
    start = datetime.now(timezone.utc)
    async with factory.begin() as session:
        await repo.enqueue(uuid4(), "paid", session=session)
    async with factory.begin() as session:
        first = await repo.claim(start, ("123",), "", session=session)
        assert first is not None
    async with factory.begin() as session:
        assert (
            await repo.claim(
                start + timedelta(minutes=2, seconds=1),
                ("123",),
                "",
                session=session,
            )
            is None
        )
        row = (
            (await session.execute(select(ORDER_NOTICE_DELIVERIES)))
            .mappings()
            .one()
        )
        assert row["state"] == "pending"
    async with factory.begin() as session:
        second = await repo.claim(
            start + timedelta(minutes=3), ("123",), "", session=session
        )
        assert second is not None and second.attempt == 2
        assert not await repo.begin(
            first, start + timedelta(minutes=3), session=session
        )
        assert await repo.begin(
            second, start + timedelta(minutes=3), session=session
        )
    async with factory.begin() as session:
        assert (
            await repo.claim(
                start + timedelta(minutes=6), ("123",), "", session=session
            )
            is None
        )
        state = (
            await session.execute(select(ORDER_NOTICE_DELIVERIES.c.state))
        ).scalar_one()
        assert state == "unknown"
    await engine.dispose()


@pytest.mark.asyncio
async def test_telegram_rate_limit_is_known_rejection_with_provider_delay(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aiogram.exceptions import TelegramRetryAfter
    from aiogram.methods import SendMessage

    from ugc_bot.application.notice_delivery_ports import DeliveryFailure
    from ugc_bot.application.order_notice_ports import OrderNoticeJob
    from ugc_bot.config import AppConfig
    from ugc_bot.container import order_notice_factory

    config = AppConfig.model_validate(
        {"BOT_TOKEN": "synthetic", "KAFKA_ENABLED": False}
    )
    repos = {
        "user_repo": AsyncMock(),
        "order_repo": AsyncMock(),
        "advertiser_repo": AsyncMock(),
    }
    repos["order_repo"].get_by_id.return_value = SimpleNamespace(
        advertiser_id=uuid4()
    )
    messenger = AsyncMock()
    messenger.send_text.side_effect = TelegramRetryAfter(
        method=SendMessage(chat_id=123, text="test"),
        message="limited",
        retry_after=75,
    )

    class Transactions:
        @asynccontextmanager
        async def transaction(self):
            yield object()

    worker = order_notice_factory.build_order_notice_delivery(
        config, Transactions(), messenger, repos
    )
    worker.repository.begin = AsyncMock(return_value=True)
    monkeypatch.setattr(
        order_notice_factory.UserRoleService,
        "list_admins",
        AsyncMock(
            return_value=[SimpleNamespace(telegram_id="123", status="active")]
        ),
    )

    async def send(_order, client, *args, **kwargs):
        await client.send_text(chat_id="123", text="test")

    monkeypatch.setattr(
        order_notice_factory, "notify_admins_about_order_created", send
    )
    with pytest.raises(DeliveryFailure) as error:
        await worker.send(OrderNoticeJob(uuid4(), uuid4(), "created", "123", 1))
    assert error.value.uncertain is False
    assert error.value.retry_after_seconds == 75
    assert messenger.send_text.await_count == 1


@pytest.mark.asyncio
async def test_order_rate_limit_reschedules_durably_with_provider_delay():
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select, update

    from ugc_bot.application.notice_delivery_ports import DeliveryFailure
    from ugc_bot.application.services.order_notice_delivery import (
        OrderNoticeDelivery,
    )
    from ugc_bot.infrastructure.db.order_notice_models import (
        ORDER_NOTICE_DELIVERIES,
        metadata,
    )
    from ugc_bot.infrastructure.db.repositories.order_notices import (
        SqlAlchemyOrderNoticeRepository,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    factory = async_sessionmaker(engine)

    class Transactions:
        @asynccontextmanager
        async def transaction(self):
            async with factory.begin() as session:
                yield session

    tm, repo = Transactions(), SqlAlchemyOrderNoticeRepository()
    async with tm.transaction() as session:
        await repo.enqueue(uuid4(), "paid", session=session)
    attempts = []

    async def send(job):
        attempts.append(job.attempt)
        raise DeliveryFailure(
            "telegram_rate_limited", uncertain=False, retry_after_seconds=120
        )

    async def recipients():
        return ("123",)

    worker = OrderNoticeDelivery(repo, tm, send, recipients)
    before = datetime.now(timezone.utc)
    for attempt in (1, 2, 3):
        assert await worker.run_once()
        async with tm.transaction() as session:
            row = (
                (await session.execute(select(ORDER_NOTICE_DELIVERIES)))
                .mappings()
                .one()
            )
            assert row["state"] == ("pending" if attempt < 3 else "failed")
            if attempt < 3:
                assert row["lease_until"].replace(
                    tzinfo=timezone.utc
                ) >= before + timedelta(seconds=120)
        if attempt < 3:
            assert not await worker.run_once()
            async with tm.transaction() as session:
                await session.execute(
                    update(ORDER_NOTICE_DELIVERIES).values(
                        lease_until=before - timedelta(seconds=1)
                    )
                )
    assert attempts == [1, 2, 3]
    await engine.dispose()

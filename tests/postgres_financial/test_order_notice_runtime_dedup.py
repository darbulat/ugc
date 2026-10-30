"""The two production durable queues share one owner for paid admin cards."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.orm import Session

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
from ugc_bot.container.checkout_factory import build_checkout_service
from ugc_bot.container.order_notice_factory import build_order_notice_delivery
from ugc_bot.domain.checkout import NativePaidReceipt
from ugc_bot.infrastructure.db.checkout_models import NOTICE_JOBS
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
async def test_paid_capture_sends_one_admin_card_and_one_client_receipt(
    checkout_env,
):
    env = checkout_env
    # Use the production factory's ownership setting with the fixture gateway.
    checkout = build_checkout_service(env["config"], env["transactions"])
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
        env["container"].build_bot_services()["payment_service"],
        capture_repository=checkout.repository.capture,
        capture_account=env["config"].bot.telegram_payment_account_id,
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
        env["config"], env["transactions"], messenger, env["repos"]
    )
    for _ in range(100):
        if not await notices.run_once():
            break
    # Created + paid admin events are distinct; checkout sends only the receipt.
    assert messenger.send_text.await_count == 2
    assert not await processor.run_once()
    assert not await notices.run_once()


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

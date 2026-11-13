"""Provider ambiguity, expiry and runtime wiring use synthetic transports."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ugc_bot.application.customer_workflow_texts import bot_text_defaults
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    DeliveryReceipt,
)
from ugc_bot.application.services.customer_workflow_delivery import (
    CustomerWorkflowDelivery,
)
from ugc_bot.client_followup_scheduler import run_enabled, run_loop
from ugc_bot.config import AppConfig
from ugc_bot.container.customer_workflow_factory import (
    build_customer_workflow_delivery,
    build_customer_workflows,
)


class Transactions:
    @asynccontextmanager
    async def transaction(self):
        yield object()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "receipt,state",
    [
        ("accepted", "accepted"),
        ("invalid", "unknown"),
        ("exception", "unknown"),
        ("failed", "failed"),
        ("unknown", "unknown"),
    ],
)
async def test_receipts_and_failures_terminal(receipt, state):
    job = dict(
        job_id=uuid4(),
        request_id=uuid4(),
        series_id=None,
        channel="telegram",
        address="123",
        address_kind="chat_id",
        text="All fields",
    )
    repo = SimpleNamespace(
        eligible=AsyncMock(return_value=job),
        finish=AsyncMock(),
        expand_admin=AsyncMock(),
        claim=AsyncMock(side_effect=[job, None]),
    )
    transport = AsyncMock()
    transport.send.return_value = DeliveryReceipt(
        "telegram", "ok" if receipt == "accepted" else ""
    )
    if receipt == "exception":
        transport.send.side_effect = RuntimeError("private provider response")
    if receipt in ("failed", "unknown"):
        transport.send.side_effect = DeliveryFailure(
            "safe", uncertain=receipt == "unknown"
        )
    worker = CustomerWorkflowDelivery(
        repo,
        Transactions(),
        transport,
        SimpleNamespace(now=lambda: datetime.now(timezone.utc)),
        {},
    )
    assert await worker.run_once() == 1
    assert repo.finish.call_args.args[1] == state
    with pytest.raises(ValueError):
        await worker.run_once(0)


@pytest.mark.asyncio
async def test_followup_localization_actions_and_missing_channel_url():
    job = dict(
        job_id=uuid4(),
        request_id=None,
        series_id=uuid4(),
        channel="max",
        address="123",
        address_kind="user_id",
        stage=3,
        language="en",
        order_id=uuid4(),
    )
    repo = SimpleNamespace(
        eligible=AsyncMock(return_value=job),
        finish=AsyncMock(),
        retry_preparation=AsyncMock(),
    )
    transport = AsyncMock()
    transport.send.return_value = DeliveryReceipt("max", "ok")
    texts = SimpleNamespace(get=AsyncMock(side_effect=["Custom body", "Open"]))
    worker = CustomerWorkflowDelivery(
        repo,
        Transactions(),
        transport,
        SimpleNamespace(now=lambda: datetime.now(timezone.utc)),
        {"max": "https://test/app?platform=max"},
        texts=texts,
    )
    assert await worker.deliver(job)
    message = transport.send.call_args.args[0]
    assert (
        message.text == "Custom body"
        and "&screen=services&order_id=" in message.action_url
    )
    worker.texts = None
    worker.action_urls = {}
    assert await worker.deliver(job)
    repo.retry_preparation.assert_awaited_once()
    repo.eligible.return_value = None
    assert await worker.deliver(job) is False
    assert repo.finish.call_args.args[1] == "obsolete"
    assert set(bot_text_defaults()) == {"ru", "en", "kk", "be", "uz"}


@pytest.mark.asyncio
async def test_scheduler_bounds_continue_after_error_and_default_off():
    worker = SimpleNamespace(
        run_once=AsyncMock(side_effect=[RuntimeError("secret"), 0])
    )
    await run_loop(worker, interval_seconds=0.001, max_iterations=2)
    assert worker.run_once.call_count == 2
    for values in ({"interval_seconds": 0}, {"max_iterations": 0}):
        with pytest.raises(ValueError):
            await run_loop(worker, **values)
    await run_enabled(
        SimpleNamespace(customer_workflows_enabled=False), None, None
    )
    await run_enabled(
        SimpleNamespace(customer_workflows_enabled=True),
        SimpleNamespace(transaction_manager=None),
        None,
    )


@pytest.mark.asyncio
async def test_factory_and_enabled_scheduler_synthetic(monkeypatch):
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "synthetic",
            "KAFKA_ENABLED": False,
            "WEBHOOK_BASE_URL": "https://example.test",
        }
    )
    services = build_customer_workflows(Transactions())
    assert set(services) == {
        "order_support_service",
        "order_cancellation_service",
        "service_lead_service",
        "client_followup_service",
        "client_order_view_service",
    }
    worker = build_customer_workflow_delivery(
        config, Transactions(), AsyncMock()
    )
    assert (
        worker.action_urls["telegram"]
        == "https://example.test/miniapp/app.html"
    )
    fake = SimpleNamespace(run_once=AsyncMock(return_value=0))
    import ugc_bot.client_followup_scheduler as runtime

    monkeypatch.setattr(
        runtime,
        "build_customer_workflow_delivery",
        lambda *args, **kwargs: fake,
    )
    await run_enabled(
        SimpleNamespace(customer_workflows_enabled=True, max_bot=None),
        SimpleNamespace(
            transaction_manager=Transactions(),
            build_bot_texts_service=lambda: SimpleNamespace(
                load_from_db=AsyncMock()
            ),
        ),
        AsyncMock(),
        max_iterations=1,
    )
    assert fake.run_once.call_count == 1


@pytest.mark.asyncio
async def test_max_runtime_owns_session_without_live_send(monkeypatch):
    import ugc_bot.client_followup_scheduler as runtime

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "synthetic",
            "KAFKA_ENABLED": False,
            "MAX_BOT_TOKEN": "synthetic-max",
            "MAX_BOT_WEBHOOK_URL": "https://max.example.test/webhook",
        }
    )
    factory = build_customer_workflow_delivery(
        config, Transactions(), AsyncMock(), max_session=AsyncMock()
    )
    assert (
        factory.action_urls["max"]
        == "https://max.example.test/miniapp/max_app.html"
    )
    captured = []
    fake = SimpleNamespace(run_once=AsyncMock(return_value=0))

    def build(*args, **kwargs):
        captured.append(kwargs["max_session"])
        return fake

    monkeypatch.setattr(runtime, "build_customer_workflow_delivery", build)
    enabled = SimpleNamespace(
        customer_workflows_enabled=True, max_bot=config.max_bot
    )
    await run_enabled(
        enabled,
        SimpleNamespace(
            transaction_manager=Transactions(),
            build_bot_texts_service=lambda: SimpleNamespace(
                load_from_db=AsyncMock()
            ),
        ),
        AsyncMock(),
        max_iterations=1,
    )
    assert captured[0].closed


@pytest.mark.asyncio
async def test_known_preparation_failure_retries_without_transport():
    job = dict(
        job_id=uuid4(),
        request_id=None,
        series_id=uuid4(),
        stage=1,
        channel="telegram",
        address="123",
        address_kind="chat_id",
        language="ru",
        order_id=None,
    )
    repo = SimpleNamespace(
        eligible=AsyncMock(return_value=job),
        retry_preparation=AsyncMock(),
        finish=AsyncMock(),
    )
    transport = AsyncMock()

    async def offer(_current):
        raise DeliveryFailure("temporary_offer_unavailable", uncertain=False)

    worker = CustomerWorkflowDelivery(
        repo,
        Transactions(),
        transport,
        SimpleNamespace(now=lambda: datetime.now(timezone.utc)),
        {"telegram": "https://example.test"},
        offer_loader=offer,
    )
    assert await worker.deliver(job)
    repo.retry_preparation.assert_awaited_once()
    transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_changed_delivery_context_retries_before_transport():
    job = dict(
        job_id=uuid4(),
        request_id=None,
        series_id=uuid4(),
        stage=1,
        channel="telegram",
        address="123",
        address_kind="chat_id",
        language="ru",
        order_id=None,
    )
    repo = SimpleNamespace(
        eligible=AsyncMock(side_effect=[job, job | {"address": "456"}]),
        retry_preparation=AsyncMock(),
        finish=AsyncMock(),
    )
    transport = AsyncMock()
    worker = CustomerWorkflowDelivery(
        repo,
        Transactions(),
        transport,
        SimpleNamespace(now=lambda: datetime.now(timezone.utc)),
        {"telegram": "https://example.test"},
    )
    assert not await worker.deliver(job)
    repo.retry_preparation.assert_awaited_once()
    transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_context_change_during_sending_transition_does_not_send():
    job = dict(
        job_id=uuid4(),
        request_id=None,
        series_id=uuid4(),
        stage=1,
        channel="telegram",
        address="123",
        address_kind="chat_id",
        language="ru",
        order_id=None,
    )
    repo = SimpleNamespace(
        eligible=AsyncMock(side_effect=[job, job, job | {"address": "456"}]),
        retry_preparation=AsyncMock(),
        finish=AsyncMock(),
        retry_before_transport=AsyncMock(),
    )
    transport = AsyncMock()
    worker = CustomerWorkflowDelivery(
        repo,
        Transactions(),
        transport,
        SimpleNamespace(now=lambda: datetime.now(timezone.utc)),
        {"telegram": "https://example.test"},
    )
    assert not await worker.deliver(job)
    repo.retry_before_transport.assert_awaited_once()
    transport.send.assert_not_awaited()

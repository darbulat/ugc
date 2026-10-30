"""Scheduler orchestration, cancellation and daily maintenance stay offline."""

import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from ugc_bot import (
    combined_scheduler,
    order_image_cleanup_scheduler,
    order_notice_scheduler,
)
from ugc_bot.config import AppConfig
from ugc_bot.container import Container


@pytest.mark.asyncio
async def test_combined_starts_customer_runtime_with_financial_flags_disabled(
    monkeypatch,
):
    seen = []

    async def loop(config, container, bot):
        seen.append((config, container, bot))

    for key in (
        "order_notice_loop",
        "customer_workflow_loop",
        "image_cleanup_loop",
    ):
        monkeypatch.setattr(combined_scheduler, key, loop)
    config, container, bot = (
        object(),
        NS(transaction_manager=object()),
        object(),
    )
    tasks = combined_scheduler._customer_tasks(config, container, bot)
    assert {task.get_name() for task in tasks} == {
        "order-notice-delivery",
        "customer-workflow-delivery",
        "order-image-cleanup",
    }
    await asyncio.gather(*tasks)
    assert seen == [(config, container, bot)] * 3
    assert (
        combined_scheduler._customer_tasks(
            config, NS(transaction_manager=None), bot
        )
        == []
    )


@pytest.mark.asyncio
async def test_notice_scheduler_drains_queue_recovers_and_cleanup_runs_daily(
    monkeypatch,
):
    worker = NS(
        run_once=AsyncMock(side_effect=[True, False, RuntimeError("synthetic")])
    )
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(order_notice_scheduler.asyncio, "sleep", sleep)
    await order_notice_scheduler.run_loop(worker, max_iterations=2)
    assert worker.run_once.await_count == 3
    assert sleeps == [5]
    cleanup = NS(cleanup=AsyncMock(side_effect=[RuntimeError("synthetic"), 2]))
    sleeps.clear()
    await order_image_cleanup_scheduler.run_loop(cleanup, max_iterations=2)
    assert sleeps == [86400]
    assert cleanup.cleanup.await_count == 2
    for runtime, service in (
        (order_notice_scheduler, worker),
        (order_image_cleanup_scheduler, cleanup),
    ):
        for bounds in ({"interval_seconds": 0}, {"max_iterations": 0}):
            with pytest.raises(ValueError):
                await runtime.run_loop(service, **bounds)


@pytest.mark.asyncio
async def test_durable_notice_transport_does_not_retry_an_uncertain_send():
    from aiogram.exceptions import TelegramNetworkError
    from aiogram.methods import SendMessage

    bot = NS(
        send_message=AsyncMock(
            side_effect=[
                TelegramNetworkError(
                    method=SendMessage(chat_id=123, text="notice"),
                    message="response lost",
                ),
                object(),
            ]
        )
    )
    captured = []

    class Container:
        def build_order_notice_delivery(self, messenger):
            captured.append(messenger)
            return

    await order_notice_scheduler.run_enabled(None, Container(), bot)
    with pytest.raises(TelegramNetworkError):
        await captured[0].send_text(chat_id="123", text="notice")
    assert bot.send_message.await_count == 1


def test_no_database_has_no_private_runtime_dependencies():
    container = Container(
        AppConfig.model_validate(
            {
                "BOT_TOKEN": "synthetic",
                "DATABASE_URL": "",
                "KAFKA_ENABLED": False,
            }
        )
    )
    assert container.build_order_image_service() is None
    assert container.build_order_notice_delivery(object()) is None

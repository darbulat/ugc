"""Worker commit order, ambiguous receipts and bounded scheduler behavior."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    DeliveryReceipt,
)
from ugc_bot.application.services.campaign_delivery_service import (
    CampaignDeliveryService,
)
from ugc_bot.application.services.campaign_response_service import (
    CampaignResponseService,
)
from ugc_bot.campaign_scheduler import run_loop
from ugc_bot.container.campaign_analytics_factory import (
    build_campaign_analytics,
)
from ugc_bot.container.campaign_runtime_factory import build_campaign_runtime


class Transactions:
    def __init__(self):
        self.active = False
        self.commits = 0

    @asynccontextmanager
    async def transaction(self):
        assert not self.active
        self.active = True
        try:
            yield object()
        finally:
            self.active = False
            self.commits += 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,result",
    [
        (DeliveryFailure("PRIVATE", uncertain=False), "failed"),
        (RuntimeError("PRIVATE"), "unknown"),
        (None, "unknown"),
        (DeliveryReceipt("max", "receipt"), "unknown"),
        (DeliveryReceipt("telegram", " "), "unknown"),
        (DeliveryReceipt("telegram", "receipt"), "accepted"),
    ],
)
async def test_worker_commits_before_one_transport_attempt_and_bounds_receipts(
    provider, result
):
    tm = Transactions()
    attempt = object()
    repo = SimpleNamespace(
        pending=AsyncMock(return_value=("skip", "send")),
        prepare=AsyncMock(side_effect=(None, attempt)),
        finish=AsyncMock(),
    )

    async def send(value):
        assert value is attempt and not tm.active and tm.commits == 3
        if isinstance(provider, Exception):
            raise provider
        return provider

    clock = SimpleNamespace(
        now=lambda: datetime(2026, 10, 25, tzinfo=timezone.utc)
    )
    worker = CampaignDeliveryService(
        repo, tm, SimpleNamespace(send=send), clock, enabled=True
    )
    assert await worker.run_once() == 1
    assert repo.finish.await_args.args[1] == result
    assert "PRIVATE" not in str(repo.finish.await_args)


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 1001, True, "10"])
async def test_disabled_worker_and_invalid_bounds_never_query_or_send(limit):
    worker = CampaignDeliveryService(None, None, None, None)
    assert await worker.run_once() == 0
    with pytest.raises(ValueError, match="bounds"):
        await worker.run_once(limit=limit)


@pytest.mark.asyncio
async def test_bounded_scheduler_survives_safe_failure_then_stops(
    monkeypatch, caplog
):
    worker = SimpleNamespace(
        run_once=AsyncMock(side_effect=(RuntimeError("PRIVATE"), None))
    )
    sleep = AsyncMock()
    monkeypatch.setattr("ugc_bot.campaign_scheduler.asyncio.sleep", sleep)
    await run_loop(worker, max_iterations=2)
    assert worker.run_once.await_count == 2 and sleep.await_count == 1
    assert "PRIVATE" not in caplog.text
    for values in ({"interval_seconds": 0}, {"max_iterations": 0}):
        with pytest.raises(ValueError, match="bounds"):
            await run_loop(worker, **values)


@pytest.mark.asyncio
async def test_invalid_response_never_reaches_repository():
    service = CampaignResponseService(None, None)
    with pytest.raises(ValueError, match="request_invalid"):
        await service.respond(
            None, None, "key", True, "interested", principal=None, session=None
        )


def test_runtime_factories_need_explicit_database_and_transport():
    assert build_campaign_runtime(None, None) == {}
    assert build_campaign_analytics(None) == {}
    config = SimpleNamespace(
        webhook=SimpleNamespace(webhook_base_url="https://example.test")
    )
    with pytest.raises(ValueError, match="transport_required"):
        build_campaign_runtime(config, object(), delivery_enabled=True)
    services = build_campaign_runtime(
        config, object(), delivery_enabled=True, bot=object()
    )
    assert services["campaign_delivery_service"].enabled is True

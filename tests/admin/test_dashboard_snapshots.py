"""Persistent values, visitor-driven refreshes and shared calculation work."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from ugc_bot.admin.dashboard_snapshots import DashboardSnapshots
from ugc_bot.infrastructure.redis_cache import serialize_admin_payload

KEY = "UTC:today"


def snapshot(value=1, *, days_old=0):
    date = datetime.now(timezone.utc) - timedelta(days=days_old)
    return {
        "payload": {"value": value},
        "creator_base": {},
        "attention_counts": {"no_manager": value},
        "calculated_at": date.isoformat(),
        "counts_at": date.isoformat(),
        "period_date": date.date().isoformat(),
    }


@pytest.fixture
def cache():
    values = {}
    mock = MagicMock()
    mock.values = values
    mock.get = AsyncMock(side_effect=lambda key: values.get(key))

    async def put(key, value, _ttl):
        values[key] = value

    mock.set = AsyncMock(side_effect=put)
    return mock


@pytest.mark.asyncio
async def test_saved_values_survive_expiration_and_worker_restart(cache):
    saved = snapshot()
    store = DashboardSnapshots(cache)
    calculate = AsyncMock(return_value=saved)
    await store.refresh(KEY, 90, saved["period_date"], calculate)
    calculate.assert_awaited_once_with(None)
    cache.values.pop(f"dashboard:snapshot-fresh:v1:{KEY}")
    restarted = DashboardSnapshots(cache)
    assert await restarted.read(KEY) == saved
    await restarted.refresh(KEY, 90, saved["period_date"], calculate)
    assert calculate.await_args.args == (None,)
    assert calculate.await_count == 2


@pytest.mark.asyncio
async def test_fresh_history_is_reused_without_extending_its_deadline(cache):
    saved = snapshot()
    store = DashboardSnapshots(cache)
    await store.refresh(
        KEY, 90, saved["period_date"], AsyncMock(return_value=saved)
    )
    calculate = AsyncMock(
        return_value=saved | {"attention_counts": {"no_manager": 2}}
    )
    await store.refresh(KEY, 90, saved["period_date"], calculate)
    calculate.assert_awaited_once_with(saved)
    assert (await store.read(KEY))["attention_counts"]["no_manager"] == 2
    markers = [
        call
        for call in cache.set.await_args_list
        if "snapshot-fresh:" in call.args[0]
    ]
    assert len(markers) == 1


@pytest.mark.asyncio
async def test_concurrent_visitors_share_refresh_even_if_one_leaves(cache):
    store = DashboardSnapshots(cache)
    started, finish = asyncio.Event(), asyncio.Event()
    saved = snapshot()

    async def calculate(previous):
        assert previous is None
        started.set()
        await finish.wait()
        return saved

    calculate = AsyncMock(side_effect=calculate)
    first = asyncio.create_task(
        store.refresh(KEY, 90, saved["period_date"], calculate)
    )
    await started.wait()
    second = asyncio.create_task(
        store.refresh(KEY, 90, saved["period_date"], calculate)
    )
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    finish.set()
    assert await second == saved
    calculate.assert_awaited_once()
    await store.close()


@pytest.mark.asyncio
async def test_failed_refresh_keeps_last_good_values_and_allows_retry(cache):
    saved = snapshot(days_old=1)
    cache.values[f"dashboard-snapshot:v1:{KEY}"] = serialize_admin_payload(
        saved
    )
    store = DashboardSnapshots(cache)
    with pytest.raises(RuntimeError):
        await store.refresh(
            KEY,
            90,
            "new-day",
            AsyncMock(side_effect=RuntimeError("Temporary failure")),
        )
    assert await store.read(KEY) == saved
    newer = snapshot(2)
    assert (
        await store.refresh(
            KEY, 90, newer["period_date"], AsyncMock(return_value=newer)
        )
        == newer
    )


@pytest.mark.asyncio
async def test_midnight_refresh_and_diagnostics_preserve_snapshot(
    cache,
):
    saved = snapshot(days_old=1)
    store = DashboardSnapshots(cache)
    await store.refresh(
        KEY, 90, saved["period_date"], AsyncMock(return_value=saved)
    )
    calculate = AsyncMock(return_value=snapshot(2))
    await store.refresh(KEY, 90, "new-day", calculate)
    calculate.assert_awaited_once_with(None)
    diagnostic = snapshot(3)
    calculate = AsyncMock(return_value=diagnostic)
    await store.refresh(
        KEY, 90, diagnostic["period_date"], calculate, force=True
    )
    calculate.assert_awaited_once_with(None)
    assert (await store.read(KEY))["payload"]["value"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [b"invalid-json", b"{}", "timeout", "bad-date", "expired", "naive"],
)
async def test_bad_cache_does_not_discard_last_good_values(cache, failure):
    store = DashboardSnapshots(cache)
    saved = snapshot()
    store._last[KEY] = saved
    if failure == "timeout":
        cache.get.side_effect = TimeoutError
    else:
        if failure == "bad-date":
            failure = serialize_admin_payload(
                saved | {"calculated_at": "bad-date"}
            )
        elif failure == "expired":
            failure = serialize_admin_payload(snapshot(days_old=8))
        elif failure == "naive":
            failure = serialize_admin_payload(
                saved | {"calculated_at": "2026-11-17T12:00:00"}
            )
        cache.values[f"dashboard-snapshot:v1:{KEY}"] = failure
    assert await store.read(KEY) == saved


@pytest.mark.asyncio
async def test_cache_outage_keeps_newer_local_values(cache):
    old = snapshot(days_old=1)
    key = f"dashboard-snapshot:v1:{KEY}"
    cache.values[key] = serialize_admin_payload(old)

    async def get(name):
        if "snapshot-fresh:" in name:
            raise TimeoutError
        return cache.values.get(name)

    cache.get.side_effect = get
    cache.set.side_effect = TimeoutError
    store = DashboardSnapshots(cache)
    newer = snapshot(2)
    calculate = AsyncMock(return_value=newer)
    await store.refresh(KEY, 90, newer["period_date"], calculate)
    calculate.assert_awaited_once_with(None)
    assert await store.read(KEY) == newer


@pytest.mark.asyncio
async def test_shutdown_cancels_unfinished_work():
    store = DashboardSnapshots(None)
    started = asyncio.Event()

    async def calculate(_previous):
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(store.refresh(KEY, 90, "today", calculate))
    await started.wait()
    await store.close()
    with pytest.raises(asyncio.CancelledError):
        await task

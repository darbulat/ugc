"""Maturity work continues after a deferred order and advances its cursor."""

from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from ugc_bot.application.services.selection_maturity_sweep_service import (
    SelectionMaturitySweepService,
)
from ugc_bot.selection_maturity_scheduler import run_loop


class Transactions:
    @asynccontextmanager
    async def transaction(self):
        yield object()


@pytest.mark.asyncio
async def test_maturity_sweep_pages_and_defers_without_starving_later_orders():
    orders = [uuid4(), uuid4()]
    seen = []

    class Repository:
        async def list_orders(self, *, after, limit, session):
            seen.append(after)
            return orders if after is None else []

    class Maturity:
        repository = Repository()

        async def refresh(self, order_id, *, session):
            if order_id == orders[0]:
                raise ValueError("selection_not_resolved")
            return dict(state="closed")

    sweep = SelectionMaturitySweepService(Maturity(), Transactions())
    result = await sweep.run_once(limit=2)
    assert (result.attempted, result.closed, result.deferred) == (2, 1, 1)
    assert (await sweep.run_once(limit=2)).attempted == 0
    assert seen == [None, orders[-1]]
    for invalid in (True, 0, 1001):
        with pytest.raises(ValueError, match="limit_invalid"):
            await sweep.run_once(limit=invalid)


@pytest.mark.asyncio
async def test_scheduler_retries_failed_iteration_without_logging_private_data(
    monkeypatch, caplog
):
    calls = []

    class Sweep:
        async def run_once(self):
            calls.append(True)
            if len(calls) == 1:
                raise RuntimeError("PRIVATE evidence")
            return NS(attempted=1, closed=1, deferred=0)

    async def sleep(delay):
        assert delay == 1

    monkeypatch.setattr(
        "ugc_bot.selection_maturity_scheduler.asyncio.sleep", sleep
    )
    await run_loop(Sweep(), interval_seconds=1, max_iterations=2)
    assert len(calls) == 2 and "PRIVATE" not in caplog.text
    for values in (dict(interval_seconds=0), dict(max_iterations=0)):
        with pytest.raises(ValueError, match="bounds_invalid"):
            await run_loop(Sweep(), **values)

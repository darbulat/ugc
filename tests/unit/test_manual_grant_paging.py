"""A blocked early grant must not starve later eligible hold balances."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from uuid import UUID

import pytest

from ugc_bot.application.services.manual_grant_service import (
    ManualGrantSweepService,
)


@pytest.mark.asyncio
async def test_manual_grant_sweep_pages_past_deferred_first_and_wraps():
    at = datetime(2026, 10, 25, tzinfo=timezone.utc)
    first, second = UUID(int=1), UUID(int=2)
    attempts = []

    class Repository:
        async def list_ready(self, now, limit, *, after=None, session):
            rows = [(at, first), (at, second)]
            return tuple(row for row in rows if after is None or row > after)[
                :limit
            ]

    class Grants:
        repository = Repository()
        clock = NS(now=lambda: at)

        async def mature(self, identity, *, session):
            attempts.append(identity)
            if identity == first:
                raise ValueError("manual_grant_recipient_unavailable")
            return dict(mature=True)

    class Transactions:
        @asynccontextmanager
        async def transaction(self):
            yield object()

    sweep = ManualGrantSweepService(Grants(), Transactions())
    assert (await sweep.run_once(limit=1))["deferred"] == 1
    assert (await sweep.run_once(limit=1))["matured"] == 1
    assert (await sweep.run_once(limit=1))["attempted"] == 0
    assert (await sweep.run_once(limit=1))["deferred"] == 1
    assert attempts == [first, second, first]

"""A delayed capture assessment cannot leave a disputed item spendable."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.application.services.test_client_entitlement_service import (
    START,
    scenario,
)
from ugc_bot.application.services.work_financial_guard import WorkFinancialGuard
from ugc_bot.application.work_entitlement_ports import WorkDisputeCase


def guard_for(source, *, future=False):
    case = WorkDisputeCase(
        uuid4(),
        uuid4(),
        source.capture.items[0].paid_item_id,
        uuid4(),
        source.capture.client_id,
        "actual opposite-party objection",
        START + timedelta(seconds=1) if future else START,
    )

    async def get_dispute_case(item_id, *, session):
        return case if item_id == case.paid_item_id else None

    return WorkFinancialGuard(
        SimpleNamespace(get_dispute_case=get_dispute_case)
    ), case


@pytest.mark.asyncio
async def test_dispute_before_delayed_capture_blocks_its_new_client_ground():
    service, source, repo, _, _, event = await scenario()
    service.work_guard, case = guard_for(source)
    async with repo.transaction() as session:
        await service.handle(event, session=session)
    assert len(repo.movements) == 2
    issue, blocked = list(repo.movements.values())
    assert issue.bucket_to == "pending"
    assert blocked.bucket_from == "pending" and blocked.bucket_to == "blocked"
    assert blocked.case_id == case.case_id
    assert blocked.event_id == str(case.source_event_id)
    assert blocked.actor_kind == "system"
    assert blocked.actor_id is None
    assert blocked.system_actor == "client_entitlement"
    assert source.receipt is not None
    async with repo.transaction() as session:
        await service.handle(event, session=session)
    assert len(repo.movements) == 2


@pytest.mark.asyncio
async def test_future_dispute_fact_is_not_used_to_create_money_early():
    service, source, repo, _, _, event = await scenario()
    service.work_guard, _ = guard_for(source, future=True)
    with pytest.raises(ValueError, match="work_case_time_conflict"):
        async with repo.transaction() as session:
            await service.handle(event, session=session)
    assert repo.records == repo.movements == repo.wallets == {}
    assert source.receipt is None

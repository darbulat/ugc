"""A refund alone never decides the future fixed management entitlement."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.application.services.test_work_entitlement_service import setup
from ugc_bot.application.financial_ports import WorkMaturitySource


class Funding:
    decision = None

    async def require_forward_clear(self, *args, **kwargs):
        pass

    async def load_item(self, *args, **kwargs):
        return (
            SimpleNamespace(
                component="accompaniment", cumulative_refund_minor=60000
            ),
        )

    async def management_refund_disposition(self, *args, **kwargs):
        return self.decision


@pytest.mark.asyncio
async def test_partial_refund_review_allows_future_management_600():
    repo, ledger, service, clock, event, _, _ = setup(final=True)
    scope, work = repo.snapshot.scope, repo.snapshot.record.collaboration
    source = WorkMaturitySource(
        source_id=uuid4(),
        source_event_id=event.event_id,
        assignment_id=scope.assignment_id,
        paid_item_id=scope.paid_item_id,
        order_id=scope.order_id,
        policy_version=scope.policy_version,
        creator_id=scope.creator_id,
        manager_id=scope.manager_id,
        state="success_final",
        assignment_ended_at=None,
        success_final_at=work.success_final_at,
        release_at=work.available_at,
    )
    ledger.maturity_sources[source.source_id] = source
    repo.snapshot = replace(repo.snapshot, schedule_id=source.source_id)
    service.funding_guard = Funding()
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
    assert not any(
        r.basis.kind == "management" for r in ledger.records.values()
    )
    assert (
        repo.receipts[event.event_id]["assessment"]["manager"]
        == "accompaniment_management_review_required"
    )
    service.funding_guard.decision = "continue"
    async with ledger.transaction() as session:
        await service.handle(replace(event, event_id=uuid4()), session=session)
        money = await ledger.read_projection(
            scope.manager_id, "RUB", session=session
        )
    assert money["hold"] == 60000
    assert money["available"] == 0

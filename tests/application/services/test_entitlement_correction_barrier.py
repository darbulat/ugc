"""Unapplied corrections stop ordinary entitlement consumers."""

from dataclasses import replace
from uuid import uuid4

import pytest

from tests.application.services.test_work_entitlement_service import setup


class Blocked:
    def __init__(self):
        self.items = []

    async def require_forward_clear(self, item_id, *, session, components):
        self.items.append(item_id)
        raise ValueError("correction_unresolved")


@pytest.mark.asyncio
async def test_current_correction_blocks_creator_issue_before_any_money():
    repo, ledger, service, _, event, _, _ = setup()
    guard = Blocked()
    service.funding_guard = guard
    async with ledger.transaction() as session:
        with pytest.raises(ValueError, match="correction_unresolved"):
            await service.handle(event, session=session)
        assert not ledger.records
    assert guard.items == [repo.snapshot.scope.paid_item_id]


@pytest.mark.asyncio
async def test_current_correction_blocks_maturity_of_existing_obligation():
    repo, ledger, service, _, event, _, _ = setup()
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
    guard = Blocked()
    service.funding_guard = guard
    async with ledger.transaction() as session:
        with pytest.raises(ValueError, match="correction_unresolved"):
            await service.handle(
                replace(event, event_id=uuid4()), session=session
            )
    assert guard.items

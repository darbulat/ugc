"""A reviewed work outcome moves only its original blocked obligations."""

from dataclasses import replace
from uuid import uuid4

import pytest

from tests.application.services.test_work_entitlement_service import (
    case_for,
    setup,
)
from ugc_bot.application.financial_ports import WorkMaturitySource
from ugc_bot.domain.collaboration import CollaborationState


async def blocked():
    repo, ledger, service, clock, event, partner, _ = setup()
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
    case = case_for(repo)
    repo.dispute = case
    async with ledger.transaction() as session:
        await service.handle(replace(event, event_id=uuid4()), session=session)
        assert (await ledger.read_projection(partner, "RUB", session=session))[
            "blocked"
        ] == 5000
    repo.dispute = None
    repo.snapshot = replace(repo.snapshot, resolution_case_id=case.case_id)
    return repo, ledger, service, clock, event, partner, case


@pytest.mark.asyncio
async def test_rejection_cancels_blocked_creator_without_income():
    repo, ledger, service, clock, event, partner, case = await blocked()
    repo.snapshot = replace(
        repo.snapshot,
        record=replace(
            repo.snapshot.record,
            collaboration=replace(
                repo.snapshot.record.collaboration,
                state=CollaborationState.REJECTED,
            ),
        ),
    )
    async with ledger.transaction() as session:
        await service.handle(
            replace(
                event,
                event_id=uuid4(),
                event_type="financial.collaboration.rejected",
            ),
            session=session,
        )
        money = await ledger.read_projection(partner, "RUB", session=session)
    assert money["blocked"] == money["available"] == money["hold"] == 0
    assert money["cancelled"] == 5000
    reversal = next(
        m for m in ledger.movements.values() if m.movement_type == "reversal"
    )
    assert reversal.case_id == case.case_id
    assert reversal.effective_at == clock.at
    assert not any(
        o.basis.kind == "management" for o in ledger.records.values()
    )


@pytest.mark.asyncio
async def test_administrative_success_unblocks_to_actual_fresh_hold_only():
    repo, ledger, service, clock, event, partner, case = await blocked()
    work = replace(
        repo.snapshot.record.collaboration,
        state=CollaborationState.SUCCESS_FINAL,
        success_final_at=clock.at,
    )
    source = WorkMaturitySource(
        source_id=uuid4(),
        source_event_id=uuid4(),
        assignment_id=work.assignment_id,
        paid_item_id=repo.snapshot.scope.paid_item_id,
        order_id=repo.snapshot.scope.order_id,
        policy_version=repo.snapshot.scope.policy_version,
        creator_id=work.creator_id,
        manager_id=work.manager_id,
        state="success_final",
        assignment_ended_at=None,
        success_final_at=clock.at,
        release_at=work.available_at,
    )
    ledger.maturity_sources[source.source_id] = source
    repo.snapshot = replace(
        repo.snapshot,
        record=replace(repo.snapshot.record, collaboration=work),
        schedule_id=source.source_id,
    )
    async with ledger.transaction() as session:
        await service.handle(
            replace(
                event,
                event_id=uuid4(),
                event_type="financial.collaboration.success_final",
            ),
            session=session,
        )
        money = await ledger.read_projection(partner, "RUB", session=session)
    assert money["blocked"] == money["available"] == 0
    assert money["hold"] == 5000
    unblocked = next(
        m for m in ledger.movements.values() if m.bucket_from == "blocked"
    )
    assert unblocked.case_id == case.case_id

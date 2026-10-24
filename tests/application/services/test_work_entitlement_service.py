"""Capture-time referral and current lifecycle from trusted work events."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from ugc_bot.application.collaboration_ports import (
    CollaborationRecord,
    CollaborationScope,
)
from ugc_bot.application.entitlement_ports import ClientCapture, FundedSelection
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicy,
)
from ugc_bot.domain.collaboration import Collaboration, CollaborationState
from ugc_bot.domain.entities import OutboxEvent
from ugc_bot.domain.enums import OutboxEventStatus
from ugc_bot.domain.identity_history import (
    HistoricalDirectAttribution,
    VerifiedCreatorCount,
)
from ugc_bot.infrastructure.memory_financial_ledger import (
    InMemoryFinancialLedgerRepository,
)

START = datetime(2026, 10, 23, tzinfo=timezone.utc)


class Clock:
    at = START + timedelta(hours=2)

    def now(self):
        return self.at


class History:
    def __init__(self, creator, recipient, calls):
        self.creator, self.recipient, self.calls = creator, recipient, calls

    async def resolve_direct_binding(self, creator, as_of, *, session):
        assert creator == self.creator and as_of == START
        return HistoricalDirectAttribution(
            creator,
            self.recipient,
            as_of,
            START - timedelta(days=5) if self.recipient else None,
            START - timedelta(days=5) if self.recipient else None,
            START - timedelta(days=5) if self.recipient else None,
            1 if self.recipient else None,
            None if self.recipient else "unbound",
            START - timedelta(days=10),
            START + timedelta(hours=1),
            "v1",
        )

    async def count_verified_direct_creators(
        self, recipient, as_of, *, session
    ):
        assert recipient == self.recipient and as_of == START
        return VerifiedCreatorCount(
            recipient,
            as_of,
            9,
            START - timedelta(days=10),
            START + timedelta(hours=1),
            1,
            1,
            "v1",
        )

    async def acquire_snapshot_barrier(self, *, session):
        self.calls.append("history")


class Overrides:
    async def select_effective_override(
        self, recipient, side, policy, as_of, *, session
    ):
        assert side == "creator" and as_of == START
        return


class Repo:
    def __init__(self, snapshot, calls):
        self.snapshot, self.calls = snapshot, calls
        self.receipts = {}
        self.dispute = None

    async def source_hash(self, event, *, session):
        return "a" * 64

    async def load(self, event, *, session):
        return self.snapshot

    async def lock_funding(self, snapshot, *, session):
        self.calls.append("order")

    async def get_receipt(self, event_id, *, session):
        return self.receipts.get(event_id)

    async def save_receipt(
        self, event, snapshot, assessment, *, recorded_at, session
    ):
        self.receipts[event.event_id] = {
            "source_hash": snapshot.source_hash,
            "assessment": assessment,
        }

    async def get_dispute_case(self, item_id, *, session):
        return self.dispute


class Ledger(InMemoryFinancialLedgerRepository):
    def __init__(self, calls):
        super().__init__()
        self.calls = calls

    async def lock_item(self, item_id, *, session):
        self.calls.append("item")
        await super().lock_item(item_id, session=session)


def setup(*, accompaniment=120000, referred=True, final=False):
    from ugc_bot.application.services.work_entitlement_service import (
        WorkEntitlementService,
    )
    from ugc_bot.application.work_entitlement_ports import (
        WorkEntitlementSnapshot,
    )

    client, creator, manager, partner, assignment, item, order, payment, eid = [
        uuid4() for _ in range(9)
    ]
    calls = []
    work = Collaboration(
        assignment_id=assignment,
        client_id=client,
        creator_id=creator,
        manager_id=manager,
        due_at=START + timedelta(days=3),
        agreed_at=START + timedelta(hours=1),
    )
    if final:
        work = replace(
            work,
            state=CollaborationState.SUCCESS_FINAL,
            claimant_id=creator,
            claimed_at=START + timedelta(hours=1),
            success_final_at=START + timedelta(hours=2),
        )
    record = CollaborationRecord(
        work,
        item,
        order,
        "approved:test",
        "terms:test",
        4 if final else 1,
        START + timedelta(hours=2),
    )
    scope = CollaborationScope(
        assignment_id=assignment,
        paid_item_id=item,
        order_id=order,
        client_id=client,
        creator_id=creator,
        manager_id=manager,
        policy_version="approved:test",
        captured_at=START,
        valid_from=START + timedelta(hours=1),
        valid_to=None,
        selection_funded=True,
    )
    policy = FinancialPolicy(
        "approved:test",
        client,
        START - timedelta(days=2),
        START - timedelta(days=1),
        timedelta(hours=1),
        frozenset({client}),
        "terms:test",
    )
    capture = ClientCapture(
        uuid4(),
        order,
        payment,
        client,
        policy,
        START,
        START - timedelta(days=5),
        partner,
        (FundedSelection(item, 50000, accompaniment),),
        "funding",
    )
    snapshot = WorkEntitlementSnapshot(scope, record, capture, "a" * 64, True)
    repo = Repo(snapshot, calls)
    ledger = Ledger(calls)
    clock = Clock()
    history = History(creator, partner if referred else None, calls)
    service = WorkEntitlementService(
        repo, FinancialLedgerService(ledger), history, Overrides(), clock
    )
    event = OutboxEvent(
        eid,
        "financial.collaboration.success_final"
        if final
        else "financial.collaboration.assigned",
        str(assignment),
        "collaboration",
        {"collaboration_event_id": str(eid)},
        OutboxEventStatus.PENDING,
        clock.at,
        None,
        0,
        None,
    )
    return repo, ledger, service, clock, event, partner, calls


@pytest.mark.asyncio
async def test_assignment_waits_for_actual_manager_success():
    repo, ledger, service, _, event, partner, calls = setup()
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
        wallet = await ledger.read_projection(partner, "RUB", session=session)
    assert wallet["pending"] == 5000 and wallet["hold"] == 0
    assert len(ledger.records) == 1
    assert next(iter(ledger.records.values())).basis.snapshot_at == START
    assert calls.index("order") < calls.index("history") < calls.index("item")
    assert event.event_id in repo.receipts


@pytest.mark.asyncio
async def test_maturity_keeps_the_original_payment_snapshot():
    repo, ledger, service, clock, event, partner, _ = setup(final=True)
    from ugc_bot.application.financial_ports import WorkMaturitySource

    scope = repo.snapshot.scope
    work = repo.snapshot.record.collaboration
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
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
        assert (await ledger.read_projection(partner, "RUB", session=session))[
            "hold"
        ] == 5000
        assert (
            await ledger.read_projection(
                scope.manager_id, "RUB", session=session
            )
        )["hold"] == 60000
    clock.at = work.available_at
    later = replace(
        event,
        event_id=uuid4(),
        event_type="financial.collaboration.hold_matured",
    )
    async with ledger.transaction() as session:
        await service.handle(later, session=session)
        assert (await ledger.read_projection(partner, "RUB", session=session))[
            "available"
        ] == 5000
    assert all(
        record.basis.available_at is None for record in ledger.records.values()
    )


@pytest.mark.asyncio
async def test_known_absent_referrer_has_no_fabricated_grade():
    repo, ledger, service, _, event, _, _ = setup(referred=False)
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
    assert not ledger.records
    potential = next(iter(ledger.potentials.values()))
    assert potential.basis.recipient_id is None
    assert potential.basis.verified_count is None
    assert potential.basis.registered_at is None
    assert event.event_id in repo.receipts


@pytest.mark.asyncio
async def test_later_success_keeps_original_creator_issue_payload():
    from ugc_bot.application.financial_ports import WorkMaturitySource

    repo, ledger, service, clock, event, _, _ = setup()
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
    original = next(iter(ledger.records.values()))
    work = replace(
        repo.snapshot.record.collaboration,
        state=CollaborationState.SUCCESS_FINAL,
        claimant_id=repo.snapshot.scope.creator_id,
        claimed_at=clock.at,
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
        record=replace(repo.snapshot.record, collaboration=work, version=4),
        schedule_id=source.source_id,
        current_event_id=source.source_event_id,
    )
    final = replace(
        event,
        event_id=source.source_event_id,
        event_type="financial.collaboration.success_final",
    )
    async with ledger.transaction() as session:
        await service.handle(final, session=session)
        assert (
            await ledger.get_issue(original.basis.business_key, session=session)
            == original
        )


@pytest.mark.asyncio
async def test_work_brief_and_financial_terms_are_independent():
    repo, ledger, service, _, event, _, _ = setup()
    repo.snapshot = replace(
        repo.snapshot,
        record=replace(
            repo.snapshot.record,
            terms_reference="brief:client agreed content and due date",
        ),
    )
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
    assert len(ledger.records) == 1


def case_for(repo, at=START + timedelta(hours=2)):
    from ugc_bot.application.work_entitlement_ports import WorkDisputeCase

    scope = repo.snapshot.scope
    return WorkDisputeCase(
        uuid4(),
        scope.assignment_id,
        scope.paid_item_id,
        uuid4(),
        scope.client_id,
        "actual other-party dispute",
        at,
    )


@pytest.mark.asyncio
async def test_historical_dispute_still_blocks_existing_item_earnings():
    repo, ledger, service, clock, event, partner, _ = setup()
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
    repo.dispute = case_for(repo)
    repo.snapshot = replace(
        repo.snapshot, scope=replace(repo.snapshot.scope, valid_to=clock.at)
    )
    later = replace(event, event_id=uuid4())
    async with ledger.transaction() as session:
        await service.handle(later, session=session)
        balances = await ledger.read_projection(partner, "RUB", session=session)
    assert balances["blocked"] == 5000 and balances["pending"] == 0
    assert repo.receipts[later.event_id]["assessment"]["case_id"]


@pytest.mark.asyncio
async def test_future_dispute_fails_without_creating_an_obligation():
    repo, ledger, service, clock, event, _, _ = setup()
    repo.dispute = case_for(repo, clock.at + timedelta(seconds=1))
    with pytest.raises(ValueError, match="work_fact_in_future"):
        async with ledger.transaction() as session:
            await service.handle(event, session=session)
    assert not ledger.records and not ledger.movements
    assert not repo.receipts


@pytest.mark.asyncio
async def test_expiry_preserves_client_ground_and_cancels_creator_only():
    from ugc_bot.application.financial_ports import IssueBasis

    repo, ledger, service, clock, event, partner, _ = setup()
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
        creator = next(iter(ledger.records.values()))
        client_basis = replace(
            creator.basis,
            business_key="independent-client",
            kind="client_referral",
            assignment_id=None,
            referred_user_id=repo.snapshot.scope.client_id,
            verified_count=None,
        )
        assert isinstance(client_basis, IssueBasis)
        await service.ledger.issue(
            client_basis, recorded_at=clock.at, session=session
        )
    work = replace(
        repo.snapshot.record.collaboration,
        state=CollaborationState.UNCONFIRMED_EXPIRED,
    )
    clock.at = work.first_claim_deadline
    repo.snapshot = replace(
        repo.snapshot, record=replace(repo.snapshot.record, collaboration=work)
    )
    async with ledger.transaction() as session:
        await service.handle(replace(event, event_id=uuid4()), session=session)
        balances = await ledger.read_projection(partner, "RUB", session=session)
    assert balances["pending"] == 5000 and balances["cancelled"] == 5000
    cancellation = next(
        m for m in ledger.movements.values() if m.bucket_to == "cancelled"
    )
    assert (
        cancellation.source_entry_id
        == ledger.entry_ids[creator.movement.operation_key]
    )


@pytest.mark.asyncio
async def test_missing_manager_proof_keeps_explicit_assessment():
    repo, ledger, service, _, event, _, _ = setup(final=True)
    repo.snapshot = replace(repo.snapshot, manager_linked=False)

    # Maturity proof itself is covered by the successful work test above.
    async def settle(*args, **kwargs):
        return None

    service._settle = settle
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
    assert not any(
        r.basis.kind == "management" for r in ledger.records.values()
    )
    assert (
        repo.receipts[event.event_id]["assessment"]["manager"]
        == "manager_membership_at_success_unproven"
    )
    assert repo.receipts[event.event_id]["assessment"]["potential_reasons"] == [
        "manager_membership_at_success_unproven"
    ]


@pytest.mark.asyncio
async def test_completed_inbox_is_idempotent_but_checks_source_payload():
    repo, ledger, service, _, event, _, calls = setup()
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
        before = len(ledger.movements), len(calls)
        await service.handle(event, session=session)
        assert (len(ledger.movements), len(calls)) == before
        repo.receipts[event.event_id]["source_hash"] = "b" * 64
        with pytest.raises(ValueError, match="idempotency_payload_conflict"):
            await service.handle(event, session=session)


@pytest.mark.asyncio
async def test_unknown_type_never_takes_financial_locks():
    _, ledger, service, _, event, _, calls = setup()
    with pytest.raises(ValueError, match="work_source_unsupported"):
        async with ledger.transaction() as session:
            await service.handle(
                replace(event, event_type="financial.unknown"), session=session
            )
    assert not calls and not ledger.records


@pytest.mark.asyncio
async def test_inbox_is_rechecked_after_waiting_for_item_lock(monkeypatch):
    repo, ledger, service, _, event, _, calls = setup()
    original = repo.get_receipt

    async def after_wait(event_id, *, session):
        if "item" in calls:
            return {"source_hash": repo.snapshot.source_hash}
        return await original(event_id, session=session)

    monkeypatch.setattr(repo, "get_receipt", after_wait)
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
    assert not ledger.records and not repo.receipts


@pytest.mark.asyncio
async def test_new_historical_recipient_requires_whole_transaction_retry(
    monkeypatch,
):
    repo, ledger, service, _, event, _, _ = setup()
    original = service.history.resolve_direct_binding
    reads = 0

    async def changed(creator, as_of, *, session):
        nonlocal reads
        reads += 1
        fact = await original(creator, as_of, session=session)
        return replace(fact, referrer_user_id=uuid4()) if reads == 2 else fact

    monkeypatch.setattr(service.history, "resolve_direct_binding", changed)
    with pytest.raises(
        ValueError, match="financial_scope_changed_retry_required"
    ):
        async with ledger.transaction() as session:
            await service.handle(event, session=session)
    assert not ledger.records and not repo.receipts


@pytest.mark.asyncio
async def test_new_existing_ground_requires_retry_before_mutation(monkeypatch):
    from ugc_bot.application.financial_ports import ActiveEconomicGround

    repo, ledger, service, _, event, _, calls = setup()

    async def grounds(item, kind, *, session):
        if "item" in calls and kind == "client_referral":
            return (
                ActiveEconomicGround(
                    uuid4(), "new-client", uuid4(), "RUB", item, kind
                ),
            )
        return ()

    monkeypatch.setattr(ledger, "list_item_grounds", grounds)
    with pytest.raises(
        ValueError, match="financial_scope_changed_retry_required"
    ):
        async with ledger.transaction() as session:
            await service.handle(event, session=session)
    assert not ledger.records and not repo.receipts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad", ["new_capture", "new_actor", "source", "scope", "funding", "terms"]
)
async def test_scope_and_funding_are_rechecked_under_item_barrier(
    monkeypatch, bad
):
    repo, ledger, service, _, event, _, calls = setup()
    before = repo.snapshot
    if bad == "new_capture":
        changed = replace(
            before, capture=replace(before.capture, payment_id=uuid4())
        )
    elif bad == "new_actor":
        changed = replace(
            before, scope=replace(before.scope, manager_id=uuid4())
        )
    elif bad == "source":
        changed = replace(before, source_hash="c" * 64)
    elif bad == "scope":
        changed = replace(
            before, scope=replace(before.scope, selection_funded=False)
        )
    elif bad == "terms":
        changed = replace(
            before, record=replace(before.record, terms_reference=" ")
        )
    else:
        item = replace(before.capture.items[0], accompaniment_minor=1)
        capture = replace(before.capture, items=(item,))
        before = changed = replace(before, capture=capture)

    async def load(event, *, session):
        return changed if "item" in calls else before

    monkeypatch.setattr(repo, "load", load)
    with pytest.raises(
        ValueError,
        match="financial_scope_changed_retry_required|work_scope_mismatch|work_funding_mismatch",
    ):
        async with ledger.transaction() as session:
            await service.handle(event, session=session)
    assert not ledger.records and not repo.receipts


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["grade", "registration", "unknown"])
async def test_unknown_or_wrong_history_never_becomes_zero_or_standard(
    monkeypatch, bad
):
    from ugc_bot.domain.identity_history import IdentityHistoryUnavailable

    repo, ledger, service, _, event, _, _ = setup()
    original = service.history.count_verified_direct_creators
    original_binding = service.history.resolve_direct_binding

    async def grade(recipient, at, *, session):
        if bad == "unknown":
            raise IdentityHistoryUnavailable("synthetic_uncovered_payment")
        fact = await original(recipient, at, session=session)
        return (
            replace(fact, as_of=at + timedelta(seconds=1))
            if bad == "grade"
            else fact
        )

    async def binding(creator, at, *, session):
        fact = await original_binding(creator, at, session=session)
        return (
            replace(fact, registered_at=None) if bad == "registration" else fact
        )

    monkeypatch.setattr(
        service.history, "count_verified_direct_creators", grade
    )
    monkeypatch.setattr(service.history, "resolve_direct_binding", binding)
    with pytest.raises(
        ValueError,
        match="work_grade_scope_mismatch|historical_registration_required|synthetic_uncovered_payment",
    ):
        async with ledger.transaction() as session:
            await service.handle(event, session=session)
    assert not ledger.records and not ledger.potentials and not repo.receipts


@pytest.mark.asyncio
async def test_missing_immutable_schedule_rolls_back_new_earnings():
    repo, ledger, service, _, event, _, _ = setup(final=True)
    with pytest.raises(ValueError, match="work_maturity_schedule_missing"):
        async with ledger.transaction() as session:
            await service.handle(event, session=session)
    assert not ledger.records and not ledger.movements and not repo.receipts


@pytest.mark.asyncio
async def test_readonly_guard_rejects_an_unresolved_actual_case():
    from ugc_bot.application.services.work_financial_guard import (
        WorkFinancialGuard,
    )

    repo, ledger, _, _, _, _, _ = setup()
    guard = WorkFinancialGuard(repo)
    async with ledger.transaction() as session:
        await guard.require_clear(
            repo.snapshot.scope.paid_item_id, session=session
        )
        repo.dispute = case_for(repo)
        with pytest.raises(ValueError, match="work_disputed"):
            await guard.require_clear(
                repo.snapshot.scope.paid_item_id, session=session
            )


@pytest.mark.asyncio
async def test_absent_manager_keeps_qualification_as_potential():
    repo, ledger, service, _, event, _, _ = setup(final=True)
    repo.snapshot = replace(
        repo.snapshot,
        scope=replace(repo.snapshot.scope, manager_id=None),
        record=replace(
            repo.snapshot.record,
            collaboration=replace(
                repo.snapshot.record.collaboration, manager_id=None
            ),
        ),
    )

    async def settle(*args, **kwargs):
        return None

    service._settle = settle
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
    assert (
        repo.receipts[event.event_id]["assessment"]["manager"]
        == "actual_manager_not_assigned"
    )
    assert all(r.basis.kind != "management" for r in ledger.records.values())


@pytest.mark.asyncio
async def test_dispute_freezes_free_balance_and_flags_existing_reservation():
    from ugc_bot.application.financial_ports import JournalMovement

    repo, ledger, service, clock, event, partner, _ = setup()
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
        issued = next(iter(ledger.records.values()))
        reservation = JournalMovement(
            obligation_id=issued.obligation_id,
            operation_key="existing-reservation",
            event_id="reservation-event",
            movement_type="transfer",
            amount_minor=2000,
            currency="RUB",
            effective_at=clock.at,
            recorded_at=clock.at,
            actor_id=partner,
            reason="existing reservation",
            bucket_from="pending",
            bucket_to="reserved",
            request_id=uuid4(),
            allocation_id=uuid4(),
        )
        await ledger.append(reservation, session=session)
        await ledger.apply_projection(reservation, session=session)
    repo.dispute = case_for(repo)
    later = replace(event, event_id=uuid4())
    async with ledger.transaction() as session:
        await service.handle(later, session=session)
        balances = await ledger.read_projection(partner, "RUB", session=session)
    assert balances["reserved"] == 2000 and balances["blocked"] == 3000
    assert repo.receipts[later.event_id]["assessment"][
        "manual_review_required"
    ] == [str(issued.obligation_id)]


@pytest.mark.asyncio
async def test_expiry_of_another_assignment_keeps_historical_ground():
    repo, ledger, service, clock, event, partner, _ = setup()
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
    replacement = uuid4()
    work = replace(
        repo.snapshot.record.collaboration,
        assignment_id=replacement,
        state=CollaborationState.UNCONFIRMED_EXPIRED,
    )
    repo.snapshot = replace(
        repo.snapshot,
        scope=replace(repo.snapshot.scope, assignment_id=replacement),
        record=replace(repo.snapshot.record, collaboration=work),
    )
    clock.at = work.first_claim_deadline
    async with ledger.transaction() as session:
        await service.handle(replace(event, event_id=uuid4()), session=session)
        balances = await ledger.read_projection(partner, "RUB", session=session)
    assert balances["pending"] == 5000 and balances["cancelled"] == 0

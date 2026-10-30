"""Selection closes from actual facts before window and hold release."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from tests.application.services.test_client_entitlement_service import scenario
from ugc_bot.domain.refund_rules import RefundRules

AT = datetime(2026, 10, 23, tzinfo=timezone.utc)


def components():
    try:
        from ugc_bot.application.selection_maturity_ports import (
            SelectionPosition,
            SelectionSnapshot,
        )
        from ugc_bot.application.services.selection_maturity_service import (
            SelectionMaturityService,
        )
    except ModuleNotFoundError:
        pytest.fail("Selection delivery/closure maturity is not implemented")
    return SelectionPosition, SelectionSnapshot, SelectionMaturityService


def test_selection_positions_do_not_accept_invented_resolution_facts():
    Position, _, _ = components()
    with pytest.raises(ValueError):
        Position(uuid4(), delivered_at=AT, delivery_id=None)


@pytest.mark.asyncio
async def test_delivered_selection_stays_pending_until_closed_window_and_hold():
    Position, Snapshot, Service = components()
    issuer, capture_source, ledger, _, _, event = await scenario()
    async with ledger.transaction() as session:
        await issuer.handle(event, session=session)
    original = next(iter(ledger.records.values()))
    capture = capture_source.capture
    at = capture.captured_at + timedelta(hours=1)
    rules = RefundRules(
        86400, "item_delivered", "all_positions_resolved", (), "retain_earned"
    )
    snapshot = Snapshot(
        capture.order_id,
        capture.client_id,
        capture.payment_id,
        replace(capture.policy, refund_rules=rules),
        capture.captured_at,
        (
            Position(
                capture.items[0].paid_item_id,
                delivered_at=at,
                delivery_id=uuid4(),
            ),
        ),
    )

    class Clock:
        def now(self):
            return self.at

    class Repo:
        closed = None
        schedules = {}
        source = snapshot

        async def load(self, order_id, *, session):
            return self.source

        async def lock_order(self, order_id, *, session):
            pass

        async def get_closure(self, order_id, *, session):
            return self.closed

        async def save_closure(self, closure, *, session):
            self.closed = closure
            return closure

        async def save_schedule(self, schedule, *, session):
            self.schedules[schedule.paid_item_id] = schedule
            ledger.selection_maturity_sources[original.obligation_id] = schedule
            return schedule

        async def require_clear(self, item_id, *, session):
            pass

    repo, clock = Repo(), Clock()
    clock.at = at
    service = Service(repo, issuer.ledger, clock)
    async with ledger.transaction() as session:
        await service.refresh(capture.order_id, session=session)
        money = await ledger.read_projection(
            original.basis.recipient_id, "RUB", session=session
        )
    assert money["pending"] == original.movement.amount_minor
    assert money["available"] == 0
    clock.at = at + timedelta(days=1)
    async with ledger.transaction() as session:
        await service.refresh(capture.order_id, session=session)
        money = await ledger.read_projection(
            original.basis.recipient_id, "RUB", session=session
        )
    assert money["hold"] == original.movement.amount_minor
    clock.at += timedelta(days=14)
    async with ledger.transaction() as session:
        await service.refresh(capture.order_id, session=session)
        money = await ledger.read_projection(
            original.basis.recipient_id, "RUB", session=session
        )
        await service.refresh(capture.order_id, session=session)
    assert money["available"] == original.movement.amount_minor
    assert len(repo.schedules) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "block_reason",
    ["work_disputed", "correction_unresolved", "correction_component_refunded"],
)
async def test_public_policy_matures_each_delivered_position_independently(
    block_reason,
):
    from ugc_bot.application.entitlement_ports import FundedSelection

    Position, Snapshot, Service = components()
    issuer, source, ledger, _, _, event = await scenario()
    second = FundedSelection(uuid4(), 50000, 120000)
    policy = replace(
        source.capture.policy,
        selection_refund_window=timedelta(days=7),
        maturity_mode="per_item_v1",
    )
    source.capture = replace(
        source.capture,
        policy=policy,
        items=source.capture.items + (second,),
    )
    async with ledger.transaction() as session:
        await issuer.handle(event, session=session)
    capture = source.capture
    first = capture.items[0]
    delivered_at = capture.captured_at + timedelta(hours=1)
    snapshot = Snapshot(
        capture.order_id,
        capture.client_id,
        capture.payment_id,
        policy,
        capture.captured_at,
        (
            Position(first.paid_item_id, delivered_at, uuid4()),
            Position(second.paid_item_id),
        ),
    )

    class Clock:
        at = delivered_at

        def now(self):
            return self.at

    class Repo:
        schedules = {}
        current = snapshot
        blocked = set()

        async def load(self, order_id, *, session):
            return self.current

        async def lock_order(self, order_id, *, session):
            pass

        async def save_schedule(self, schedule, *, session):
            prior = self.schedules.setdefault(schedule.paid_item_id, schedule)
            assert prior == schedule
            for original in ledger.records.values():
                if original.basis.paid_item_id == schedule.paid_item_id:
                    ledger.selection_maturity_sources[
                        original.obligation_id
                    ] = schedule
            return prior

        async def require_clear(self, item_id, *, session):
            if item_id in self.blocked:
                raise ValueError(block_reason)

    repo, clock = Repo(), Clock()
    service = Service(repo, issuer.ledger, clock)

    async def refresh(at):
        clock.at = at
        async with ledger.transaction() as session:
            await service.refresh(capture.order_id, session=session)
            return await ledger.read_projection(
                capture.captured_referrer_id, "RUB", session=session
            )

    initial = await refresh(delivered_at)
    assert initial["pending"] == 3000
    assert initial["hold"] == initial["available"] == 0
    schedule = repo.schedules[first.paid_item_id]
    assert schedule.closure_id is None
    assert schedule.refund_deadline_at == delivered_at + timedelta(days=7)
    assert schedule.hold_started_at == delivered_at + timedelta(days=7)
    assert schedule.release_at == delivered_at + timedelta(days=21)
    assert second.paid_item_id not in repo.schedules

    before = await refresh(delivered_at + timedelta(days=7, seconds=-1))
    assert before["pending"] == 3000 and before["hold"] == 0
    on_hold = await refresh(delivered_at + timedelta(days=7))
    assert on_hold["pending"] == 1500 and on_hold["hold"] == 1500
    before_release = await refresh(
        delivered_at + timedelta(days=21, seconds=-1)
    )
    assert before_release["hold"] == 1500 and before_release["available"] == 0
    released = await refresh(delivered_at + timedelta(days=21))
    assert released["pending"] == 1500 and released["available"] == 1500
    assert await refresh(delivered_at + timedelta(days=21)) == released
    assert len(repo.schedules) == 1
    repo.current = replace(
        snapshot,
        positions=(
            snapshot.positions[0],
            Position(second.paid_item_id, delivered_at, uuid4()),
        ),
    )
    repo.blocked.add(second.paid_item_id)
    disputed = await refresh(delivered_at + timedelta(days=21))
    assert disputed["pending"] == 1500 and disputed["available"] == 1500
    assert second.paid_item_id not in repo.schedules
    repo.blocked.clear()
    cleared = await refresh(delivered_at + timedelta(days=21))
    assert cleared["pending"] == 0 and cleared["available"] == 3000
    assert len(repo.schedules) == 2


@pytest.mark.asyncio
async def test_partial_selection_or_accompaniment_refunds_do_not_stop_loading():
    from ugc_bot.infrastructure.db.repositories.selection_maturity import (
        SqlAlchemySelectionMaturityRepository,
    )

    payment_id = uuid4()
    refund = [
        {
            "component": "accompaniment",
            "payment_id": payment_id,
            "refund_minor": 120000,
        },
        {
            "component": "selection",
            "payment_id": payment_id,
            "refund_minor": 20000,
        },
    ]
    result = await SqlAlchemySelectionMaturityRepository._refund_resolution(
        None,
        {"selection_minor": 50000},
        refund,
        payment_id,
        allow_partial=True,
    )
    assert result == (None, None)


@pytest.mark.asyncio
async def test_legacy_policy_still_requires_entire_order_resolved():
    Position, Snapshot, Service = components()
    issuer, source, ledger, _, _, event = await scenario()
    async with ledger.transaction() as session:
        await issuer.handle(event, session=session)
    capture = source.capture
    delivered_at = capture.captured_at + timedelta(hours=1)
    rules = RefundRules(
        86400, "item_delivered", "all_positions_resolved", (), "retain_earned"
    )
    snapshot = Snapshot(
        capture.order_id,
        capture.client_id,
        capture.payment_id,
        replace(capture.policy, refund_rules=rules),
        capture.captured_at,
        (
            Position(capture.items[0].paid_item_id, delivered_at, uuid4()),
            Position(uuid4()),
        ),
    )

    class Clock:
        def now(self):
            return delivered_at + timedelta(days=21)

    class Repo:
        async def load(self, order_id, *, session):
            return snapshot

        async def lock_order(self, order_id, *, session):
            pass

        async def get_closure(self, order_id, *, session):
            return None

    service = Service(Repo(), issuer.ledger, Clock())
    async with ledger.transaction() as session:
        result = await service.refresh(capture.order_id, session=session)
        balance = await ledger.read_projection(
            capture.captured_referrer_id, "RUB", session=session
        )
    assert result["state"] == "partially_fulfilled"
    assert balance["pending"] == 1500
    assert balance["available"] == 0


@pytest.mark.asyncio
async def test_financial_review_blocks_only_its_own_position():
    from ugc_bot.application.entitlement_ports import FundedSelection
    from ugc_bot.application.financial_ports import JournalMovement

    Position, Snapshot, Service = components()
    issuer, source, ledger, _, _, event = await scenario()
    policy = replace(
        source.capture.policy,
        selection_refund_window=timedelta(days=7),
        maturity_mode="per_item_v1",
    )
    second = FundedSelection(uuid4(), 50000, 120000)
    source.capture = replace(
        source.capture, policy=policy, items=source.capture.items + (second,)
    )
    async with ledger.transaction() as session:
        await issuer.handle(event, session=session)
    capture = source.capture
    blocked = next(
        entry
        for entry in ledger.records.values()
        if entry.basis.paid_item_id == second.paid_item_id
    )
    delivered_at = capture.captured_at + timedelta(hours=1)
    snapshot = Snapshot(
        capture.order_id,
        capture.client_id,
        capture.payment_id,
        policy,
        capture.captured_at,
        tuple(
            Position(item.paid_item_id, delivered_at, uuid4())
            for item in capture.items
        ),
    )
    async with ledger.transaction() as session:
        await issuer.ledger.transfer(
            blocked.basis.business_key,
            JournalMovement(
                obligation_id=blocked.obligation_id,
                operation_key="partial-block",
                event_id="review",
                movement_type="transfer",
                amount_minor=500,
                currency="RUB",
                effective_at=delivered_at,
                recorded_at=delivered_at,
                actor_id=None,
                reason="review",
                actor_kind="system",
                system_actor="financial_review",
                bucket_from="pending",
                bucket_to="blocked",
                case_id=uuid4(),
            ),
            now=delivered_at,
            session=session,
        )

    class Clock:
        def now(self):
            return delivered_at + timedelta(days=21)

    class Repo:
        async def load(self, order_id, *, session):
            return snapshot

        async def lock_order(self, order_id, *, session):
            pass

        async def save_schedule(self, schedule, *, session):
            for original in ledger.records.values():
                if original.basis.paid_item_id == schedule.paid_item_id:
                    ledger.selection_maturity_sources[
                        original.obligation_id
                    ] = schedule
            return schedule

        async def require_clear(self, item_id, *, session):
            pass

    service = Service(Repo(), issuer.ledger, Clock())
    async with ledger.transaction() as session:
        await service.refresh(capture.order_id, session=session)
        balance = await ledger.read_projection(
            capture.captured_referrer_id, "RUB", session=session
        )
    assert balance["available"] == 1500
    assert balance["pending"] == 1000
    assert balance["blocked"] == 500

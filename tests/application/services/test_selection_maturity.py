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

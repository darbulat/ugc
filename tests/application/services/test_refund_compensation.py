"""A proven full source refund cancels original pending commission once."""

from datetime import timedelta
from uuid import uuid4

import pytest

from tests.helpers.correction_commands import NOW, U, environment
from ugc_bot.application.financial_ports import IssueBasis
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.infrastructure.memory_financial_ledger import (
    InMemoryFinancialLedgerRepository,
)


@pytest.mark.asyncio
async def test_full_refund_compensates_original_pending():
    try:
        from ugc_bot.application.services.refund_compensation_service import (
            SelectionRefundCompensationService,
        )
    except ModuleNotFoundError:
        pytest.fail("Actual source-linked refund compensation is missing")
    source = environment().repo.scope
    ledger = InMemoryFinancialLedgerRepository()
    service = FinancialLedgerService(ledger)
    item = source.bundle.components[0]
    key = f"client-selection:{source.payment_id}:{item.paid_item_id}"
    basis = IssueBasis(
        business_key=key,
        kind="client_referral",
        recipient_id=U[2],
        paid_item_id=item.paid_item_id,
        order_id=source.order_id,
        assignment_id=None,
        referred_user_id=source.client_id,
        payment_id=source.payment_id,
        currency="RUB",
        base_minor=50000,
        rate_bps=1000,
        policy_version="approved:test",
        snapshot_at=source.captured_at,
        registered_at=source.captured_at - timedelta(days=2),
        verified_count=None,
        event_id=str(source.capture_id),
        reason="actual captured selection",
        actor_id=source.client_id,
    )

    class Repo:
        rows = {}

        async def refund_application(self, match_id, *, session):
            return self.rows.get("applications")

        async def component_refund_total(self, allocation, *, session):
            return 0

        async def liability_refund_total(self, obligation, *, session):
            return 0

        async def append_fact(self, name, row, *, session):
            self.rows[name] = dict(row)

    repo = Repo()
    producer = SelectionRefundCompensationService(repo, service)
    match = dict(
        match_id=str(uuid4()),
        intent_id=str(uuid4()),
        case_id=str(uuid4()),
        order_id=str(source.order_id),
        payment_id=str(source.payment_id),
        capture_id=str(source.capture_id),
        source_hash=source.source_hash,
        amount_minor=50000,
        currency="RUB",
    )
    async with ledger.transaction() as session:
        original = await service.issue(basis, recorded_at=NOW, session=session)
        result = await producer.apply(
            source, match, actor_id=U[1], now=NOW, session=session
        )
        money = await ledger.read_projection(U[2], "RUB", session=session)
        again = await producer.apply(
            source, match, actor_id=U[1], now=NOW, session=session
        )
        assert await ledger.get_issue(key, session=session) == original
    assert result == again and result["applied"] is True
    assert money["pending"] == 0 and money["cancelled"] == 5000
    reversal = next(
        m for m in ledger.movements.values() if m.movement_type == "reversal"
    )
    assert (
        reversal.source_entry_id
        == ledger.entry_ids[original.movement.operation_key]
    )
    assert reversal.refund_id == repo.rows["applications"]["application_id"]
    assert reversal.case_id == repo.rows["applications"]["case_id"]
    assert (
        repo.rows["liabilities"]["movement_id"]
        == ledger.entry_ids[reversal.operation_key]
    )

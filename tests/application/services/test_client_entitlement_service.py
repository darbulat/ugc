"""Client coordinator retry/failure decisions use real history and ledger."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from tests.application.services.test_creator_identity_history import (
    START,
    setup_history,
)
from tests.helpers.factories import create_test_user
from ugc_bot.application.entitlement_ports import ClientCapture, FundedSelection
from ugc_bot.application.financial_ports import IssueBasis
from ugc_bot.application.services.client_entitlement_service import (
    ClientEntitlementService,
)
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicy,
)
from ugc_bot.domain.entities import OutboxEvent, UserReferralBinding
from ugc_bot.domain.enums import OutboxEventStatus
from ugc_bot.infrastructure.memory_financial_ledger import (
    InMemoryFinancialLedgerRepository,
)
from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository


class Clock:
    def now(self):
        return START


class NoOverrides:
    async def select_effective_override(self, *args, **kwargs):
        return None


class CaptureSource:
    """Port fake: SQL source authority has separate actual PG tests."""

    def __init__(self, capture):
        self.capture = capture
        self.receipt = None
        self.change_under_lock = None

    async def source_hash(self, event, *, session):
        return self.capture.source_hash

    async def load_capture(self, event, *, session):
        return self.capture

    async def lock_funding(self, capture, *, session):
        if self.change_under_lock is not None:
            await self.change_under_lock()

    async def get_receipt(self, event_id, *, session):
        return self.receipt

    async def save_receipt(self, capture, assessment, *, recorded_at, session):
        self.receipt = {
            "source_hash": capture.source_hash,
            "assessment": assessment,
        }


async def scenario():
    history_service, history, _, bindings, _ = setup_history()
    users = InMemoryUserRepository(identity_history=history)
    client = await create_test_user(
        users, created_at=START - timedelta(days=400)
    )
    partner = uuid4()
    await bindings.save(UserReferralBinding(partner, client.user_id, START))
    event_id, order_id, payment_id = uuid4(), uuid4(), uuid4()
    policy = FinancialPolicy(
        "approved:test",
        partner,
        START - timedelta(days=2),
        START - timedelta(days=1),
        timedelta(days=1),
        frozenset({client.user_id}),
        "terms:test",
    )
    capture = ClientCapture(
        event_id,
        order_id,
        payment_id,
        client.user_id,
        policy,
        START,
        client.created_at,
        partner,
        (FundedSelection(uuid4(), 50000, 120000),),
        "a" * 64,
    )
    source = CaptureSource(capture)
    ledger_repo = InMemoryFinancialLedgerRepository()
    service = ClientEntitlementService(
        source,
        FinancialLedgerService(ledger_repo),
        history_service,
        NoOverrides(),
        Clock(),
    )
    event = OutboxEvent(
        event_id,
        "financial.client_snapshot_requested",
        str(order_id),
        "order",
        {},
        OutboxEventStatus.PENDING,
        START,
        None,
        0,
        None,
    )
    return service, source, ledger_repo, history, bindings, event


@pytest.mark.asyncio
async def test_changed_funding_under_lock_requires_retry_before_issuance():
    service, source, ledger, _, _, event = await scenario()

    async def change():
        item = source.capture.items[0]
        source.capture = replace(
            source.capture, items=(replace(item, selection_minor=50001),)
        )

    source.change_under_lock = change
    with pytest.raises(ValueError, match="scope_changed_retry"):
        async with ledger.transaction() as session:
            await service.handle(event, session=session)
    assert ledger.records == ledger.movements == ledger.potentials == {}
    assert source.receipt is None
    assert ledger.wallets == {}


@pytest.mark.asyncio
async def test_new_historical_recipient_under_barrier_requires_whole_retry():
    service, source, ledger, _, bindings, event = await scenario()

    async def committed_writer():
        # Same observed timestamp models an earlier in-flight write becoming
        # visible after discovery. PostgreSQL concurrency is tested separately.
        await bindings.save(
            UserReferralBinding(
                uuid4(),
                source.capture.client_id,
                START,
            )
        )

    source.change_under_lock = committed_writer
    with pytest.raises(ValueError, match="scope_changed_retry"):
        async with ledger.transaction() as session:
            await service.handle(event, session=session)
    assert ledger.records == ledger.movements == ledger.potentials == {}
    assert source.receipt is None
    assert ledger.wallets == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["registered_at", "captured_referrer_id"])
async def test_capture_identity_mismatch_never_issues_or_audits_money(field):
    service, source, ledger, _, _, event = await scenario()
    value = (
        source.capture.registered_at - timedelta(days=1)
        if field == "registered_at"
        else uuid4()
    )
    source.capture = replace(source.capture, **{field: value})
    with pytest.raises(ValueError, match="capture_attribution_mismatch"):
        async with ledger.transaction() as session:
            await service.handle(event, session=session)
    assert ledger.records == ledger.movements == ledger.potentials == {}
    assert source.receipt is None


@pytest.mark.asyncio
async def test_pre_cutover_capture_is_unknown_without_potential_zero_receipt():
    service, source, ledger, _, _, event = await scenario()
    source.capture = replace(
        source.capture, captured_at=START - timedelta(seconds=1)
    )
    with pytest.raises(ValueError, match="coverage"):
        async with ledger.transaction() as session:
            await service.handle(event, session=session)
    assert ledger.records == ledger.movements == ledger.potentials == {}
    assert source.receipt is None


@pytest.mark.asyncio
async def test_existing_other_economic_ground_cannot_be_issued_again():
    service, source, ledger, _, _, event = await scenario()
    capture = source.capture
    basis = IssueBasis(
        business_key="another-economic-ground",
        kind="client_referral",
        recipient_id=capture.captured_referrer_id,
        paid_item_id=capture.items[0].paid_item_id,
        order_id=capture.order_id,
        assignment_id=None,
        referred_user_id=capture.client_id,
        payment_id=capture.payment_id,
        currency="RUB",
        base_minor=50000,
        rate_bps=300,
        policy_version=capture.policy.version,
        snapshot_at=START,
        registered_at=capture.registered_at,
        verified_count=None,
        event_id=str(event.event_id),
        reason="existing confirmed capture",
        actor_id=capture.client_id,
    )
    async with ledger.transaction() as session:
        await FinancialLedgerService(ledger).issue(
            basis,
            recorded_at=START,
            session=session,
        )
    old_records = dict(ledger.records)
    old_movements = dict(ledger.movements)
    with pytest.raises(ValueError, match="client_economic_ground_exists"):
        async with ledger.transaction() as session:
            await service.handle(event, session=session)
    assert ledger.records == old_records
    assert ledger.movements == old_movements
    assert source.receipt is None

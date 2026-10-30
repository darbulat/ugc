"""Published prices and order size survive configuration changes."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from tests.application.services.test_order_intake_service import values
from tests.application.services.test_refund_policy_publication import (
    Clock,
    Repository,
    Transactions,
    config,
    inputs,
)
from ugc_bot.application.services.financial_policy_publication import (
    FinancialPolicyDraft,
    FinancialPolicyPublicationService,
)
from ugc_bot.application.services.paid_item_service import build_quote
from ugc_bot.config import AppConfig
from ugc_bot.domain.order_intake import OrderIntakeCommand


@pytest.mark.parametrize("count", [10, 20, 30, 50, 100, 200])
def test_requested_count_controls_manager_positions_and_hash(count):
    command = OrderIntakeCommand(
        **(values() | {"position_count": count, "service_mode": "with_manager"})
    )
    assert command.accompaniment_ordinals == frozenset(range(1, count + 1))
    changed = replace(
        command,
        position_count=10 if count != 10 else 20,
        accompaniment_ordinals=frozenset({1}),
    )
    assert command.payload_hash != changed.payload_hash


@pytest.mark.parametrize("count", [9, 201, 10.5, True, "10"])
def test_invalid_count_is_rejected_before_quote(count):
    with pytest.raises(ValueError, match="position_count"):
        OrderIntakeCommand(**(values() | {"position_count": count}))


@pytest.mark.parametrize("count,ordinal", [(10, 11), (200, 201)])
def test_accompaniment_is_bounded_by_actual_order(count, ordinal):
    with pytest.raises(ValueError, match="accompaniment"):
        OrderIntakeCommand(
            **(
                values()
                | {
                    "position_count": count,
                    "service_mode": "with_manager",
                    "accompaniment_ordinals": frozenset({ordinal}),
                }
            )
        )


@pytest.mark.parametrize(
    "selection,accompaniment",
    [(50000, 120000), (50000, 170000), (79000, 60000), (79000, 60001)],
)
@pytest.mark.asyncio
async def test_publication_freezes_prices_and_changed_version_conflicts(
    selection, accompaniment
):
    cfg = config(
        FINANCIAL_SELECTION_PRICE_MINOR=selection,
        FINANCIAL_ACCOMPANIMENT_PRICE_MINOR=accompaniment,
    )
    chosen = FinancialPolicyDraft.from_environment(cfg, **inputs())
    actor = uuid4()
    service = FinancialPolicyPublicationService(
        Repository(), Transactions(), Clock()
    )
    published = await service.publish(chosen, actor_id=actor)
    assert (published.selection_minor, published.accompaniment_minor) == (
        selection,
        accompaniment,
    )
    assert chosen.to_document()["selection_minor"] == selection
    assert chosen.to_document()["accompaniment_minor"] == accompaniment
    cfg.selection_price_minor = selection + 1
    changed = FinancialPolicyDraft.from_environment(
        cfg, **{k: getattr(chosen, k) for k in inputs()}
    )
    with pytest.raises(ValueError, match="policy_version_conflict"):
        await service.publish(changed, actor_id=actor)
    assert published.selection_minor == selection


@pytest.mark.parametrize(
    "selection,accompaniment",
    [
        (0, 120000),
        (-1, 120000),
        (1.5, 120000),
        ("", 120000),
        (True, 120000),
        (2**63, 120000),
        (50000, 59999),
        (50000, "120000.0"),
        (50000, None),
    ],
)
def test_invalid_or_partial_tariff_cannot_publish(selection, accompaniment):
    with pytest.raises(ValueError):
        cfg = config(
            FINANCIAL_SELECTION_PRICE_MINOR=selection,
            FINANCIAL_ACCOMPANIMENT_PRICE_MINOR=accompaniment,
        )
        FinancialPolicyDraft.from_environment(cfg, **inputs())


def test_new_publication_requires_explicit_prices():
    cfg = config(
        FINANCIAL_SELECTION_PRICE_MINOR=None,
        FINANCIAL_ACCOMPANIMENT_PRICE_MINOR=None,
    )
    with pytest.raises(ValueError, match="prices_required"):
        FinancialPolicyDraft.from_environment(cfg, **inputs())


def test_general_config_loader_keeps_tariff_settings():
    cfg = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "FINANCIAL_SELECTION_PRICE_MINOR": "79000",
            "FINANCIAL_ACCOMPANIMENT_PRICE_MINOR": "170000",
        }
    )
    assert (
        cfg.financial.selection_price_minor,
        cfg.financial.accompaniment_price_minor,
    ) == (79000, 170000)


def test_quote_ten_positions_and_three_managed_has_exact_total():
    quote = build_quote(
        order_id=uuid4(),
        count=10,
        accompaniment_ordinals=frozenset({1, 2, 3}),
        currency="RUB",
        policy_version="tariff",
        selection_due_at=Clock().now() + timedelta(days=1),
        client_contact_reference="contact",
        terms_reference="terms",
        idempotency_key="ten",
        selection_minor=50000,
        accompaniment_minor=120000,
    )
    assert len(quote.items) == 10
    assert quote.selection_base_minor == 500000
    assert quote.total_minor == 860000


@pytest.mark.asyncio
async def test_new_tariff_work_earns_saved_selection_and_fixed_manager_reward():
    from tests.application.services.test_work_entitlement_service import setup

    repo, ledger, service, _, event, _, _ = setup(final=True)
    snap = repo.snapshot
    capture = replace(
        snap.capture,
        policy=replace(
            snap.capture.policy,
            selection_minor=79000,
            accompaniment_minor=170000,
        ),
        items=tuple(
            replace(i, selection_minor=79000, accompaniment_minor=170000)
            for i in snap.capture.items
        ),
    )
    from ugc_bot.application.financial_ports import WorkMaturitySource

    source = WorkMaturitySource(
        source_id=uuid4(),
        source_event_id=event.event_id,
        assignment_id=snap.scope.assignment_id,
        paid_item_id=snap.scope.paid_item_id,
        order_id=snap.scope.order_id,
        policy_version=snap.scope.policy_version,
        creator_id=snap.scope.creator_id,
        manager_id=snap.scope.manager_id,
        state="success_final",
        assignment_ended_at=None,
        success_final_at=snap.record.collaboration.success_final_at,
        release_at=snap.record.collaboration.available_at,
    )
    ledger.maturity_sources[source.source_id] = source
    repo.snapshot = replace(snap, capture=capture, schedule_id=source.source_id)
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
    assert sorted(o.movement.amount_minor for o in ledger.records.values()) == [
        7900,
        60000,
    ]


@pytest.mark.parametrize(
    "paid,refund,manager", [(170000, 85000, 30000), (60001, 30001, 30000)]
)
def test_accompaniment_refund_uses_actual_purchase_price(paid, refund, manager):
    from ugc_bot.domain.refund_rules import RefundRules

    rules = RefundRules(
        3600,
        "item_delivered",
        "all_positions_resolved",
        (("success_final", 5000),),
        "proportional",
    )
    assessed = rules.assess_accompaniment_refund(
        stage="success_final", paid_minor=paid, manager_earned_minor=60000
    )
    assert (
        assessed.customer_refund_minor,
        assessed.manager_adjustment_minor,
    ) == (refund, manager)


@pytest.mark.parametrize(
    "selection,accompaniment",
    [(49_880_000, 120000), (1, 49_999_999), (1_000_000_000, 120000)],
)
def test_tariff_pair_must_fit_two_hundred_fully_accompanied_positions(
    selection, accompaniment
):
    from ugc_bot.application.services.financial_policy_service import (
        FinancialPolicy,
    )

    cfg = config()
    draft = FinancialPolicyDraft.from_environment(cfg, **inputs())
    with pytest.raises(ValueError):
        config(
            FINANCIAL_SELECTION_PRICE_MINOR=selection,
            FINANCIAL_ACCOMPANIMENT_PRICE_MINOR=accompaniment,
        )
    with pytest.raises(ValueError, match="invalid_policy_tariff"):
        replace(
            draft, selection_minor=selection, accompaniment_minor=accompaniment
        )
    with pytest.raises(ValueError, match="invalid_policy_tariff"):
        FinancialPolicy(
            "limit",
            None,
            None,
            None,
            None,
            frozenset(),
            None,
            selection_minor=selection,
            accompaniment_minor=accompaniment,
        )
    with pytest.raises(ValueError, match="invalid_policy_tariff"):
        build_quote(
            order_id=uuid4(),
            count=10,
            selection_minor=selection,
            accompaniment_minor=accompaniment,
            accompaniment_ordinals=frozenset(),
            currency="RUB",
            policy_version="limit",
            selection_due_at=Clock().now(),
            client_contact_reference="contact",
            terms_reference="terms",
            idempotency_key="limit",
        )


def test_largest_tariff_pair_has_exact_total_and_checks_actual_quote():
    cfg = config(
        FINANCIAL_SELECTION_PRICE_MINOR=49_879_999,
        FINANCIAL_ACCOMPANIMENT_PRICE_MINOR=120000,
    )
    draft = FinancialPolicyDraft.from_environment(cfg, **inputs())
    quote = build_quote(
        order_id=uuid4(),
        count=200,
        selection_minor=draft.selection_minor,
        accompaniment_minor=draft.accompaniment_minor,
        accompaniment_ordinals=frozenset(range(1, 201)),
        currency="RUB",
        policy_version=draft.version,
        selection_due_at=Clock().now(),
        client_contact_reference="contact",
        terms_reference="terms",
        idempotency_key="limit",
    )
    assert quote.total_minor == 9_999_999_800
    with pytest.raises(ValueError, match="invoice_amount_out_of_range"):
        replace(quote, items=quote.items + (quote.items[0],))


@pytest.mark.asyncio
async def test_client_zero_commission_is_a_completed_idempotent_audit():
    from tests.application.services.test_client_entitlement_service import (
        scenario,
    )

    service, source, ledger, _, _, event = await scenario()
    source.capture = replace(
        source.capture,
        policy=replace(source.capture.policy, selection_minor=1),
        items=tuple(
            replace(item, selection_minor=1) for item in source.capture.items
        ),
    )
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
    assert source.receipt is not None
    assert ledger.records == ledger.movements == {}
    (assessment,) = ledger.potentials.values()
    assert assessment.reason == "rounded_commission_zero"
    assert assessment.basis.recipient_id == source.capture.captured_referrer_id
    assert assessment.basis.base_minor == 1
    assert assessment.basis.rate_bps == 300
    before = dict(ledger.potentials)
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
    assert ledger.potentials == before


@pytest.mark.asyncio
async def test_creator_zero_commission_does_not_block_earned_manager_reward():
    from tests.application.services.test_work_entitlement_service import setup
    from ugc_bot.application.financial_ports import WorkMaturitySource

    repo, ledger, service, _, event, _, _ = setup(final=True)
    snap = repo.snapshot
    capture = replace(
        snap.capture,
        policy=replace(snap.capture.policy, selection_minor=1),
        items=tuple(
            replace(item, selection_minor=1) for item in snap.capture.items
        ),
    )
    source = WorkMaturitySource(
        source_id=uuid4(),
        source_event_id=event.event_id,
        assignment_id=snap.scope.assignment_id,
        paid_item_id=snap.scope.paid_item_id,
        order_id=snap.scope.order_id,
        policy_version=snap.scope.policy_version,
        creator_id=snap.scope.creator_id,
        manager_id=snap.scope.manager_id,
        state="success_final",
        assignment_ended_at=None,
        success_final_at=snap.record.collaboration.success_final_at,
        release_at=snap.record.collaboration.available_at,
    )
    ledger.maturity_sources[source.source_id] = source
    repo.snapshot = replace(snap, capture=capture, schedule_id=source.source_id)
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
    assert event.event_id in repo.receipts
    (assessment,) = ledger.potentials.values()
    assert assessment.reason == "rounded_commission_zero"
    assert assessment.basis.kind == "creator_referral"
    (manager,) = ledger.records.values()
    assert manager.basis.kind == "management"
    assert manager.movement.amount_minor == 60000
    before = (
        dict(ledger.potentials),
        dict(ledger.records),
        dict(ledger.movements),
    )
    async with ledger.transaction() as session:
        await service.handle(event, session=session)
    assert (ledger.potentials, ledger.records, ledger.movements) == before


@pytest.mark.asyncio
async def test_zero_override_assessment_requires_approval_and_keeps_audit():
    from tests.application.services.test_financial_ledger_service import command
    from ugc_bot.application.financial_ports import ApprovedRateOverride
    from ugc_bot.application.services.financial_ledger_service import (
        FinancialLedgerService,
        PayloadConflict,
    )
    from ugc_bot.infrastructure.memory_financial_ledger import (
        InMemoryFinancialLedgerRepository,
    )

    ledger = InMemoryFinancialLedgerRepository()
    service = FinancialLedgerService(ledger)
    basis = replace(
        command(),
        base_minor=100,
        rate_bps=1,
        rate_source="override",
        override_id=uuid4(),
    )
    with pytest.raises(ValueError, match="approved_override_required"):
        async with ledger.transaction() as session:
            await service.issue(
                basis, recorded_at=basis.snapshot_at, session=session
            )
    assert ledger.potentials == ledger.records == ledger.movements == {}
    ledger.overrides[basis.override_id] = ApprovedRateOverride(
        override_id=basis.override_id,
        recipient_id=basis.recipient_id,
        side="client",
        rate_bps=1,
        policy_version=basis.policy_version,
        effective_from=basis.snapshot_at - timedelta(days=1),
        effective_until=basis.snapshot_at + timedelta(days=1),
        approved_by=uuid4(),
        approved_at=basis.snapshot_at - timedelta(days=2),
        reason="approved small commission",
    )
    async with ledger.transaction() as session:
        saved = await service.issue(
            basis, recorded_at=basis.snapshot_at, session=session
        )
    assert saved.reason == "rounded_commission_zero"
    assert saved.basis.override_id == basis.override_id
    async with ledger.transaction() as session:
        assert (
            await service.issue(
                basis, recorded_at=basis.snapshot_at, session=session
            )
            == saved
        )
    for changed_base in (101, 10000):
        with pytest.raises(PayloadConflict):
            async with ledger.transaction() as session:
                await service.issue(
                    replace(basis, base_minor=changed_base),
                    recorded_at=basis.snapshot_at,
                    session=session,
                )
    assert ledger.records == ledger.movements == {}
    assert len(ledger.potentials) == 1

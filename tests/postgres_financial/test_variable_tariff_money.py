"""Real captures retain prices through delivery, replacement and corrections."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.postgres_financial.test_accompaniment_reserved_payout import (
    REVIEW_RULES,
    actual_refund,
)
from tests.postgres_financial.test_order_intake import (
    command,
    intake_env,
    service,
)
from tests.postgres_financial.test_paid_selection_delivery import (
    delivery_env,
    rows,
)
from tests.postgres_financial.test_payout_runtime import payout_env, wallet
from tests.postgres_financial.test_replacements import decision, setup, submit
from tests.postgres_financial.test_v1_capture import capture_env
from ugc_bot.domain.refund_rules import RefundRules
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import FinancialPolicyVersionModel

__all__ = ["capture_env", "delivery_env", "payout_env", "intake_env"]

TARIFF = {"selection_minor": 79000, "accompaniment_minor": 170000}


@pytest.mark.asyncio
@pytest.mark.parametrize("capture_env", [TARIFF], indirect=True)
async def test_capture_delivery_retains_new_tariff_allocation(delivery_env):
    env = delivery_env
    from ugc_bot.paid_selection_delivery_scheduler import run_loop

    await run_loop(env["worker"], max_iterations=1)
    (delivered,) = rows(env, "paid_selection_accepted_deliveries")
    assert delivered["amount_minor"] == 79000
    allocations = rows(env, "payment_item_allocations")
    assert sum(row["amount_minor"] for row in allocations) == 328000
    assert len(env["bot"].calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("capture_env", [TARIFF], indirect=True)
async def test_replacement_uses_original_paid_pool_and_new_selection_amount(
    capture_env,
):
    env = capture_env
    app, interests, issue, client, admin = await setup(env)
    pending = await submit(env, app, interests, client)
    async with env["factory"].begin() as db:
        result = await app.decide(
            decision(pending, admin), principal=admin, session=db
        )
        assert (
            await app.decide(
                decision(pending, admin), principal=admin, session=db
            )
            == result
        )
        ledger = await app.ledger.repository.list_for_recipient(
            env["client"], "RUB", session=db
        )
    assert (
        sum(
            m.amount_minor
            for m in ledger
            if m.obligation_id == issue.obligation_id
            and m.movement_type == "reversal"
        )
        == 7900
    )
    assert len(rows(env, "order_items")) == 2
    assert {r["selection_minor"] for r in rows(env, "order_items")} == {79000}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "capture_env", [TARIFF | {"refund_rules": REVIEW_RULES}], indirect=True
)
async def test_partial_refund_preserves_manager_reward_and_selection(
    payout_env,
):
    env = payout_env
    manager = env["flow"]["manager"]
    assert wallet(env, manager)["available_minor"] == 60000
    refunds, apply = await actual_refund(env, customer_minor=85000)
    async with env["flow"]["container"].transaction_manager.transaction() as db:
        applied = await refunds.apply(apply, session=db)
        assert await refunds.apply(apply, session=db) == applied
    assert applied["customer_refund_minor"] == 85000
    assert applied["manager_adjustment_minor"] == 30000
    assert wallet(env, manager)["cancelled_minor"] == 30000
    items = rows(env, "order_items")
    assert {i["selection_minor"] for i in items} == {79000}
    assert sorted(i["accompaniment_minor"] for i in items) == [0, 170000]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "count,selection,override_bps",
    [(10, 79000, None), (200, 79000, None), (10, 1, None), (10, 100, 1)],
)
async def test_manual_correction_uses_saved_component_and_actual_count(
    intake_env, count, selection, override_bps
):
    from tests.helpers.correction_runtime_pg import Runtime
    from tests.helpers.corrections import captured_order
    from ugc_bot.application.correction_ports import ApplySelectionRefund
    from ugc_bot.application.services.financial_ledger_service import (
        FinancialLedgerService,
    )
    from ugc_bot.application.services.refund_compensation_service import (
        SelectionRefundCompensationService,
    )
    from ugc_bot.container.correction_factory import _original_client_assessment
    from ugc_bot.infrastructure.db.repositories.financial_capture import (
        intent_id,
    )

    env = intake_env
    rules = RefundRules(
        3600, "item_delivered", "all_positions_resolved", (), "retain_earned"
    )
    version = "correction-tariff-" + uuid4().hex
    with Session(env["pg"]) as db, db.begin():
        old = db.get(FinancialPolicyVersionModel, env["policy"])
        db.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=old.approved_by,
                approved_at=old.approved_at,
                effective_from=old.effective_from,
                refund_window_seconds=3600,
                rules=old.rules
                | (TARIFF | {"selection_minor": selection})
                | {"refund_rules": rules.to_document()},
            )
        )
    requested = command(env, policy_version=version, position_count=count)
    result = await service(env).create(requested)
    facts = await captured_order(env, existing=(requested, result))
    facts["invoice_id"] = intent_id(result.order_id)
    if override_bps is not None:
        from datetime import timedelta

        from ugc_bot.infrastructure.db.financial_lifecycle_models import (
            RateOverrideModel,
        )

        with Session(env["pg"]) as db, db.begin():
            db.add(
                RateOverrideModel(
                    override_id=uuid4(),
                    recipient_id=facts["partner"],
                    side="client",
                    rate_bps=override_bps,
                    policy_version=version,
                    approved_by=env["admin"].user_id,
                    approved_at=facts["capture_at"] - timedelta(days=2),
                    effective_from=facts["capture_at"] - timedelta(days=1),
                    effective_until=facts["capture_at"] + timedelta(days=1),
                    reason="Synthetic approved override at capture",
                )
            )
    rt = Runtime(env, facts)
    ledger = FinancialLedgerService(env["repos"]["financial_ledger_repo"])
    rt.service.compensation = SelectionRefundCompensationService(
        rt.repo,
        ledger,
        original_assessment=_original_client_assessment(
            ledger, env["clock"], env["container"].session_factory
        ),
    )
    requested_refund = await rt.execute(await rt.request())
    approved = await rt.execute(rt.review(requested_refund))
    observed = await rt.execute(
        rt.observation(approved, amount_minor=selection * 5)
    )
    matched = await rt.execute(rt.match(observed, approved, observed))
    apply = ApplySelectionRefund(
        **{
            name: getattr(rt.match(matched, approved, observed), name)
            for name in ApplySelectionRefund.__dataclass_fields__
            if name != "match_id"
        },
        match_id=UUID(matched["match_id"]),
    )
    applied = await rt.execute(apply)
    assert applied["applied"] is True
    assert await rt.execute(apply) == applied
    components = Base.metadata.tables["financial_refund_component_applications"]
    with Session(env["pg"]) as db:
        saved = (
            db.execute(
                select(components).where(
                    components.c.application_id
                    == UUID(applied["application_id"])
                )
            )
            .mappings()
            .all()
        )
    assert len(saved) == 5
    assert {c["gross_minor"] for c in saved} == {selection}
    assert sum(c["refund_minor"] for c in saved) == selection * 5
    if selection < 5000:
        from tests.helpers.corrections import rows as correction_rows

        audits = correction_rows(
            env, "financial_audit_events", reason="rounded_commission_zero"
        )
        audits = [
            r
            for r in audits
            if r["details"]["order_id"] == str(result.order_id)
        ]
        assert len(audits) == count
        assert {a["details"]["recipient_id"] for a in audits} == {
            str(facts["partner"])
        }
        assert {a["details"]["rate_bps"] for a in audits} == {
            override_bps or 1000
        }
        assert (
            correction_rows(
                env, "financial_obligations", order_id=result.order_id
            )
            == []
        )
        liabilities = correction_rows(
            env, "financial_refund_liability_assessments"
        )
        component_ids = {c["component_application_id"] for c in saved}
        assessments = [
            r
            for r in liabilities
            if r["component_application_id"] in component_ids
        ]
        assert len(assessments) == 5
        assert {a["status"] for a in assessments} == {"covered_zero"}
        assert all(
            a["movement_id"] is None and a["delta_minor"] == 0
            for a in assessments
        )

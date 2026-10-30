"""One refunded selection item cannot stall other delivered items."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.helpers.correction_runtime_pg import runtime
from tests.helpers.corrections import (
    assess_original,
    deliver_original_positions,
)
from tests.postgres_financial.test_order_intake import intake_env
from ugc_bot.application.correction_ports import ApplySelectionRefund
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.application.services.refund_compensation_service import (
    SelectionRefundCompensationService,
)
from ugc_bot.application.services.selection_maturity_service import (
    SelectionMaturityService,
)
from ugc_bot.container.correction_factory import _original_client_assessment
from ugc_bot.domain.refund_rules import RefundRules
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import FinancialPolicyVersionModel
from ugc_bot.infrastructure.db.repositories.selection_maturity import (
    SqlAlchemySelectionMaturityRepository,
)

__all__ = ["intake_env"]


@pytest.mark.asyncio
async def test_one_confirmed_full_refund_does_not_block_delivered_item(
    intake_env,
):
    env = intake_env
    version = "item-refund-" + uuid4().hex
    rules = RefundRules(604800, "item_delivered", "manual", (), "manual_review")
    with Session(env["pg"]) as db, db.begin():
        db.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=env["admin"].user_id,
                approved_at=env["clock"].at - timedelta(days=2),
                effective_from=env["clock"].at - timedelta(days=1),
                refund_window_seconds=604800,
                rules={
                    "terms_reference": "synthetic-approved-terms",
                    "allowed_clients": [str(env["user"].user_id)],
                    "maturity_mode": "per_item_v1",
                    "selection_refund_window_anchor": (
                        "per_item_delivery_accepted_at"
                    ),
                    "hold_seconds": 1209600,
                    "refund_rules": rules.to_document(),
                },
            )
        )
    env["policy"] = version
    rt = await runtime(env)
    facts = rt.facts
    await assess_original(env, facts)
    delivered = (await deliver_original_positions(env, facts, count=1))[0]
    refunded = facts["order"].items[-1].paid_item_id
    assert delivered != refunded
    ledger = FinancialLedgerService(env["repos"]["financial_ledger_repo"])
    rt.service.compensation = SelectionRefundCompensationService(
        rt.repo,
        ledger,
        original_assessment=_original_client_assessment(
            ledger, env["clock"], env["container"].session_factory
        ),
    )
    command = await rt.request(paid_item_ids=(refunded,))
    async with env["container"].transaction_manager.transaction() as db:
        scope = await rt.repo.discover_scope(command, session=db)
    command = replace(command, expected_source_hash=scope.source_hash)
    requested = await rt.execute(command)
    with Session(env["pg"]) as db:
        at = db.scalar(
            select(
                Base.metadata.tables[
                    "paid_selection_accepted_deliveries"
                ].c.accepted_at
            ).filter_by(paid_item_id=delivered)
        )
    env["clock"].at = at + timedelta(days=21)
    maturity = SelectionMaturityService(
        SqlAlchemySelectionMaturityRepository(), ledger, env["clock"]
    )
    async with env["container"].transaction_manager.transaction() as db:
        result = await maturity.refresh(facts["order"].order_id, session=db)
        wallet = await ledger.repository.read_projection(
            facts["partner"], "RUB", session=db
        )
    assert [row["paid_item_id"] for row in result["items"]] == [str(delivered)]
    assert wallet["available"] == 5000
    assert wallet["pending"] == 145000
    approved = await rt.execute(rt.review(requested))
    observed = await rt.execute(rt.observation(approved, amount_minor=50000))
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
    assert applied["applied"]
    components = Base.metadata.tables["financial_refund_component_applications"]
    with Session(env["pg"]) as db:
        original = dict(
            db.execute(select(components).filter_by(paid_item_id=refunded))
            .mappings()
            .one()
        )
    # A partial amount has no approved source under the current full-component
    # contract, so PostgreSQL must reject it before it can affect funding.
    forged = original | {
        "component_application_id": uuid4(),
        "refund_minor": 25000,
        "new_refund_minor": 25000,
    }
    with (
        pytest.raises(IntegrityError, match="ck_correction_component"),
        Session(env["pg"]) as db,
        db.begin(),
    ):
        db.execute(insert(components).values(**forged))
    async with env["container"].transaction_manager.transaction() as db:
        result = await maturity.refresh(facts["order"].order_id, session=db)
        wallet = await ledger.repository.read_projection(
            facts["partner"], "RUB", session=db
        )
    assert [row["paid_item_id"] for row in result["items"]] == [str(delivered)]
    assert wallet["available"] == 5000
    assert wallet["cancelled"] == 5000
    assert wallet["pending"] == 140000

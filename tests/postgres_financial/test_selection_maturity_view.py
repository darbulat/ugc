"""Views describe the active maturity policy without inventing closure."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from tests.helpers.corrections import captured_order, deliver_original_positions
from tests.postgres_financial.test_order_intake import (
    command,
    intake_env,
    service,
)
from ugc_bot.domain.refund_rules import RefundRules
from ugc_bot.infrastructure.db.models import FinancialPolicyVersionModel
from ugc_bot.infrastructure.db.repositories.selection_view import (
    SqlAlchemySelectionViewRepository,
)

__all__ = ["intake_env"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "maturity_mode,with_rules",
    [("legacy", True), ("per_item_v1", True), ("per_item_v1", False)],
)
async def test_manual_closure_only_offered_when_policy_closes_order(
    intake_env, maturity_mode, with_rules
):
    env = intake_env
    version = "view-maturity-" + uuid4().hex
    rules = RefundRules(604800, "item_delivered", "manual", (), "retain_earned")
    extra = {}
    if maturity_mode == "per_item_v1":
        extra = {
            "maturity_mode": "per_item_v1",
            "selection_refund_window_anchor": "per_item_delivery_accepted_at",
            "hold_seconds": 1209600,
        }
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
                    **(
                        {"refund_rules": rules.to_document()}
                        if with_rules
                        else {}
                    ),
                    **extra,
                },
            )
        )
    env["policy"] = version
    request = command(env, position_count=10)
    order = await service(env).create(request)
    facts = await captured_order(env, existing=(request, order))
    await deliver_original_positions(env, facts, count=10 if with_rules else 1)
    async with env["container"].transaction_manager.transaction() as db:
        view = await SqlAlchemySelectionViewRepository().view(
            order.order_id, env["user"].user_id, session=db
        )
    closure = view["closure_policy"]
    assert closure["mode"] == (
        "manual" if maturity_mode == "legacy" else "per_item_v1"
    )
    assert closure["can_close"] is (maturity_mode == "legacy")
    assert closure["refund_window_seconds"] == 604800
    assert closure["anchor"] == "item_delivered"
    assert closure["closed_at"] is None
    assert len(view["positions"]) == 10

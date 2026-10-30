"""Mode publication and quote snapshots use a real immutable policy row."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from tests.application.services.test_refund_policy_publication import config
from tests.postgres_financial.test_order_intake import (
    command,
    intake_env,
    scoped_rows,
    service,
)
from ugc_bot.application.services.financial_policy_publication import (
    FinancialPolicyDraft,
    FinancialPolicyPublicationService,
)
from ugc_bot.infrastructure.db.models import FinancialPolicyVersionModel

__all__ = ["intake_env"]


@pytest.mark.asyncio
async def test_explicit_per_item_mode_survives_publication_and_quote(
    intake_env,
):
    env = intake_env
    version = "per-item-" + uuid4().hex
    draft = FinancialPolicyDraft.from_environment(
        config(FINANCIAL_SELECTION_REFUND_WINDOW_ANCHOR="item_delivered"),
        version=version,
        effective_from=env["clock"].at,
        allowed_clients=frozenset({env["user"].user_id}),
        terms_reference="terms:synthetic-per-item",
        maturity_mode="per_item_v1",
    )
    policy = await FinancialPolicyPublicationService(
        env["repos"]["financial_policy_repo"],
        env["container"].transaction_manager,
        env["clock"],
    ).publish(draft, actor_id=env["admin"].user_id)
    async with env["container"].transaction_manager.transaction() as db:
        reloaded = await env["repos"]["financial_policy_repo"].load(
            version, session=db
        )
    assert reloaded == policy
    with Session(env["pg"]) as db:
        rules = db.get(FinancialPolicyVersionModel, version).rules
        assert rules["maturity_mode"] == "per_item_v1"
        assert rules["hold_seconds"] == 1209600
        assert (
            rules["selection_refund_window_anchor"]
            == "per_item_delivery_accepted_at"
        )
    order = await service(env).create(command(env, policy_version=version))
    for item in scoped_rows(env, "order_items", order.order_id):
        assert item["policy_version"] == version
        assert (
            item["quote_payload"]["refund_rules"]
            == draft.refund_rules.to_document()
        )

"""Policy and quote decoding never borrow new terms from the environment."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.application.services.test_financial_policy_service import (
    ready_policy,
)
from tests.application.services.test_refund_policy_publication import config
from ugc_bot.application.services.paid_item_service import (
    PaidItemService,
    build_quote,
)
from ugc_bot.infrastructure.db.repositories.financial_items import (
    SqlAlchemyFinancialItemRepository,
    _payload,
)


def quote_and_row(rules=None):
    _, policy, args = ready_policy()
    quote = build_quote(
        order_id=uuid4(),
        count=1,
        accompaniment_ordinals=frozenset({1}),
        currency="RUB",
        policy_version=policy.version,
        selection_due_at=args["selection_due_at"],
        client_contact_reference="contact:test",
        terms_reference=policy.terms_reference,
        idempotency_key="quote-a",
    )
    assert "refund_rules" in quote.__dataclass_fields__, (
        "Quotes do not retain their approved refund rules"
    )
    quote = replace(quote, refund_rules=rules)
    row = SimpleNamespace(
        order_id=quote.order_id,
        ordinal=1,
        paid_item_id=quote.items[0].paid_item_id,
        quote_key=quote.idempotency_key,
        quote_payload=_payload(quote),
    )
    return quote, row


def test_legacy_quote_retains_absent_key_and_roundtrips_unchanged():
    quote, row = quote_and_row()
    assert "refund_rules" not in row.quote_payload
    assert SqlAlchemyFinancialItemRepository._quote([row]) == quote


def test_new_quote_snapshot_is_symmetric_and_ignores_later_environment():
    cfg = config()
    rules = cfg.refund_rules()
    quote, row = quote_and_row(rules)
    cfg.selection_refund_window_seconds = 86400
    assert row.quote_payload["refund_rules"] == rules.to_document()
    assert SqlAlchemyFinancialItemRepository._quote([row]) == quote
    assert quote.refund_rules.selection_refund_window_seconds == 604800


def test_historical_quote_replay_uses_selected_snapshot_not_current_payload():
    quote_a, row = quote_and_row()
    original = dict(row.quote_payload)
    quote_b = replace(
        quote_a,
        idempotency_key="quote-b",
        refund_rules=config().refund_rules(),
    )
    row.quote_key = "quote-b"
    row.quote_payload = _payload(quote_b) | {"_history": {"quote-a": original}}
    assert (
        SqlAlchemyFinancialItemRepository._replay(
            [row], quote_a, _payload(quote_a)
        )
        == quote_a
    )
    assert SqlAlchemyFinancialItemRepository._quote([row]) == quote_b


@pytest.mark.parametrize("document", [None, {}, {"schema_version": 999}])
def test_present_but_invalid_quote_rules_do_not_fall_back_to_legacy(document):
    _, row = quote_and_row()
    row.quote_payload["refund_rules"] = document
    with pytest.raises(ValueError):
        SqlAlchemyFinancialItemRepository._quote([row])


def test_direct_policy_cannot_disagree_with_snapshot_window():
    _, policy, _ = ready_policy()
    assert "refund_rules" in policy.__dataclass_fields__, (
        "Policies lack immutable configured rules"
    )
    with pytest.raises(ValueError, match="refund_rules_window_mismatch"):
        replace(
            policy,
            selection_refund_window=timedelta(hours=1),
            refund_rules=config().refund_rules(),
        )


def test_prepare_quote_copies_policy_snapshot_instead_of_current_config():
    gate, policy, args = ready_policy()
    original = config().refund_rules()
    policy = replace(policy, refund_rules=original)
    gate = replace(
        gate,
        config=config(FINANCIAL_SELECTION_REFUND_WINDOW_SECONDS=86400),
    )
    gate.config.core_enabled = gate.config.new_orders_enabled = True
    quote = PaidItemService(None, gate).prepare_quote(
        policy=policy,
        client_id=args["client_id"],
        order_created_at=args["order_created_at"],
        selection_due_at=args["selection_due_at"],
        currency="RUB",
        now=args["captured_at"],
        order_id=uuid4(),
        accompaniment_ordinals=frozenset(),
        client_contact_reference="contact:test",
        idempotency_key="snapshot-from-policy",
    )
    assert quote.refund_rules == original

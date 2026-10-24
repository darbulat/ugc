"""Immutable capture truth while sibling positions may already be corrected."""

from datetime import timedelta

from ugc_bot.domain.financial import utc
from ugc_bot.infrastructure.db.repositories.entitlements import (
    SqlAlchemyClientEntitlementRepository,
    _require,
)


class SqlAlchemySelectionFundingRepository(
    SqlAlchemyClientEntitlementRepository
):
    @staticmethod
    def _require_policy(policy, effective, order, items, at):
        _require(
            effective <= utc(order["created_at"]) <= at
            and order["advertiser_id"] in policy.allowed_clients
            and bool(policy.terms_reference)
            and policy.selection_refund_window is not None
            and policy.selection_refund_window > timedelta(0),
            "capture_policy_mismatch",
        )
        for item in items:
            quote = item["quote_payload"]
            _require(
                item["currency"] == "RUB"
                and item["policy_version"] == policy.version
                and item["quote_key"] == items[0]["quote_key"]
                and item["selection_minor"] == 50000
                and item["accompaniment_minor"] in (0, 120000)
                and item["captured_at"] == at
                and item["selection_state"]
                in ("paid", "delivered", "refunded", "cancelled")
                and utc(item["selection_due_at"]) > at
                and quote.get("client_id") == str(order["advertiser_id"])
                and quote.get("terms_reference") == policy.terms_reference,
                "capture_item_mismatch",
            )

"""Fail-closed policy gates; legacy orders never convert implicitly."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from ugc_bot.application.ports import TransactionManager
from ugc_bot.config import FinancialConfig
from ugc_bot.domain.financial import utc
from ugc_bot.domain.financial_tariff import require_tariff
from ugc_bot.domain.refund_rules import RefundRules

PER_ITEM_SELECTION_ANCHOR = "per_item_delivery_accepted_at"
PER_ITEM_HOLD_SECONDS = 14 * 24 * 60 * 60


def require_maturity_mode(mode, window, refund_rules) -> None:
    """Keep the per-position rule explicit and consistent with refund terms."""
    if type(mode) is not str or mode not in ("legacy", "per_item_v1"):
        raise ValueError("invalid_maturity_policy")
    if mode == "per_item_v1" and (
        window != timedelta(days=7)
        or (
            refund_rules is not None
            and (
                not isinstance(refund_rules, RefundRules)
                or refund_rules.selection_refund_window_anchor
                != "item_delivered"
            )
        )
    ):
        raise ValueError("invalid_maturity_policy")


@dataclass(frozen=True, slots=True)
class FinancialPolicy:
    version: str
    approved_by: UUID | None
    approved_at: datetime | None
    effective_from: datetime | None
    selection_refund_window: timedelta | None
    allowed_clients: frozenset[UUID]
    terms_reference: str | None
    refund_rules: RefundRules | None = None
    selection_minor: int = 50000
    accompaniment_minor: int = 120000
    all_clients: bool = False
    maturity_mode: str = "legacy"

    def __post_init__(self) -> None:
        require_tariff(self.selection_minor, self.accompaniment_minor)
        require_maturity_mode(
            self.maturity_mode, self.selection_refund_window, self.refund_rules
        )
        if type(self.all_clients) is not bool:
            raise ValueError("invalid_policy_access_scope")
        object.__setattr__(
            self, "allowed_clients", frozenset(self.allowed_clients)
        )
        if self.all_clients and self.allowed_clients:
            raise ValueError("invalid_policy_access_scope")
        if self.refund_rules is not None and (
            not isinstance(self.refund_rules, RefundRules)
            or self.selection_refund_window
            != timedelta(
                seconds=self.refund_rules.selection_refund_window_seconds
            )
        ):
            raise ValueError("refund_rules_window_mismatch")

    def allows_client(self, client_id: UUID) -> bool:
        return (
            isinstance(client_id, UUID)
            and client_id.int != 0
            and (self.all_clients or client_id in self.allowed_clients)
        )


class FinancialPolicyReader(Protocol):
    async def load(
        self, version: str, *, session: object
    ) -> FinancialPolicy | None: ...

    async def lock_version(self, version: str, *, session: object) -> None: ...


@dataclass(frozen=True, slots=True)
class FinancialPolicyService:
    config: FinancialConfig
    reader: FinancialPolicyReader | None = None
    transaction_manager: TransactionManager | None = None

    async def load_policy(self, version: str) -> FinancialPolicy:
        """Load server-owned immutable approval; disabled gates precede any SQL.

        Loading approval alone never authorizes a quote or payment. The caller
        must still validate client, date, currency, deadline and refund gates
        for its command using validate_for_capture.
        """
        if not self.config.core_enabled or not self.config.new_orders_enabled:
            raise ValueError("financial_disabled")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("approved_policy_required")
        if self.reader is None or self.transaction_manager is None:
            raise ValueError("policy_reader_and_transaction_required")
        async with self.transaction_manager.transaction() as session:
            policy = await self.reader.load(version, session=session)
        approved, _ = self._approved_policy(policy, version)
        return approved

    def validate_for_capture(
        self,
        *,
        policy: FinancialPolicy | None,
        client_id: UUID,
        order_created_at: datetime,
        financial_version: str | None,
        selection_due_at: datetime | None,
        currency: str,
        captured_at: datetime,
    ) -> FinancialPolicy:
        if not self.config.core_enabled or not self.config.new_orders_enabled:
            raise ValueError("financial_disabled")
        if not isinstance(client_id, UUID) or client_id.int == 0:
            raise ValueError("client_identity_required")
        policy, effective = self._approved_policy(policy, financial_version)
        created, captured = utc(order_created_at), utc(captured_at)
        if created < effective or captured < created:
            raise ValueError("legacy_order_not_eligible")
        if not policy.allows_client(client_id):
            raise ValueError("client_not_allowlisted")
        if (
            policy.selection_refund_window is None
            or policy.selection_refund_window <= timedelta(0)
        ):
            raise ValueError("selection_refund_window_required")
        if selection_due_at is None or utc(selection_due_at) <= captured:
            raise ValueError("agreed_selection_due_at_required")
        if not policy.terms_reference or not policy.terms_reference.strip():
            raise ValueError("published_terms_required")
        if currency != "RUB":
            raise ValueError("unpublished_currency")
        return policy

    @staticmethod
    def _approved_policy(
        policy: FinancialPolicy | None, financial_version: str | None
    ) -> tuple[FinancialPolicy, datetime]:
        if (
            policy is None
            or not isinstance(policy.version, str)
            or not policy.version.strip()
            or financial_version != policy.version
        ):
            raise ValueError("approved_policy_required")
        if (
            not isinstance(policy.approved_by, UUID)
            or policy.approved_by.int == 0
            or policy.approved_at is None
            or policy.effective_from is None
        ):
            raise ValueError("approved_policy_required")
        effective = utc(policy.effective_from)
        if utc(policy.approved_at) > effective:
            raise ValueError("approval_after_activation")
        return policy, effective

    def create_override(self) -> None:
        raise ValueError("policy_feature_disabled")

    def apply_override(self) -> None:
        raise ValueError("policy_feature_disabled")

    def set_nonstandard_price(self) -> None:
        raise ValueError("policy_feature_disabled")

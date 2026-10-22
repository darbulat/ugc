"""Fail-closed policy gates; legacy orders never convert implicitly."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from ugc_bot.application.ports import TransactionManager
from ugc_bot.config import FinancialConfig
from ugc_bot.domain.financial import utc


@dataclass(frozen=True, slots=True)
class FinancialPolicy:
    version: str
    approved_by: UUID | None
    approved_at: datetime | None
    effective_from: datetime | None
    selection_refund_window: timedelta | None
    allowed_clients: frozenset[UUID]
    terms_reference: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "allowed_clients", frozenset(self.allowed_clients)
        )


class FinancialPolicyReader(Protocol):
    async def load(
        self, version: str, *, session: object
    ) -> FinancialPolicy | None: ...


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
        if client_id not in policy.allowed_clients:
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

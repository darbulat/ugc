"""Immutable standard quote, independent of mutable contact-pricing tables."""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicy,
    FinancialPolicyService,
)
from ugc_bot.domain.financial import utc
from ugc_bot.domain.financial_tariff import (
    require_invoice_total,
    require_tariff,
)
from ugc_bot.domain.refund_rules import RefundRules


@dataclass(frozen=True, slots=True)
class QuotedItem:
    paid_item_id: UUID
    ordinal: int
    selection_minor: int
    accompaniment_minor: int


@dataclass(frozen=True, slots=True)
class FinancialQuote:
    order_id: UUID
    currency: str
    policy_version: str
    selection_due_at: datetime
    client_contact_reference: str
    terms_reference: str
    idempotency_key: str
    items: tuple[QuotedItem, ...]
    client_id: UUID | None = None
    refund_rules: RefundRules | None = None

    def __post_init__(self) -> None:
        require_invoice_total(self.total_minor)

    @property
    def total_minor(self) -> int:
        return sum(
            item.selection_minor + item.accompaniment_minor
            for item in self.items
        )

    @property
    def selection_base_minor(self) -> int:
        return sum(item.selection_minor for item in self.items)


class FinancialQuoteRepository(Protocol):
    async def lock_order(self, order_id: UUID, *, session: object) -> None: ...
    async def activate_new_order(
        self, order_id: UUID, policy_version: str, *, session: object
    ) -> None: ...

    async def save_quote(
        self, quote: FinancialQuote, *, session: object
    ) -> FinancialQuote: ...


@dataclass(slots=True)
class PaidItemService:
    repository: FinancialQuoteRepository
    policy_service: FinancialPolicyService

    def prepare_quote(
        self,
        *,
        policy: FinancialPolicy | None,
        client_id: UUID,
        order_created_at: datetime,
        selection_due_at: datetime | None,
        currency: str,
        now: datetime,
        order_id: UUID,
        accompaniment_ordinals: frozenset[int],
        client_contact_reference: str,
        idempotency_key: str,
        position_count: int = 30,
    ) -> FinancialQuote:
        approved = self.policy_service.validate_for_capture(
            policy=policy,
            client_id=client_id,
            order_created_at=order_created_at,
            financial_version=policy.version if policy else None,
            selection_due_at=selection_due_at,
            currency=currency,
            captured_at=now,
        )
        assert (
            selection_due_at is not None
            and approved.terms_reference is not None
        )
        return replace(
            build_quote(
                order_id=order_id,
                count=position_count,
                selection_minor=approved.selection_minor,
                accompaniment_minor=approved.accompaniment_minor,
                accompaniment_ordinals=accompaniment_ordinals,
                currency=currency,
                policy_version=approved.version,
                selection_due_at=selection_due_at,
                client_contact_reference=client_contact_reference,
                terms_reference=approved.terms_reference,
                idempotency_key=idempotency_key,
            ),
            client_id=client_id,
            refund_rules=approved.refund_rules,
        )

    async def quote_new_order(
        self,
        *,
        session: object,
        policy: FinancialPolicy | None,
        client_id: UUID,
        order_created_at: datetime,
        selection_due_at: datetime | None,
        currency: str,
        now: datetime,
        order_id: UUID,
        accompaniment_ordinals: frozenset[int],
        client_contact_reference: str,
        idempotency_key: str,
        position_count: int = 30,
    ) -> FinancialQuote:
        quote = self.prepare_quote(
            policy=policy,
            client_id=client_id,
            order_created_at=order_created_at,
            selection_due_at=selection_due_at,
            currency=currency,
            now=now,
            order_id=order_id,
            accompaniment_ordinals=accompaniment_ordinals,
            client_contact_reference=client_contact_reference,
            idempotency_key=idempotency_key,
            position_count=position_count,
        )
        return await self.repository.save_quote(quote, session=session)


def build_quote(
    *,
    order_id: UUID,
    count: int,
    selection_minor: int,
    accompaniment_minor: int,
    accompaniment_ordinals: frozenset[int],
    currency: str,
    policy_version: str,
    selection_due_at: datetime,
    client_contact_reference: str,
    terms_reference: str,
    idempotency_key: str,
) -> FinancialQuote:
    if currency != "RUB":
        raise ValueError("unpublished_currency")
    if type(count) is not int or not 10 <= count <= 200:
        raise ValueError("invalid_position_count")
    require_tariff(selection_minor, accompaniment_minor)
    if any(
        type(n) is not int or not 1 <= n <= count
        for n in accompaniment_ordinals
    ):
        raise ValueError("invalid_accompaniment_ordinal")
    if not all(
        s.strip()
        for s in (
            policy_version,
            client_contact_reference,
            terms_reference,
            idempotency_key,
        )
    ):
        raise ValueError("quote_terms_and_provenance_required")
    return FinancialQuote(
        order_id,
        currency,
        policy_version,
        utc(selection_due_at),
        client_contact_reference,
        terms_reference,
        idempotency_key,
        tuple(
            QuotedItem(
                uuid4(),
                ordinal,
                selection_minor,
                accompaniment_minor if ordinal in accompaniment_ordinals else 0,
            )
            for ordinal in range(1, count + 1)
        ),
    )

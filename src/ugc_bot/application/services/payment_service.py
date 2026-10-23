"""Service for Telegram payments and order activation."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID, uuid4

from ugc_bot.application.capture_ports import FinancialCaptureRepository
from ugc_bot.application.errors import OrderCreationError, UserNotFoundError
from ugc_bot.application.messenger.dto import PaymentSuccess
from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    ContactPricingRepository,
    CountryRepository,
    OrderRepository,
    PaymentRepository,
    TransactionManager,
    UserRepository,
)
from ugc_bot.domain.entities import Order, Payment
from ugc_bot.domain.enums import OrderStatus, PaymentStatus
from ugc_bot.infrastructure.db.session import with_optional_tx

if TYPE_CHECKING:
    from ugc_bot.config import AppConfig

logger = logging.getLogger(__name__)

DEFAULT_RECEIPT_SERVICE_DESCRIPTION = "Услуги платформы Use My Content"

PROVIDER_RU = "yookassa_telegram"
PROVIDER_INTL = "telegram_payments"


def build_receipt_provider_data(
    total_amount: float | Decimal,
    currency: str,
    receipt_description: str,
) -> str:
    """Build provider_data JSON for YooKassa receipt (54-FZ)."""
    amount_str = f"{total_amount:.2f}"
    receipt = {
        "receipt": {
            "items": [
                {
                    "description": receipt_description
                    or DEFAULT_RECEIPT_SERVICE_DESCRIPTION,
                    "quantity": 1,
                    "amount": {"value": amount_str, "currency": currency},
                    "vat_code": 2,
                    "payment_mode": "full_prepayment",
                    "payment_subject": "service",
                }
            ],
            "internet": "true",
        }
    }
    return json.dumps(receipt, ensure_ascii=False)


@dataclass(frozen=True)
class InvoiceData:
    """All data needed to send a Telegram invoice."""

    total: Decimal
    currency: str
    currency_symbol: str
    provider_token: str
    provider_data: str | None
    need_email: bool
    is_ru: bool


def calculate_invoice_total(
    contact_pricing_price: Decimal,
    order_price: Decimal,
    bloggers_needed: int,
    tax_rate: Decimal,
    is_ru: bool,
) -> Decimal:
    """Calculate invoice total. Single source of truth.

    RU: total = contact_pricing_price
    Intl: (pricing + order_price * bloggers) * (1 + tax_rate)
    """
    if is_ru:
        return contact_pricing_price
    base = contact_pricing_price + order_price * bloggers_needed
    return (base * (1 + tax_rate)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


@dataclass(slots=True)
class PaymentService:
    """Telegram payment service. Moves order to PENDING_MODERATION."""

    user_repo: UserRepository
    advertiser_repo: AdvertiserProfileRepository
    order_repo: OrderRepository
    payment_repo: PaymentRepository
    pricing_repo: ContactPricingRepository
    country_repo: CountryRepository | None = None
    metrics_collector: Optional[Any] = None
    transaction_manager: TransactionManager | None = None
    capture_repository: FinancialCaptureRepository | None = None
    capture_account: str = ""

    async def confirm_telegram_payment(
        self,
        user_id: UUID,
        order_id: UUID,
        provider_payment_charge_id: str,
        total_amount: int,
        currency: str,
        receipt: PaymentSuccess | None = None,
    ) -> Payment:
        """Confirm a Telegram payment and activate order."""

        if self.transaction_manager is None:
            raise ValueError(
                "PaymentService needs transaction_manager for atomic payment."
            )

        return await self._confirm_telegram_payment_impl(
            user_id,
            order_id,
            provider_payment_charge_id,
            total_amount,
            currency,
            receipt,
        )

    async def get_order(self, order_id: UUID) -> Order | None:
        """Fetch order by id within a transaction boundary."""

        async def _run(session: object | None):
            return await self.order_repo.get_by_id(order_id, session=session)

        return await with_optional_tx(self.transaction_manager, _run)

    async def calculate_invoice_data(
        self,
        order: Order,
        user_country: str | None,
        config: AppConfig,
    ) -> InvoiceData | None:
        """Build invoice data for an order. Returns None if pricing missing."""
        if order.financial_version is not None:
            if (
                self.capture_repository is None
                or self.transaction_manager is None
            ):
                raise OrderCreationError("v1_invoice_not_configured")
            async with self.transaction_manager.transaction() as session:
                total, currency = await self.capture_repository.issue(
                    order.order_id,
                    order.advertiser_id,
                    self.capture_account,
                    session=session,
                )
            return InvoiceData(
                total,
                currency,
                config.market.currency_symbol,
                config.bot.telegram_provider_token,
                build_receipt_provider_data(
                    total,
                    currency,
                    config.market.receipt_service_description,
                ),
                True,
                True,
            )
        country_code = (user_country or "ru").lower()
        is_ru = country_code == "ru"

        async def _run(session: object | None) -> InvoiceData | None:
            pricing = await self.pricing_repo.get_by_bloggers_count(
                order.bloggers_needed,
                country_code=country_code,
                session=session,
            )
            if pricing is None:
                return None

            tax_rate = Decimal("0")
            currency_symbol = config.market.currency_symbol
            if not is_ru and self.country_repo is not None:
                country = await self.country_repo.get_by_code(
                    country_code, session=session
                )
                if country:
                    tax_rate = country.tax_rate
                    currency_symbol = country.currency_symbol

            total = calculate_invoice_total(
                contact_pricing_price=pricing.price,
                order_price=Decimal(str(order.price)),
                bloggers_needed=order.bloggers_needed,
                tax_rate=tax_rate,
                is_ru=is_ru,
            )

            if is_ru:
                provider_token = config.bot.telegram_provider_token
            else:
                provider_token = config.bot.telegram_provider_token_intl

            receipt_desc = (
                config.market.receipt_service_description
                or DEFAULT_RECEIPT_SERVICE_DESCRIPTION
            )
            provider_data = (
                build_receipt_provider_data(
                    float(total), pricing.currency, receipt_desc
                )
                if is_ru
                else None
            )

            return InvoiceData(
                total=total,
                currency=pricing.currency,
                currency_symbol=currency_symbol,
                provider_token=provider_token,
                provider_data=provider_data,
                need_email=is_ru,
                is_ru=is_ru,
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def validate_order_for_invoice(
        self,
        order_id: UUID,
        user_id: UUID,
        user_country: str | None,
        config: AppConfig,
    ) -> tuple[Order, InvoiceData] | str:
        """Validate order and build invoice data.

        Returns (order, invoice_data) on success or an error key string.
        """
        order = await self.get_order(order_id)
        if order is None:
            return "msg_order_not_found"
        if order.advertiser_id != user_id:
            return "msg_order_not_yours"
        if order.status != OrderStatus.NEW:
            return "msg_order_not_new"
        invoice_data = await self.calculate_invoice_data(
            order, user_country, config
        )
        if invoice_data is None:
            return "msg_pricing_not_configured"
        if not invoice_data.provider_token:
            return "msg_payment_provider_not_configured"
        return order, invoice_data

    async def _validate_payment_amount(
        self,
        user: Any,
        order: Order,
        total_amount: int,
        session: object,
    ) -> None:
        """Validate that total_amount matches expected invoice total."""
        country_code = (user.country or "ru").lower()
        is_ru = country_code == "ru"
        pricing = await self.pricing_repo.get_by_bloggers_count(
            order.bloggers_needed,
            country_code=country_code,
            session=session,
        )
        if pricing is None:
            raise OrderCreationError(
                "Contact pricing not configured for this bloggers count."
            )
        tax_rate = Decimal("0")
        if not is_ru and self.country_repo is not None and user.country:
            country_obj = await self.country_repo.get_by_code(
                country_code, session=session
            )
            if country_obj:
                tax_rate = country_obj.tax_rate
        expected = calculate_invoice_total(
            pricing.price,
            Decimal(str(order.price)),
            order.bloggers_needed,
            tax_rate,
            is_ru,
        )
        expected_amount_minor = int(expected * 100)
        if total_amount != expected_amount_minor:
            raise OrderCreationError(
                "Payment amount does not match order price."
            )

    async def _capture_v1(
        self,
        order: Order,
        user_id: UUID,
        external_id: str,
        amount: int,
        currency: str,
        receipt: PaymentSuccess | None,
        session: object,
    ) -> Payment:
        if self.capture_repository is None or receipt is None:
            raise OrderCreationError("trusted_v1_capture_required")
        if (
            receipt.provider_payment_charge_id != external_id
            or receipt.total_amount != amount
            or receipt.currency != currency
            or receipt.invoice_payload != str(order.order_id)
        ):
            raise OrderCreationError("capture_receipt_mismatch")
        return await self.capture_repository.capture(
            order.order_id,
            user_id,
            self.capture_account,
            receipt,
            session=session,
        )

    async def _locked_payment_order(
        self, order_id: UUID, user_id: UUID, session: object
    ) -> Order:
        # Quote lock order: advisory identity, then order FOR UPDATE.
        if self.capture_repository is not None:
            await self.capture_repository.lock_order(order_id, session=session)
        order = await self.order_repo.get_by_id_for_update(
            order_id, session=session
        )
        if order is None:
            raise OrderCreationError("Order not found.")
        if order.advertiser_id != user_id:
            raise OrderCreationError("Order does not belong to advertiser.")
        return order

    async def _confirm_telegram_payment_impl(
        self,
        user_id: UUID,
        order_id: UUID,
        provider_payment_charge_id: str,
        total_amount: int,
        currency: str,
        receipt: PaymentSuccess | None = None,
    ) -> Payment:
        """Confirm payment (assumes transaction_manager is set)."""

        assert self.transaction_manager is not None
        async with self.transaction_manager.transaction() as session:
            user = await self.user_repo.get_by_id(user_id, session=session)
            if user is None:
                raise UserNotFoundError("Advertiser not found.")
            if (
                await self.advertiser_repo.get_by_user_id(
                    user_id, session=session
                )
                is None
            ):
                raise OrderCreationError("Advertiser profile is not set.")

            order = await self._locked_payment_order(order_id, user_id, session)

            if order.financial_version is not None:
                return await self._capture_v1(
                    order,
                    user_id,
                    provider_payment_charge_id,
                    total_amount,
                    currency,
                    receipt,
                    session,
                )

            existing = await self.payment_repo.get_by_order(
                order_id, session=session
            )
            if existing and existing.status == PaymentStatus.PAID:
                # A captured payment owns its provider identity. Changing the
                # user's country later must not reinterpret an old receipt.
                if (
                    existing.order_id != order_id
                    or existing.external_id != provider_payment_charge_id
                    or existing.currency != currency
                    or existing.provider not in {PROVIDER_RU, PROVIDER_INTL}
                    or Decimal(str(existing.amount)) * 100 != total_amount
                ):
                    raise OrderCreationError(
                        "Payment replay identity mismatch."
                    )
                return existing

            if order.status != OrderStatus.NEW:
                raise OrderCreationError("Order is not in NEW status.")

            await self._validate_payment_amount(
                user, order, total_amount, session
            )

            country_code = (user.country or "ru").lower()
            is_ru = country_code == "ru"
            provider = PROVIDER_RU if is_ru else PROVIDER_INTL

            now = datetime.now(timezone.utc)
            if existing is not None:
                payment = replace(
                    existing,
                    status=PaymentStatus.PAID,
                    amount=round(total_amount / 100, 2),
                    currency=currency,
                    external_id=provider_payment_charge_id,
                    provider=provider,
                    paid_at=now,
                    updated_at=now,
                )
            else:
                payment = Payment(
                    payment_id=uuid4(),
                    order_id=order_id,
                    provider=provider,
                    status=PaymentStatus.PAID,
                    amount=round(total_amount / 100, 2),
                    currency=currency,
                    external_id=provider_payment_charge_id,
                    created_at=now,
                    paid_at=now,
                )
            await self.payment_repo.save(payment, session=session)
            order_pending = replace(
                order, status=OrderStatus.PENDING_MODERATION
            )
            await self.order_repo.save(order_pending, session=session)

        logger.info(
            "Payment confirmed",
            extra={
                "payment_id": str(payment.payment_id),
                "order_id": str(order_id),
                "user_id": str(user_id),
                "amount": float(payment.amount),
                "currency": payment.currency,
                "external_id": payment.external_id,
                "event_type": "payment.confirmed",
            },
        )

        return payment

"""Atomic v1 invoice/capture adapter. Never infers money from legacy tariffs.

The intent is a durable outbox record plus a PENDING payment (quote freeze).
The capture outbox PK is also the provider/account scoped transaction identity.
Message.date is Telegram protocol message time, not bank settlement time.
All writes use the caller's transaction; there are no sends or commits here.
"""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select, text

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.messenger.dto import PaymentSuccess
from ugc_bot.application.services.creator_identity_history_service import (
    CreatorIdentityHistoryService,
)
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicyService,
)
from ugc_bot.domain.entities import Payment
from ugc_bot.domain.enums import OrderStatus, PaymentStatus
from ugc_bot.domain.financial import utc
from ugc_bot.domain.financial_tariff import require_invoice_total
from ugc_bot.domain.identity_history import IdentityHistoryUnavailable
from ugc_bot.domain.refund_rules import RefundRules
from ugc_bot.infrastructure.db.models import (
    FinancialPolicyVersionModel,
    OrderItemModel,
    OrderModel,
    OutboxEventModel,
    PaymentItemAllocationModel,
    PaymentModel,
    UserModel,
    UserReferralBindingModel,
)
from ugc_bot.infrastructure.db.repositories.financial_items import (
    SqlAlchemyFinancialItemRepository,
    _session,
)
from ugc_bot.infrastructure.db.repositories.financial_ledger import _canonical
from ugc_bot.infrastructure.db.repositories.financial_policy import (
    decode_policy_version,
)
from ugc_bot.infrastructure.db.repositories.orders import _to_payment_entity
from ugc_bot.infrastructure.db.repositories.payment_allocations import (
    SqlAlchemyPaymentAllocationRepository,
)

PROVIDER = "yookassa_telegram"


def intent_id(order_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"ugc:financial:intent:{order_id}")


def capture_id(account: str, external_id: str) -> UUID:
    # Length-delimited components cannot alias through separators in IDs.
    return uuid5(
        NAMESPACE_URL,
        f"ugc:capture:{PROVIDER}:{len(account)}:{account}:{external_id}",
    )


class SqlAlchemyFinancialCaptureRepository:
    def __init__(
        self,
        policy_service: FinancialPolicyService,
        *,
        history: CreatorIdentityHistoryService | None = None,
    ) -> None:
        self.policy_service = policy_service
        self.history = history
        self.allocations = SqlAlchemyPaymentAllocationRepository()

    async def lock_payer(self, client_id: UUID, *, session: object) -> None:
        # Before order coordination, including the outer payment service.
        # Prevent User deletion/PK cascades from inverting order→history locks.
        row = await _session(session).scalar(
            select(UserModel.user_id)
            .where(UserModel.user_id == client_id)
            .with_for_update(key_share=True)
        )
        if row is None:
            raise OrderCreationError("capture_order_owner_mismatch")

    async def lock_order(self, order_id: UUID, *, session: object) -> None:
        await SqlAlchemyFinancialItemRepository().lock_order(
            order_id, session=session
        )

    async def _locked(self, order_id: UUID, client_id: UUID, session: object):
        await self.lock_payer(client_id, session=session)
        await self.lock_order(order_id, session=session)
        db = _session(session)
        order = await db.scalar(
            select(OrderModel)
            .where(OrderModel.order_id == order_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if order is None or order.advertiser_id != client_id:
            raise OrderCreationError("capture_order_owner_mismatch")
        if order.complimentary:
            raise OrderCreationError("complimentary_order_not_payable")
        if order.financial_version is None:
            raise OrderCreationError("financial_order_required")
        items = list(
            (
                await db.scalars(
                    select(OrderItemModel)
                    .where(OrderItemModel.order_id == order_id)
                    .order_by(OrderItemModel.ordinal)
                )
            ).all()
        )
        if not items or any(
            i.policy_version != order.financial_version or i.currency != "RUB"
            for i in items
        ):
            raise OrderCreationError("approved_quote_required")
        return db, order, items

    async def _policy(self, db, order, items, at: datetime, *, issuing: bool):
        stored = await db.get(
            FinancialPolicyVersionModel, order.financial_version
        )
        if stored is None:
            raise OrderCreationError("approved_policy_required")
        # Issued invoices must finish even if sales are paused.
        # No feature flags are modified, including in this path.
        try:
            policy = decode_policy_version(stored)
            if issuing:
                self.policy_service.validate_for_capture(
                    policy=policy,
                    client_id=order.advertiser_id,
                    order_created_at=order.created_at,
                    financial_version=order.financial_version,
                    selection_due_at=min(i.selection_due_at for i in items),
                    currency="RUB",
                    captured_at=at,
                )
            else:
                _, effective = FinancialPolicyService._approved_policy(
                    policy, order.financial_version
                )
                if (
                    utc(order.created_at) < effective
                    or at < utc(order.created_at)
                    or policy.selection_refund_window is None
                    or policy.selection_refund_window <= timedelta(0)
                    or not policy.terms_reference
                    or not policy.allows_client(order.advertiser_id)
                    or any(utc(i.selection_due_at) <= at for i in items)
                ):
                    raise ValueError("invalid_capture_policy")
            if any(
                i.selection_minor != policy.selection_minor
                or i.accompaniment_minor not in (0, policy.accompaniment_minor)
                or i.quote_payload.get("client_id") != str(order.advertiser_id)
                or i.quote_payload.get("terms_reference")
                != policy.terms_reference
                or (
                    RefundRules.from_document(i.quote_payload["refund_rules"])
                    if "refund_rules" in i.quote_payload
                    else None
                )
                != policy.refund_rules
                for i in items
            ):
                raise ValueError("quote_policy_mismatch")
        except ValueError as exc:
            raise OrderCreationError(str(exc)) from exc

    async def issue(
        self, order_id: UUID, client_id: UUID, account: str, *, session: object
    ) -> tuple[Decimal, str]:
        db, order, items = await self._locked(order_id, client_id, session)
        if not account.strip():
            raise OrderCreationError("capture_account_required")
        total = sum(i.selection_minor + i.accompaniment_minor for i in items)
        try:
            require_invoice_total(total)
        except ValueError as error:
            raise OrderCreationError(str(error)) from error
        identity = dict(
            order_id=str(order_id),
            client_id=str(client_id),
            provider=PROVIDER,
            account=account,
            currency="RUB",
            amount_minor=total,
            policy_version=order.financial_version,
            quote_key=items[0].quote_key,
            components=[
                [str(i.paid_item_id), i.selection_minor, i.accompaniment_minor]
                for i in items
            ],
        )
        existing = await db.get(OutboxEventModel, intent_id(order_id))
        if existing is not None:
            if existing.payload != identity:
                raise OrderCreationError("capture_intent_conflict")
            return Decimal(total) / 100, "RUB"
        if order.status != OrderStatus.NEW or any(
            i.captured_at is not None for i in items
        ):
            raise OrderCreationError("uncaptured_new_order_required")
        await self._policy(
            db, order, items, datetime.now(timezone.utc), issuing=True
        )
        if (
            await db.scalar(
                select(PaymentModel).where(PaymentModel.order_id == order_id)
            )
            is not None
        ):
            raise OrderCreationError("payment_already_issued")
        db.add(
            PaymentModel(
                payment_id=uuid4(),
                order_id=order_id,
                provider=PROVIDER,
                status=PaymentStatus.PENDING,
                amount=Decimal(total) / 100,
                currency="RUB",
                external_id=f"intent:{order_id}",
                financial_version=order.financial_version,
            )
        )
        db.add(
            OutboxEventModel(
                event_id=intent_id(order_id),
                event_type="financial.capture_intent",
                aggregate_id=str(order_id),
                aggregate_type="order",
                payload=identity,
            )
        )
        await db.flush()
        return Decimal(total) / 100, "RUB"

    @staticmethod
    def _receipt_time(
        receipt: PaymentSuccess, order_id: UUID, account: str
    ) -> datetime:
        try:
            at = (
                utc(receipt.protocol_message_at)
                if receipt.protocol_message_at is not None
                else None
            )
        except ValueError as exc:
            raise OrderCreationError("trusted_protocol_time_required") from exc
        if (
            at is None
            or not receipt.telegram_payment_charge_id
            or not receipt.provider_payment_charge_id
            or not account.strip()
            or receipt.invoice_payload != str(order_id)
            or type(receipt.total_amount) is not int
        ):
            raise OrderCreationError("trusted_protocol_receipt_required")
        return at

    async def _check_external_scope(
        self, db, payment, account: str, external_id: str
    ) -> None:
        prior = (
            await db.scalars(
                select(PaymentModel).where(
                    PaymentModel.provider == PROVIDER,
                    PaymentModel.external_id == external_id,
                    PaymentModel.payment_id != payment.payment_id,
                )
            )
        ).all()
        for other in prior:
            intent = await db.get(OutboxEventModel, intent_id(other.order_id))
            # Legacy rows have no provable account scope: fail closed.
            if intent is None or intent.payload.get("account") == account:
                raise OrderCreationError("capture_external_id_conflict")

    async def capture(
        self,
        order_id: UUID,
        client_id: UUID,
        account: str,
        receipt: PaymentSuccess,
        *,
        session: object,
    ) -> Payment:
        db, order, items = await self._locked(order_id, client_id, session)
        at = self._receipt_time(receipt, order_id, account)
        intent = await db.get(OutboxEventModel, intent_id(order_id))
        expected = intent.payload if intent is not None else {}
        if (
            expected.get("provider") != PROVIDER
            or expected.get("account") != account
            or expected.get("client_id") != str(client_id)
            or expected.get("currency") != receipt.currency
            or expected.get("amount_minor") != receipt.total_amount
            or expected.get("policy_version") != order.financial_version
            or expected.get("quote_key") != items[0].quote_key
            or expected.get("components")
            != [
                [str(i.paid_item_id), i.selection_minor, i.accompaniment_minor]
                for i in items
            ]
        ):
            raise OrderCreationError("capture_intent_mismatch")
        event_id = capture_id(account, receipt.provider_payment_charge_id)
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": str(event_id)},
        )
        event = await db.get(OutboxEventModel, event_id)
        payment = await db.scalar(
            select(PaymentModel)
            .where(PaymentModel.order_id == order_id)
            .with_for_update()
        )
        identity = dict(
            expected,
            external_id=receipt.provider_payment_charge_id,
            telegram_payment_charge_id=receipt.telegram_payment_charge_id,
            captured_at=at.isoformat(),
            captured_at_source="telegram.message.date",
        )
        if event is not None:
            if (
                event.payload.get("capture") != identity
                or payment is None
                or payment.captured_minor != receipt.total_amount
            ):
                raise OrderCreationError("capture_external_id_conflict")
            # Return the original receipt even after status changes.
            return _to_payment_entity(payment)
        if (
            payment is None
            or payment.status != PaymentStatus.PENDING
            or payment.captured_minor is not None
            or payment.provider != PROVIDER
            or payment.currency != receipt.currency
            or Decimal(str(payment.amount)) * 100 != receipt.total_amount
            or payment.financial_version != order.financial_version
            or order.status != OrderStatus.NEW
            or any(i.captured_at is not None for i in items)
        ):
            raise OrderCreationError("capture_payment_conflict")
        await self._check_external_scope(
            db, payment, account, receipt.provider_payment_charge_id
        )
        await self._policy(db, order, items, at, issuing=False)
        attribution = await self._client_attribution(client_id, at, db)
        payment.status = PaymentStatus.PAID
        payment.external_id = receipt.provider_payment_charge_id
        payment.captured_minor = receipt.total_amount
        payment.paid_at = at
        payment.updated_at = at
        for item in items:
            item.captured_at = at
            item.selection_state = "paid"
        # Capture all items before allocation immutability takes effect.
        await db.flush()
        for item in items:
            for component, amount in [
                ("selection", item.selection_minor),
                ("accompaniment", item.accompaniment_minor),
            ]:
                if amount:
                    await self.allocations.add(
                        PaymentItemAllocationModel(
                            allocation_key=f"{payment.payment_id}:{item.paid_item_id}:{component}",
                            payment_id=payment.payment_id,
                            paid_item_id=item.paid_item_id,
                            order_id=order_id,
                            component=component,
                            amount_minor=amount,
                            currency=item.currency,
                        ),
                        session=db,
                    )
        db.add(
            OutboxEventModel(
                event_id=event_id,
                event_type="financial.client_snapshot_requested",
                aggregate_id=str(order_id),
                aggregate_type="order",
                payload={
                    "capture": identity,
                    "payment_id": str(payment.payment_id),
                    **attribution,
                    "selection_bases": [
                        [str(i.paid_item_id), i.selection_minor] for i in items
                    ],
                },
            )
        )
        order.status = OrderStatus.PENDING_MODERATION
        await db.flush()
        return _to_payment_entity(payment)

    async def _client_attribution(self, client_id, at, db):
        if self.history is None:
            # Existing internal capture callers have no authoritative history
            # dependency. The monetary consumer still verifies their payload.
            binding = await db.scalar(
                select(UserReferralBindingModel).where(
                    UserReferralBindingModel.referred_user_id == client_id,
                    UserReferralBindingModel.created_at <= at,
                )
            )
            client = await db.get(UserModel, client_id)
            return {
                "client_registered_at": client.created_at.isoformat()
                if client
                else None,
                "client_referrer_id": str(binding.referrer_user_id)
                if binding
                else None,
            }
        # Payer→order→payment are already locked. This precedes item mutation;
        # no new User locks may be acquired after taking the shared barrier.
        await self.history.acquire_snapshot_barrier(session=db)
        try:
            fact = await self.history.resolve_direct_binding(
                client_id, at, session=db
            )
        except IdentityHistoryUnavailable as error:
            # A real captured receipt is recorded even when no commission can
            # be assessed. The consumer will retain it unresolved, never infer
            # a historical recipient or registration from today's profile.
            return {
                "client_registered_at": None,
                "client_referrer_id": None,
                "attribution_history": {
                    "status": "unavailable",
                    "reason": str(error),
                },
            }
        return {
            "client_registered_at": fact.registered_at.isoformat()
            if fact.registered_at is not None
            else None,
            "client_referrer_id": str(fact.referrer_user_id)
            if fact.referrer_user_id is not None
            else None,
            "attribution_history": {
                "status": "assessed",
                "fact": _canonical(asdict(fact)),
            },
        }

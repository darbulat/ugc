"""One active provider reservation per order, shared with Telegram checkout."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import exists, insert, select, update

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.domain.browser_checkout import BrowserInvoice, browser_invoice_url
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.infrastructure.db.browser_checkout_models import (
    ACTIVE_STATES,
)
from ugc_bot.infrastructure.db.browser_checkout_models import (
    BROWSER_ATTEMPTS as ATTEMPTS,
)
from ugc_bot.infrastructure.db.checkout_models import (
    AUTHORIZATIONS,
    INBOX,
    REVIEWS,
)
from ugc_bot.infrastructure.db.models import OrderModel
from ugc_bot.infrastructure.db.repositories.financial_items import _session


def unresolved_telegram_payment(order_id):
    return exists().where(
        AUTHORIZATIONS.c.order_id == order_id,
        ~exists().where(
            REVIEWS.c.authorization_id == AUTHORIZATIONS.c.authorization_id
        ),
    ) | exists().where(INBOX.c.order_id == order_id)


class SqlBrowserCheckout:
    def __init__(self, capture, telegram_account, shop_id, test_mode, notices):
        self.capture = capture
        self.telegram_account = telegram_account
        self.shop_id = shop_id
        self.test_mode = test_mode
        self.notices = notices

    async def view(self, order_id, *, session):
        db = _session(session)
        order = await db.get(OrderModel, order_id)
        if (
            order is None
            or order.financial_version is None
            or order.currency != "RUB"
        ):
            return None
        row = (
            (
                await db.execute(
                    select(
                        ATTEMPTS.c.state,
                        ATTEMPTS.c.invoice_url,
                        ATTEMPTS.c.expires_at,
                    )
                    .where(ATTEMPTS.c.order_id == order_id)
                    .order_by(ATTEMPTS.c.created_at.desc())
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        if order.complimentary or (
            order.status != OrderStatus.NEW and row is None
        ):
            return None
        if row and row.state in (*ACTIVE_STATES, "paid"):
            return {
                "state": row.state,
                "url": browser_invoice_url(row.invoice_url)
                if row.state == "pending"
                and row.invoice_url
                and row.expires_at > datetime.now(timezone.utc)
                else None,
            }
        if order.status != OrderStatus.NEW:
            return None
        if await db.scalar(select(unresolved_telegram_payment(order_id))):
            return {"state": "telegram_pending"}
        return {"state": row.state if row else "available"}

    async def reserve(self, order_id: UUID, email: str, receipt, *, session):
        db = _session(session)
        owner = await db.scalar(
            select(OrderModel.advertiser_id).where(
                OrderModel.order_id == order_id
            )
        )
        if owner is None:
            raise LookupError("order_not_found")
        _, order, items = await self.capture._locked(order_id, owner, db)
        if order.status != OrderStatus.NEW or order.currency != "RUB":
            raise OrderCreationError("order_not_payable")
        active = await db.scalar(
            select(ATTEMPTS.c.attempt_id).where(
                ATTEMPTS.c.order_id == order_id,
                ATTEMPTS.c.state.in_(ACTIVE_STATES),
            )
        )
        if active is not None:
            return
        if await db.scalar(select(unresolved_telegram_payment(order_id))):
            raise OrderCreationError("telegram_payment_pending")
        now = datetime.now(timezone.utc)
        # Leave time for the provider to finish a payment started before expiry.
        expires_at = min(
            now + timedelta(hours=2),
            min(i.selection_due_at for i in items) - timedelta(minutes=30),
        ).replace(microsecond=0)
        if expires_at < now + timedelta(minutes=15):
            raise OrderCreationError("browser_payment_quote_expiring")
        await self.capture._policy(db, order, items, now, issuing=True)
        total, currency = await self.capture.issue(
            order_id, owner, self.telegram_account, session=db
        )
        attempt_id = uuid4()
        amount = {"value": f"{total:.2f}", "currency": currency}
        metadata = {"order_id": str(order_id), "attempt_id": str(attempt_id)}
        description = f"Услуги UMC · заказ №{order_id.hex[:8].upper()}"
        await db.execute(
            insert(ATTEMPTS).values(
                attempt_id=attempt_id,
                order_id=order_id,
                client_id=owner,
                shop_id=self.shop_id,
                test_mode=self.test_mode,
                amount_minor=int(total * Decimal(100)),
                request={
                    "payment_data": {
                        "amount": amount,
                        "capture": True,
                        "description": description,
                        "metadata": metadata,
                        "receipt": receipt(total, currency)
                        | {"customer": {"email": email}},
                    },
                    "cart": [
                        {
                            "description": description,
                            "price": amount,
                            "quantity": 1,
                        }
                    ],
                    "delivery_method_data": {"type": "self"},
                    "locale": "ru_RU",
                    "expires_at": expires_at.isoformat(),
                    "description": description,
                    "metadata": metadata,
                },
                state="creating",
                created_at=now,
                expires_at=expires_at,
                next_check_at=now,
            )
        )

    async def claim(self, order_id, *, session):
        db = _session(session)
        now = datetime.now(timezone.utc)
        query = (
            select(ATTEMPTS)
            .where(
                ATTEMPTS.c.state.in_(ACTIVE_STATES),
                ATTEMPTS.c.shop_id == self.shop_id,
                ATTEMPTS.c.test_mode == self.test_mode,
                ATTEMPTS.c.next_check_at <= now,
                (
                    ATTEMPTS.c.lease_until.is_(None)
                    | (ATTEMPTS.c.lease_until <= now)
                ),
            )
            .order_by(ATTEMPTS.c.next_check_at, ATTEMPTS.c.attempt_id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if order_id is not None:
            query = query.where(ATTEMPTS.c.order_id == order_id)
        row = (await db.execute(query)).mappings().one_or_none()
        if row is None:
            return None
        claim_id = uuid4()
        await db.execute(
            update(ATTEMPTS)
            .where(ATTEMPTS.c.attempt_id == row.attempt_id)
            .values(lease_until=now + timedelta(seconds=45), claim_id=claim_id)
        )
        return SimpleNamespace(**(dict(row) | {"claim_id": claim_id}))

    async def finish(
        self, claim, invoice: BrowserInvoice | None, state=None, *, session
    ):
        db = _session(session)
        if invoice and invoice.payment:
            # Match the native lock order. Do not hold a task lock while
            # acquiring the owner/order locks used by authorization.
            await self.capture._locked(claim.order_id, claim.client_id, db)
        result = await db.execute(
            select(ATTEMPTS.c.attempt_id)
            .where(
                ATTEMPTS.c.attempt_id == claim.attempt_id,
                ATTEMPTS.c.claim_id == claim.claim_id,
                ATTEMPTS.c.state.in_(ACTIVE_STATES),
            )
            .with_for_update()
        )
        if result.scalar_one_or_none() is None:
            return
        if invoice is not None:
            state = invoice.state
        values = {
            "claim_id": None,
            "lease_until": None,
            "next_check_at": (
                datetime.now(timezone.utc)
                + timedelta(seconds=20 if invoice else 60)
                if (state or claim.state) in ACTIVE_STATES
                else None
            ),
            "state": state or claim.state,
        }
        if invoice:
            values.update(
                invoice_id=invoice.invoice_id,
                invoice_url=invoice.url,
                request=None,
            )
        if state not in ACTIVE_STATES and state is not None:
            values["request"] = None
        if invoice and invoice.payment:
            proof = invoice.payment
            if (
                proof.invoice_id != invoice.invoice_id
                or proof.shop_id != self.shop_id
                or proof.amount_minor != claim.amount_minor
                or await db.scalar(
                    select(unresolved_telegram_payment(claim.order_id))
                )
            ):
                raise OrderCreationError("browser_capture_payment_conflict")
            values.update(
                payment_id=proof.payment_id, captured_at=proof.captured_at
            )
        await db.execute(
            update(ATTEMPTS)
            .where(ATTEMPTS.c.attempt_id == claim.attempt_id)
            .values(**values)
        )
        if invoice and invoice.payment:
            # Release the reservation and book the capture atomically. Order
            # mutations remain guarded until this transaction commits.
            await self.capture.capture_browser(
                claim.order_id, claim.client_id, invoice.payment, session=db
            )
            if self.notices is not None:
                await self.notices.enqueue(claim.order_id, "paid", session=db)

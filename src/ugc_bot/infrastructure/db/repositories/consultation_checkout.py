"""Issue and reconcile independent consultation invoices."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import insert, select, update

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.domain.browser_checkout import browser_invoice_url
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.domain.order_intake import CONSULTATION_MINOR
from ugc_bot.infrastructure.db.browser_checkout_models import ACTIVE_STATES
from ugc_bot.infrastructure.db.consultation_models import (
    CONSULTATION_ATTEMPTS as attempts,
)
from ugc_bot.infrastructure.db.consultation_models import (
    CONSULTATIONS as consultations,
)
from ugc_bot.infrastructure.db.models import OrderModel
from ugc_bot.infrastructure.db.order_intake_models import is_combined_checkout
from ugc_bot.infrastructure.db.order_notice_models import (
    CONSULTATION_DELIVERIES,
    CONSULTATION_EVENTS,
)
from ugc_bot.infrastructure.db.repositories.browser_checkout import (
    BrowserAttemptClaims,
    invoice_outcome,
    invoice_request,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.repositories.order_notices import (
    SqlAlchemyOrderNoticeRepository,
)


def consultation_notices(*, order_card_recipients=frozenset()):
    return SqlAlchemyOrderNoticeRepository(
        events_table=CONSULTATION_EVENTS,
        deliveries_table=CONSULTATION_DELIVERIES,
        order_card_recipients=order_card_recipients,
    )


class SqlConsultationCheckout(BrowserAttemptClaims):
    def __init__(self, shop_id, test_mode):
        super().__init__(attempts, shop_id, test_mode)

    @staticmethod
    async def _order(db, token, *, lock=False):
        query = (
            select(
                OrderModel.order_id, OrderModel.advertiser_id, OrderModel.status
            )
            .join(
                consultations, consultations.c.order_id == OrderModel.order_id
            )
            .where(
                consultations.c.token == token,
                ~is_combined_checkout(OrderModel.order_id),
                consultations.c.client_id == OrderModel.advertiser_id,
            )
        )
        if lock:
            query = query.with_for_update(of=OrderModel)
        order = (await db.execute(query)).one_or_none()
        if order is None:
            raise LookupError("browser_link_not_found")
        return order

    @staticmethod
    async def _attempt(db, order_id):
        return (
            await db.execute(
                select(
                    attempts.c.state,
                    attempts.c.invoice_url,
                    attempts.c.expires_at,
                )
                .where(attempts.c.order_id == order_id)
                .order_by(attempts.c.created_at.desc())
                .limit(1)
            )
        ).one_or_none()

    async def buyer_view(self, token, *, session):
        db = _session(session)
        order = await self._order(db, token)
        attempt = await self._attempt(db, order.order_id)
        if attempt is not None and attempt.state in (*ACTIVE_STATES, "paid"):
            url = (
                browser_invoice_url(attempt.invoice_url)
                if attempt.state == "pending"
                and attempt.invoice_url
                and attempt.expires_at > datetime.now(timezone.utc)
                and order.status
                not in {OrderStatus.CLOSED, OrderStatus.DELETED}
                else None
            )
            return {"state": attempt.state, "url": url}
        if order.status in {OrderStatus.CLOSED, OrderStatus.DELETED}:
            return None
        return {"state": attempt.state if attempt else "available"}

    async def reserve(self, token, email, receipt, *, session):
        db = _session(session)
        order = await self._order(db, token, lock=True)
        if order.status in {OrderStatus.CLOSED, OrderStatus.DELETED}:
            raise OrderCreationError("order_not_payable")
        previous = await self._attempt(db, order.order_id)
        if previous and previous.state in (*ACTIVE_STATES, "paid"):
            return order.order_id
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(hours=2)).replace(microsecond=0)
        attempt_id = uuid4()
        await db.execute(
            insert(attempts).values(
                attempt_id=attempt_id,
                order_id=order.order_id,
                client_id=order.advertiser_id,
                shop_id=self.shop_id,
                test_mode=self.test_mode,
                amount_minor=CONSULTATION_MINOR,
                request=invoice_request(
                    order.order_id,
                    attempt_id,
                    Decimal(CONSULTATION_MINOR) / 100,
                    "RUB",
                    expires_at,
                    email,
                    receipt,
                    "Разбор запуска UGC · заказ "
                    f"№{order.order_id.hex[:8].upper()}",
                ),
                state="creating",
                created_at=now,
                expires_at=expires_at,
                next_check_at=now,
            )
        )
        return order.order_id

    async def finish(self, claim, invoice, state=None, *, session):
        db = _session(session)
        values = invoice_outcome(claim, invoice, state)
        proof = invoice.payment if invoice else None
        if proof is not None:
            if (
                proof.invoice_id != invoice.invoice_id
                or proof.shop_id != self.shop_id
                or proof.amount_minor != CONSULTATION_MINOR
            ):
                raise OrderCreationError("browser_capture_payment_conflict")
            values.update(
                payment_id=proof.payment_id, captured_at=proof.captured_at
            )
        finished = await db.scalar(
            update(attempts)
            .where(
                attempts.c.attempt_id == claim.attempt_id,
                attempts.c.claim_id == claim.claim_id,
                attempts.c.state.in_(ACTIVE_STATES),
            )
            .values(**values)
            .returning(attempts.c.order_id)
        )
        if finished and proof is not None and not self.test_mode:
            await consultation_notices().enqueue(finished, "paid", session=db)

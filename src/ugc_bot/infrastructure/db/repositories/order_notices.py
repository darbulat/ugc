"""Atomic event enqueue and short SKIP LOCKED delivery claims."""

from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import Table, case, exists, false, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.application.order_notice_ports import (
    OrderNoticeJob,
    OrderNoticeKind,
)
from ugc_bot.domain.browser_checkout import BROWSER_PROVIDER
from ugc_bot.domain.enums import PaymentStatus
from ugc_bot.infrastructure.db.models import PaymentModel
from ugc_bot.infrastructure.db.order_intake_models import is_combined_checkout
from ugc_bot.infrastructure.db.order_notice_models import (
    ORDER_NOTICE_DELIVERIES as deliveries,
)
from ugc_bot.infrastructure.db.order_notice_models import (
    ORDER_NOTICE_EVENTS as events,
)


def _browser_paid(order_notices):
    return exists().where(
        PaymentModel.order_id == order_notices.c.order_id,
        PaymentModel.provider == BROWSER_PROVIDER,
        PaymentModel.status == PaymentStatus.PAID,
    )


def business_order_card_covers(order_id, event_kind, recipient):
    """A business event owns this recipient's detailed card."""
    delivery = exists().where(
        deliveries.c.order_id == events.c.order_id,
        deliveries.c.event_kind == events.c.event_kind,
        deliveries.c.recipient == recipient,
        deliveries.c.state != "failed",
    )
    return exists().where(
        events.c.order_id == order_id,
        events.c.event_kind == event_kind,
        or_(events.c.expanded.is_(False), delivery),
    )


def _covered_consultation(order_id, event_kind, recipient):
    # Legacy split checkout can pay for the consultation on its own.
    return or_(event_kind == "created", is_combined_checkout(order_id)) & (
        business_order_card_covers(order_id, event_kind, recipient)
    )


class SqlAlchemyOrderNoticeRepository:
    def __init__(
        self,
        browser_paid_recipients: frozenset[str] | None = None,
        *,
        events_table: Table = events,
        deliveries_table: Table = deliveries,
        order_card_recipients: frozenset[str] = frozenset(),
    ) -> None:
        self.browser_paid_recipients = browser_paid_recipients
        self.namespace = (
            "order-notice" if events_table is events else events_table.name
        )
        self.events = events_table
        self.deliveries = deliveries_table
        self.order_card_recipients = order_card_recipients

    async def enqueue(
        self, order_id: UUID, event_kind: OrderNoticeKind, *, session: object
    ) -> None:
        session = cast(AsyncSession, session)
        if event_kind not in {"created", "paid"}:
            raise ValueError("invalid_order_notice_kind")
        await session.execute(
            insert(self.events)
            .values(
                order_id=order_id,
                event_kind=event_kind,
                created_at=datetime.now(timezone.utc),
                expanded=False,
            )
            .on_conflict_do_nothing()
        )

    async def claim(
        self,
        now: datetime,
        admin_recipients: tuple[str, ...],
        *,
        session: object,
    ) -> OrderNoticeJob | None:
        session = cast(AsyncSession, session)
        events, deliveries = self.events, self.deliveries
        # Provider acceptance after a process interruption is ambiguous. Keep it
        # visible for manual resolution instead of risking a duplicate card.
        await session.execute(
            update(deliveries)
            .where(
                deliveries.c.state == "sending", deliveries.c.lease_until <= now
            )
            .values(state="unknown", last_error="delivery_lease_expired")
        )
        await session.execute(
            update(deliveries)
            .where(
                deliveries.c.state == "leased", deliveries.c.lease_until <= now
            )
            .values(
                state=case(
                    (deliveries.c.attempt >= 3, "failed"), else_="pending"
                ),
                last_error="preparation_lease_expired",
                lease_until=now + timedelta(seconds=30),
            )
        )
        browser_recipients = self.browser_paid_recipients
        browser_paid_event = false()
        if browser_recipients is not None:
            browser_paid_event = _browser_paid(events)
            # A delayed "created" card can also include the paid status.
            await session.execute(
                update(deliveries)
                .where(
                    deliveries.c.state.in_(("pending", "leased")),
                    _browser_paid(deliveries),
                    deliveries.c.recipient.not_in(browser_recipients),
                )
                .values(
                    state="failed",
                    last_error="order_notice_recipient_ineligible",
                    lease_until=None,
                )
            )
        if self.order_card_recipients:
            await self._close_redundant_deliveries(session)
        pending = (
            (
                await session.execute(
                    select(events, browser_paid_event.label("browser_paid"))
                    .where(events.c.expanded.is_(False))
                    .order_by(events.c.created_at)
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            )
            .mappings()
            .all()
        )
        admin_addresses = {
            value.strip() for value in admin_recipients if value.strip()
        }
        for event in pending:
            addresses = admin_addresses
            if event["browser_paid"] and browser_recipients is not None:
                addresses = admin_addresses.intersection(browser_recipients)
            if not addresses:
                continue
            for address in sorted(addresses):
                if await self._included_in_order_card(session, event, address):
                    continue
                job_id = uuid5(
                    NAMESPACE_URL,
                    f"{self.namespace}:{event['order_id']}:{event['event_kind']}:{address}",
                )
                await session.execute(
                    insert(deliveries)
                    .values(
                        job_id=job_id,
                        order_id=event["order_id"],
                        event_kind=event["event_kind"],
                        recipient=address,
                        state="pending",
                        attempt=0,
                    )
                    .on_conflict_do_nothing()
                )
            await session.execute(
                update(events)
                .where(
                    events.c.order_id == event["order_id"],
                    events.c.event_kind == event["event_kind"],
                )
                .values(expanded=True)
            )
        row = (
            (
                await session.execute(
                    select(deliveries)
                    .where(
                        deliveries.c.state == "pending",
                        or_(
                            deliveries.c.lease_until.is_(None),
                            deliveries.c.lease_until <= now,
                        ),
                    )
                    .order_by(deliveries.c.job_id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        attempt = row["attempt"] + 1
        await session.execute(
            update(deliveries)
            .where(deliveries.c.job_id == row["job_id"])
            .values(
                state="leased",
                attempt=attempt,
                lease_until=now + timedelta(minutes=2),
            )
        )
        return OrderNoticeJob(
            row["job_id"],
            row["order_id"],
            cast(OrderNoticeKind, row["event_kind"]),
            row["recipient"],
            attempt,
        )

    async def _included_in_order_card(self, session, event, address: str):
        return address in self.order_card_recipients and bool(
            await session.scalar(
                select(
                    _covered_consultation(
                        event["order_id"], event["event_kind"], address
                    )
                )
            )
        )

    async def _close_redundant_deliveries(self, session):
        queued = self.deliveries
        await session.execute(
            update(queued)
            .where(
                queued.c.state.in_(("pending", "leased")),
                queued.c.recipient.in_(self.order_card_recipients),
                _covered_consultation(
                    queued.c.order_id, queued.c.event_kind, queued.c.recipient
                ),
            )
            .values(
                state="failed",
                last_error="included_in_business_order_card",
                lease_until=None,
            )
        )

    async def begin(
        self, job: OrderNoticeJob, now: datetime, *, session: object
    ) -> bool:
        session = cast(AsyncSession, session)
        deliveries = self.deliveries
        statement = update(deliveries).where(
            deliveries.c.job_id == job.job_id,
            deliveries.c.state == "leased",
            deliveries.c.attempt == job.attempt,
            deliveries.c.lease_until > now,
        )
        browser_recipients = self.browser_paid_recipients
        if (
            browser_recipients is not None
            and job.recipient not in browser_recipients
        ):
            statement = statement.where(~_browser_paid(deliveries))
        result = await session.execute(
            statement.values(state="sending").returning(deliveries.c.job_id)
        )
        return result.scalar_one_or_none() is not None

    async def finish(
        self,
        job: OrderNoticeJob,
        state: str,
        reason: str | None,
        *,
        session: object,
        retry_after_seconds: int | None = None,
    ) -> None:
        session = cast(AsyncSession, session)
        deliveries = self.deliveries
        await session.execute(
            update(deliveries)
            .where(
                deliveries.c.job_id == job.job_id,
                deliveries.c.state.in_(("leased", "sending")),
                deliveries.c.attempt == job.attempt,
            )
            .values(
                state=state,
                last_error=reason,
                lease_until=(
                    datetime.now(timezone.utc)
                    + timedelta(
                        seconds=max(30 * job.attempt, retry_after_seconds or 0)
                    )
                )
                if state == "pending"
                else None,
            )
        )

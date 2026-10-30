"""Atomic event enqueue and short SKIP LOCKED delivery claims."""

from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import case, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.application.order_notice_ports import (
    OrderNoticeJob,
    OrderNoticeKind,
)
from ugc_bot.infrastructure.db.order_notice_models import (
    ORDER_NOTICE_DELIVERIES as deliveries,
)
from ugc_bot.infrastructure.db.order_notice_models import (
    ORDER_NOTICE_EVENTS as events,
)


class SqlAlchemyOrderNoticeRepository:
    async def enqueue(
        self, order_id: UUID, event_kind: OrderNoticeKind, *, session: object
    ) -> None:
        session = cast(AsyncSession, session)
        if event_kind not in {"created", "paid"}:
            raise ValueError("invalid_order_notice_kind")
        await session.execute(
            insert(events)
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
        support_recipient: str,
        *,
        session: object,
    ) -> OrderNoticeJob | None:
        session = cast(AsyncSession, session)
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
        pending = (
            (
                await session.execute(
                    select(events)
                    .where(events.c.expanded.is_(False))
                    .order_by(events.c.created_at)
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            )
            .mappings()
            .all()
        )
        for event in pending:
            addresses = {
                value.strip() for value in admin_recipients if value.strip()
            }
            if event["event_kind"] == "created" and support_recipient.strip():
                addresses.add(support_recipient.strip())
            if not addresses:
                continue
            for address in sorted(addresses):
                job_id = uuid5(
                    NAMESPACE_URL,
                    f"order-notice:{event['order_id']}:{event['event_kind']}:{address}",
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

    async def begin(
        self, job: OrderNoticeJob, now: datetime, *, session: object
    ) -> bool:
        session = cast(AsyncSession, session)
        result = await session.execute(
            update(deliveries)
            .where(
                deliveries.c.job_id == job.job_id,
                deliveries.c.state == "leased",
                deliveries.c.attempt == job.attempt,
                deliveries.c.lease_until > now,
            )
            .values(state="sending")
            .returning(deliveries.c.job_id)
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

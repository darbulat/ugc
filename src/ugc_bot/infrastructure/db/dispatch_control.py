"""Durable campaign controls and recipient claims."""

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    Table,
    exists,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import UUID

from ugc_bot.domain.enums import OrderStatus
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import OfferDispatchModel, OrderModel
from ugc_bot.infrastructure.db.repositories.financial_items import _session

CONTROLS = Table(
    "order_dispatch_controls",
    Base.metadata,
    Column(
        "order_id",
        UUID(as_uuid=True),
        ForeignKey("orders.order_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("run", Integer, nullable=False),
    Column("paused", Boolean, nullable=False),
    Column("audience_ready", Boolean, nullable=False),
)

CLAIMS = Table(
    "order_dispatch_claims",
    Base.metadata,
    Column(
        "order_id",
        UUID(as_uuid=True),
        ForeignKey("order_dispatch_controls.order_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "blogger_id",
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("run", Integer, nullable=False),
    Column("rejected", Boolean, nullable=False),
)


class SqlDispatchControl:
    async def current(self, order_id, *, session):
        return (
            await _session(session).execute(
                select(
                    CONTROLS.c.run, CONTROLS.c.paused, CONTROLS.c.audience_ready
                ).where(CONTROLS.c.order_id == order_id)
            )
        ).one_or_none()

    async def start(self, order_id, *, session):
        db = _session(session)
        await db.scalar(
            select(OrderModel.order_id)
            .where(OrderModel.order_id == order_id)
            .with_for_update()
        )
        if await self.current(order_id, session=session) is not None:
            return None
        await _session(session).execute(
            insert(CONTROLS).values(
                order_id=order_id, run=1, paused=False, audience_ready=False
            )
        )
        return 1

    async def change(self, order_id, *, paused, session):
        db = _session(session)
        order = await db.get(OrderModel, order_id, with_for_update=True)
        if (
            order is None
            or order.status != OrderStatus.ACTIVE
            or order.dispatch_stopped
        ):
            return None
        control = await self.current(order_id, session=session)
        if control is None or control.paused == paused:
            return None
        run = control.run if paused else control.run + 1
        await db.execute(
            update(CONTROLS)
            .where(CONTROLS.c.order_id == order_id)
            .values(run=run, paused=paused)
        )
        return run

    async def prepare_audience(self, order_id, blogger_ids, run, *, session):
        db = _session(session)
        order = await db.get(OrderModel, order_id, with_for_update=True)
        control = await self.current(order_id, session=session)
        if not self._can_dispatch(order, control, run):
            return set()
        if not control.audience_ready:
            if blogger_ids:
                await db.execute(
                    insert(CLAIMS),
                    [
                        {
                            "order_id": order_id,
                            "blogger_id": blogger_id,
                            "run": 0,
                            "rejected": False,
                        }
                        for blogger_id in blogger_ids
                    ],
                )
            await db.execute(
                update(CONTROLS)
                .where(CONTROLS.c.order_id == order_id)
                .values(audience_ready=True)
            )
            return set(blogger_ids)
        return set(
            await db.scalars(
                select(CLAIMS.c.blogger_id).where(CLAIMS.c.order_id == order_id)
            )
        )

    @staticmethod
    def _can_dispatch(order, control, run):
        return (
            order is not None
            and order.status == OrderStatus.ACTIVE
            and not order.dispatch_stopped
            and control is not None
            and not control.paused
            and control.run == run
        )

    async def claim(self, order_id, blogger_id, run, *, session):
        """Return stop, skip, or claimed. Commit the claim before sending."""
        db = _session(session)
        order = await db.get(OrderModel, order_id, with_for_update=True)
        control = await self.current(order_id, session=session)
        if not self._can_dispatch(order, control, run):
            return "stop"
        if await db.scalar(
            select(
                exists().where(
                    OfferDispatchModel.order_id == order_id,
                    OfferDispatchModel.blogger_id == blogger_id,
                )
            )
        ):
            return "skip"
        scope = (CLAIMS.c.order_id == order_id) & (
            CLAIMS.c.blogger_id == blogger_id
        )
        previous = (
            await db.execute(
                select(CLAIMS.c.run, CLAIMS.c.rejected).where(scope)
            )
        ).one_or_none()
        if previous is None or not (
            previous.run == 0 or (previous.rejected and previous.run < run)
        ):
            return "skip"
        await db.execute(
            update(CLAIMS).where(scope).values(run=run, rejected=False)
        )
        return "claimed"

    async def reject(self, order_id, blogger_id, run, *, session):
        await _session(session).execute(
            update(CLAIMS)
            .where(
                CLAIMS.c.order_id == order_id,
                CLAIMS.c.blogger_id == blogger_id,
                CLAIMS.c.run == run,
            )
            .values(rejected=True)
        )

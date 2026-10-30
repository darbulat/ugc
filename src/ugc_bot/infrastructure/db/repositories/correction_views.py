"""Bounded owner-filtered navigation over strict correction sources."""

from sqlalchemy import and_, func, or_, select

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.correction_models import TABLE_MAP
from ugc_bot.infrastructure.db.repositories.corrections import (
    SqlAlchemyCorrectionRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session


class SqlAlchemyCorrectionViewRepository(SqlAlchemyCorrectionRepository):
    async def discover_preview(
        self,
        actor_id,
        order_id,
        paid_item_ids,
        *,
        existing_case_id,
        session,
    ):
        return await self._discover(
            actor_id,
            order_id,
            existing_case_id,
            paid_item_ids,
            _session(session),
        )

    async def cases_page(self, actor_id, *, admin, limit, after, session):
        cases, requests = TABLE_MAP["cases"], TABLE_MAP["requests"]
        orders = Base.metadata.tables["orders"]
        source = cases.outerjoin(
            requests, requests.c.case_id == cases.c.case_id
        ).outerjoin(
            orders,
            orders.c.order_id
            == func.coalesce(requests.c.order_id, cases.c.order_id),
        )
        query = select(
            cases,
            *(column.label("request_" + column.name) for column in requests.c),
        ).select_from(source)
        if not admin:
            query = query.where(
                orders.c.advertiser_id == actor_id,
                or_(
                    and_(
                        requests.c.request_id.is_(None),
                        cases.c.client_id == actor_id,
                    ),
                    and_(
                        requests.c.client_id == actor_id,
                        or_(
                            cases.c.client_id.is_(None),
                            cases.c.client_id == actor_id,
                        ),
                        or_(
                            cases.c.order_id.is_(None),
                            requests.c.order_id == cases.c.order_id,
                        ),
                    ),
                ),
            )
        if after is not None:
            query = query.where(cases.c.case_id > after)
        rows = (
            (
                await _session(session).execute(
                    query.order_by(cases.c.case_id).limit(limit + 1)
                )
            )
            .mappings()
            .all()
        )
        return [
            {column.name: row[column.name] for column in cases.c}
            | dict(
                request={
                    column.name: row["request_" + column.name]
                    for column in requests.c
                }
                if row["request_request_id"] is not None
                else None
            )
            for row in rows
        ]

    async def orders_page(self, actor_id, *, limit, after, session):
        orders = Base.metadata.tables["orders"]
        items = Base.metadata.tables["order_items"]
        query = select(orders.c.order_id, orders.c.offer_text).where(
            orders.c.advertiser_id == actor_id,
            select(items.c.paid_item_id)
            .where(
                items.c.order_id == orders.c.order_id,
                items.c.captured_at.is_not(None),
            )
            .exists(),
        )
        if after is not None:
            query = query.where(orders.c.order_id > after)
        db = _session(session)
        rows = (
            (
                await db.execute(
                    query.order_by(orders.c.order_id).limit(limit + 1)
                )
            )
            .mappings()
            .all()
        )
        return [
            dict(
                order_id=row["order_id"],
                title=row["offer_text"][:160],
                items=await self.order_positions(row["order_id"], session=db),
            )
            for row in rows
        ]

    async def order_positions(self, order_id, *, session):
        items = Base.metadata.tables["order_items"]
        orders = Base.metadata.tables["orders"]
        db = _session(session)
        expected_count = await db.scalar(
            select(orders.c.bloggers_needed).where(
                orders.c.order_id == order_id
            )
        )
        positions = (
            (
                await db.execute(
                    select(
                        items.c.paid_item_id,
                        items.c.ordinal,
                        items.c.selection_state,
                        items.c.selection_due_at,
                    )
                    .where(
                        items.c.order_id == order_id,
                        items.c.captured_at.is_not(None),
                    )
                    .order_by(items.c.ordinal)
                    .limit(201)
                )
            )
            .mappings()
            .all()
        )
        if (
            expected_count is None
            or len(positions) > min(expected_count, 200)
            or any(
                not 1 <= row["ordinal"] <= expected_count for row in positions
            )
        ):
            raise ValueError("correction_source_unavailable")
        return [dict(item) for item in positions]

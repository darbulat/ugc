"""Notice amounts come from persisted quote components."""

from uuid import UUID

from sqlalchemy import select

from ugc_bot.domain.financial import utc
from ugc_bot.infrastructure.db.models import OrderItemModel, OrderModel
from ugc_bot.infrastructure.db.repositories.financial_items import _session


class SqlAlchemyOrderNoticeDetailsRepository:
    async def load(self, order_id: UUID, *, session: object) -> dict | None:
        db = _session(session)
        rows = (
            await db.scalars(
                select(OrderItemModel)
                .where(OrderItemModel.order_id == order_id)
                .order_by(OrderItemModel.ordinal)
            )
        ).all()
        if not rows:
            return None
        snapshot = rows[0].quote_payload
        selection_due = utc(rows[0].selection_due_at)
        # Components retain the issued price even when later financial state
        # changes, or a subsequently published policy has a different tariff.
        components = snapshot["components"]
        selection = sum(component[1] for component in components)
        accompaniment = sum(component[2] for component in components)
        count = sum(component[2] > 0 for component in components)
        owner = await db.scalar(
            select(OrderModel.advertiser_id).where(
                OrderModel.order_id == order_id
            )
        )
        return dict(
            user_id=owner,
            contact_reference=snapshot["client_contact_reference"],
            format="with_manager" if count else "self_service",
            accompaniment_count=count,
            position_count=len(components),
            selection_due_at=selection_due.isoformat(),
            selection_due_display=selection_due.strftime(
                "%d.%m.%Y %H:%M:%S UTC"
            ),
            selection_base_minor=selection,
            selection_unit_minor=components[0][1],
            accompaniment_unit_minor=next(
                (part[2] for part in components if part[2]), None
            ),
            accompaniment_minor=accompaniment,
            total_minor=selection + accompaniment,
            currency=snapshot["currency"],
            policy_version=snapshot["policy_version"],
        )

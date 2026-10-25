"""Versioned assignment replacement serialized on the stable item row."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.domain.financial import utc
from ugc_bot.infrastructure.db.models import ItemAssignmentModel, OrderItemModel
from ugc_bot.infrastructure.db.repositories.correction_funding import (
    require_forward_clear,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session


class SqlAlchemyItemAssignmentRepository:
    async def replace(
        self,
        *,
        paid_item_id: UUID,
        expected_version: int,
        creator_id: UUID,
        manager_id: UUID | None,
        actor_id: UUID,
        reason: str,
        at: datetime,
        session: AsyncSession,
    ) -> ItemAssignmentModel:
        db = _session(session)
        at = utc(at)
        item = await db.scalar(
            select(OrderItemModel)
            .where(OrderItemModel.paid_item_id == paid_item_id)
            .with_for_update()
        )
        if item is None:
            raise ValueError("item_not_found")
        version = await db.scalar(
            select(
                func.coalesce(func.max(ItemAssignmentModel.version), 0)
            ).where(ItemAssignmentModel.paid_item_id == paid_item_id)
        )
        if version != expected_version:
            raise ValueError("assignment_version_conflict")
        if item.captured_at is not None:
            await require_forward_clear(paid_item_id, session=db)
        current = await db.scalar(
            select(ItemAssignmentModel)
            .where(
                ItemAssignmentModel.paid_item_id == paid_item_id,
                ItemAssignmentModel.valid_to.is_(None),
            )
            .execution_options(populate_existing=True)
        )
        if current is not None:
            if at < current.valid_from:
                raise ValueError("assignment_time_conflict")
            current.valid_to = at
            await db.flush()
        row = ItemAssignmentModel(
            paid_item_id=paid_item_id,
            version=expected_version + 1,
            creator_id=creator_id,
            manager_id=manager_id,
            actor_id=actor_id,
            reason=reason,
            valid_from=at,
        )
        db.add(row)
        await db.flush()
        return row

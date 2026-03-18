"""SQLAlchemy interaction and offer dispatch repositories."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import String, and_, bindparam, cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ugc_bot.application.ports import (
    InteractionRepository,
    OfferDispatchRepository,
)
from ugc_bot.domain.entities import Interaction, OfferDispatch
from ugc_bot.domain.enums import InteractionStatus, OrderStatus
from ugc_bot.infrastructure.db.models import (
    InteractionModel,
    OfferDispatchModel,
    OrderModel,
)
from ugc_bot.infrastructure.db.repositories._shared import _resolve_session


@dataclass(slots=True)
class SqlAlchemyOfferDispatchRepository(OfferDispatchRepository):
    """SQLAlchemy-backed offer dispatch repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def record_sent(
        self,
        order_id: UUID,
        blogger_id: UUID,
        session: object | None = None,
    ) -> None:
        """Record that an offer was sent to a blogger for an order."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            model = OfferDispatchModel(
                order_id=order_id,
                blogger_id=blogger_id,
                in_offer=False,
            )
            await db_session.merge(model)

    async def record_response(
        self,
        order_id: UUID,
        blogger_id: UUID,
        accepted: bool,
        in_offer: bool,
        session: object | None = None,
        manager_id: UUID | None = None,
    ) -> None:
        """Update dispatch with response (accepted/in_offer) and updated_at."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            now = datetime.now(timezone.utc)
            await db_session.execute(
                update(OfferDispatchModel)
                .where(
                    OfferDispatchModel.order_id == order_id,
                    OfferDispatchModel.blogger_id == blogger_id,
                )
                .values(
                    accepted=accepted,
                    in_offer=in_offer,
                    updated_at=now,
                    manager_id=manager_id,
                )
            )

    async def list_blogger_ids_sent_for_order(
        self, order_id: UUID, session: object | None = None
    ) -> list[UUID]:
        """List blogger ids who already received an offer for this order."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(OfferDispatchModel.blogger_id).where(
                    OfferDispatchModel.order_id == order_id
                )
            )
            return list(exec_result.scalars().all())

    async def list_responses_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> List[OfferDispatch]:
        """List dispatches (with response) by order."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(OfferDispatchModel)
                .where(OfferDispatchModel.order_id == order_id)
                .order_by(
                    OfferDispatchModel.updated_at.asc().nullslast(),
                    OfferDispatchModel.created_at.asc(),
                )
            )
            results = exec_result.scalars().all()
            return [_to_offer_dispatch_entity(m) for m in results]

    async def list_responses_by_blogger(
        self,
        blogger_id: UUID,
        session: object | None = None,
        in_offer_only: bool = False,
    ) -> List[OfferDispatch]:
        """List dispatches where blogger responded (accepted is not null).

        When in_offer_only is True, return only dispatches that ended up in the
        offer (in_offer=true).
        """
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            where = [
                OfferDispatchModel.blogger_id == blogger_id,
                OfferDispatchModel.accepted.isnot(None),
            ]
            if in_offer_only:
                where.append(OfferDispatchModel.in_offer.is_(True))
            exec_result = await db_session.execute(
                select(OfferDispatchModel)
                .where(*where)
                .order_by(
                    OfferDispatchModel.updated_at.desc().nullslast(),
                    OfferDispatchModel.created_at.desc(),
                )
            )
            results = exec_result.scalars().all()
            return [_to_offer_dispatch_entity(m) for m in results]

    async def exists_responded(
        self, order_id: UUID, blogger_id: UUID, session: object | None = None
    ) -> bool:
        """Check if blogger already responded (accepted is not null)."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(func.count())
                .select_from(OfferDispatchModel)
                .where(
                    OfferDispatchModel.order_id == order_id,
                    OfferDispatchModel.blogger_id == blogger_id,
                    OfferDispatchModel.accepted.isnot(None),
                )
            )
            result = exec_result.scalar_one()
            return int(result) > 0

    async def count_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> int:
        """Count dispatches by order (all rows)."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(func.count())
                .select_from(OfferDispatchModel)
                .where(OfferDispatchModel.order_id == order_id)
            )
            result = exec_result.scalar_one()
            return int(result)

    async def count_accepted_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> int:
        """Count in_offer=true by order (accepted within limit)."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(func.count())
                .select_from(OfferDispatchModel)
                .where(
                    OfferDispatchModel.order_id == order_id,
                    OfferDispatchModel.in_offer.is_(True),
                )
            )
            result = exec_result.scalar_one()
            return int(result)

    async def count_completed_orders_by_blogger_ids(
        self,
        blogger_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, int]:
        """Count completed orders (CLOSED, interaction OK) per blogger ID."""
        if not blogger_ids:
            return {}
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            query = (
                select(
                    OfferDispatchModel.blogger_id,
                    func.count().label("cnt"),
                )
                .select_from(OfferDispatchModel)
                .join(
                    OrderModel,
                    and_(
                        OfferDispatchModel.order_id == OrderModel.order_id,
                        OrderModel.status == OrderStatus.CLOSED,
                    ),
                )
                .join(
                    InteractionModel,
                    and_(
                        InteractionModel.order_id
                        == OfferDispatchModel.order_id,
                        InteractionModel.blogger_id
                        == OfferDispatchModel.blogger_id,
                        InteractionModel.advertiser_id
                        == OrderModel.advertiser_id,
                        InteractionModel.status == InteractionStatus.OK,
                    ),
                )
                .where(
                    OfferDispatchModel.blogger_id.in_(blogger_ids),
                    OfferDispatchModel.in_offer.is_(True),
                )
                .group_by(OfferDispatchModel.blogger_id)
            )
            exec_result = await db_session.execute(query)
            rows = exec_result.all()
            result = {uid: 0 for uid in blogger_ids}
            for row in rows:
                result[row.blogger_id] = int(row.cnt)
            return result

    async def list_responses_by_order_and_manager(
        self,
        order_id: UUID,
        manager_id: UUID | None,
        in_offer: bool,
        limit: int = 20,
        offset: int = 0,
        session: object | None = None,
    ) -> list[OfferDispatch]:
        """List dispatches by order and manager with pagination."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            conditions = [
                OfferDispatchModel.order_id == order_id,
                OfferDispatchModel.in_offer == in_offer,
                OfferDispatchModel.accepted.is_(True),
            ]
            if manager_id is not None:
                conditions.append(OfferDispatchModel.manager_id == manager_id)
            exec_result = await db_session.execute(
                select(OfferDispatchModel)
                .where(*conditions)
                .order_by(
                    OfferDispatchModel.updated_at.asc().nullslast(),
                    OfferDispatchModel.created_at.asc(),
                )
                .offset(offset)
                .limit(limit)
            )
            results = exec_result.scalars().all()
            return [_to_offer_dispatch_entity(m) for m in results]

    async def count_responses_by_order_and_manager(
        self,
        order_id: UUID,
        manager_id: UUID | None,
        in_offer: bool,
        session: object | None = None,
    ) -> int:
        """Count dispatches by order and manager."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            conditions = [
                OfferDispatchModel.order_id == order_id,
                OfferDispatchModel.in_offer == in_offer,
                OfferDispatchModel.accepted.is_(True),
            ]
            if manager_id is not None:
                conditions.append(OfferDispatchModel.manager_id == manager_id)
            exec_result = await db_session.execute(
                select(func.count())
                .select_from(OfferDispatchModel)
                .where(*conditions)
            )
            result = exec_result.scalar_one()
            return int(result)

    async def get_by_order_and_blogger(
        self,
        order_id: UUID,
        blogger_id: UUID,
        session: object | None = None,
    ) -> OfferDispatch | None:
        """Fetch a single dispatch by order and blogger."""
        async with _resolve_session(self.session_factory, session) as s:
            result = await s.execute(
                select(OfferDispatchModel).where(
                    OfferDispatchModel.order_id == order_id,
                    OfferDispatchModel.blogger_id == blogger_id,
                )
            )
            row = result.scalar_one_or_none()
            return _to_offer_dispatch_entity(row) if row else None

    async def set_ugc_video_url(
        self,
        order_id: UUID,
        blogger_id: UUID,
        url: str | None,
        session: object | None = None,
    ) -> None:
        """Set ugc_video_url for a dispatch."""
        async with _resolve_session(self.session_factory, session) as s:
            await s.execute(
                update(OfferDispatchModel)
                .where(
                    OfferDispatchModel.order_id == order_id,
                    OfferDispatchModel.blogger_id == blogger_id,
                )
                .values(
                    ugc_video_url=url,
                    updated_at=datetime.now(timezone.utc),
                )
            )

    async def set_in_offer(
        self,
        order_id: UUID,
        blogger_id: UUID,
        in_offer: bool,
        session: object | None = None,
    ) -> None:
        """Set in_offer flag for a dispatch."""
        async with _resolve_session(self.session_factory, session) as s:
            await s.execute(
                update(OfferDispatchModel)
                .where(
                    OfferDispatchModel.order_id == order_id,
                    OfferDispatchModel.blogger_id == blogger_id,
                )
                .values(
                    in_offer=in_offer,
                    updated_at=datetime.now(timezone.utc),
                )
            )


@dataclass(slots=True)
class SqlAlchemyInteractionRepository(InteractionRepository):
    """SQLAlchemy-backed interaction repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get_by_id(
        self, interaction_id: UUID, session: object | None = None
    ) -> Optional[Interaction]:
        """Fetch interaction by id."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(InteractionModel).where(
                    InteractionModel.interaction_id == interaction_id
                )
            )
            result = exec_result.scalar_one_or_none()
            return _to_interaction_entity(result) if result else None

    async def get_by_participants(
        self,
        order_id: UUID,
        blogger_id: UUID,
        advertiser_id: UUID,
        session: object | None = None,
    ) -> Optional[Interaction]:
        """Fetch interaction by order/blogger/advertiser."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(InteractionModel).where(
                    InteractionModel.order_id == order_id,
                    InteractionModel.blogger_id == blogger_id,
                    InteractionModel.advertiser_id == advertiser_id,
                )
            )
            result = exec_result.scalar_one_or_none()
            return _to_interaction_entity(result) if result else None

    async def list_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> Iterable[Interaction]:
        """List interactions for order."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(InteractionModel).where(
                    InteractionModel.order_id == order_id
                )
            )
            results = exec_result.scalars()
            return [_to_interaction_entity(item) for item in results]

    async def list_due_for_feedback(
        self, cutoff: datetime, session: object | None = None
    ) -> Iterable[Interaction]:
        """List interactions due for feedback."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            status_param = cast(
                bindparam(
                    "status_1",
                    value=InteractionStatus.PENDING.value,
                    type_=String(),
                ),
                InteractionModel.status.type,
            )
            exec_result = await db_session.execute(
                select(InteractionModel).where(
                    InteractionModel.next_check_at <= cutoff,
                    InteractionModel.status == status_param,
                )
            )
            results = exec_result.scalars()
            return [_to_interaction_entity(item) for item in results]

    async def list_by_status(
        self, status: InteractionStatus, session: object | None = None
    ) -> Iterable[Interaction]:
        """List interactions by status."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            status_param = cast(
                bindparam(
                    "status_1",
                    value=status.value,
                    type_=String(),
                ),
                InteractionModel.status.type,
            )
            exec_result = await db_session.execute(
                select(InteractionModel).where(
                    InteractionModel.status == status_param
                )
            )
            results = exec_result.scalars()
            return [_to_interaction_entity(item) for item in results]

    async def save(
        self, interaction: Interaction, session: object | None = None
    ) -> None:
        """Persist interaction."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            model = _to_interaction_model(interaction)
            await db_session.merge(model)

    async def update_next_check_at(
        self,
        interaction_id: UUID,
        next_check_at: datetime,
        session: object | None = None,
    ) -> None:
        """Update next_check_at for an interaction."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            await db_session.execute(
                update(InteractionModel)
                .where(InteractionModel.interaction_id == interaction_id)
                .values(next_check_at=next_check_at)
            )

    async def list_blogger_ids_with_unfulfilled_interaction(
        self, session: object | None = None
    ) -> list[UUID]:
        """Blogger ids with at least one interaction PENDING or ISSUE."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(InteractionModel.blogger_id)
                .where(
                    InteractionModel.status.in_(
                        [InteractionStatus.PENDING, InteractionStatus.ISSUE]
                    )
                )
                .distinct()
            )
            return list(exec_result.scalars().all())


def _to_offer_dispatch_entity(model: OfferDispatchModel) -> OfferDispatch:
    """Map offer dispatch ORM model to domain entity."""
    return OfferDispatch(
        order_id=model.order_id,
        blogger_id=model.blogger_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        accepted=model.accepted,
        in_offer=model.in_offer,
        manager_id=model.manager_id,
        ugc_video_url=model.ugc_video_url,
    )


def _to_interaction_entity(model: InteractionModel) -> Interaction:
    """Map interaction ORM model to domain entity."""
    return Interaction(
        interaction_id=model.interaction_id,
        order_id=model.order_id,
        blogger_id=model.blogger_id,
        advertiser_id=model.advertiser_id,
        status=model.status,
        from_advertiser=model.from_advertiser,
        from_blogger=model.from_blogger,
        postpone_count=model.postpone_count,
        next_check_at=model.next_check_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _to_interaction_model(interaction: Interaction) -> InteractionModel:
    """Map domain interaction to ORM model."""
    return InteractionModel(
        interaction_id=interaction.interaction_id,
        order_id=interaction.order_id,
        blogger_id=interaction.blogger_id,
        advertiser_id=interaction.advertiser_id,
        status=interaction.status,
        from_advertiser=interaction.from_advertiser,
        from_blogger=interaction.from_blogger,
        postpone_count=interaction.postpone_count,
        next_check_at=interaction.next_check_at,
        created_at=interaction.created_at,
        updated_at=interaction.updated_at,
    )

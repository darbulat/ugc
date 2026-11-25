"""SQLAlchemy interaction and offer dispatch repositories."""

import hashlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import String, and_, bindparam, cast, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ugc_bot.application.ports import (
    InteractionRepository,
    OfferDispatchRepository,
)
from ugc_bot.domain.entities import Interaction, OfferDispatch
from ugc_bot.domain.enums import (
    InteractionStatus,
    MessengerType,
    OrderStatus,
    RejectionReason,
)
from ugc_bot.infrastructure.db.messenger_attribution import (
    OFFER_CARD_ACTION_EVENTS,
    OFFER_CHANNELS,
    remember_offer_response,
)
from ugc_bot.infrastructure.db.models import (
    InteractionModel,
    OfferDispatchModel,
    OrderModel,
)
from ugc_bot.infrastructure.db.repositories._shared import _resolve_session
from ugc_bot.infrastructure.db.repositories.legacy_financial_guards import (
    SqlAlchemyLegacyFinancialGuardRepository,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SqlAlchemyOfferDispatchRepository(OfferDispatchRepository):
    """SQLAlchemy-backed offer dispatch repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def record_sent(
        self,
        order_id: UUID,
        blogger_id: UUID,
        session: object | None = None,
        *,
        channel: MessengerType | None = None,
        message_id: str | None = None,
    ) -> None:
        """Save the first successful send on this channel for the offer."""
        async with _resolve_session(self.session_factory, session) as db:
            if message_id is not None:
                # Serialize provider acknowledgements with callback recovery.
                await db.scalar(
                    select(OrderModel.order_id)
                    .where(OrderModel.order_id == order_id)
                    .with_for_update()
                )
            if channel is None:
                await db.merge(
                    OfferDispatchModel(
                        order_id=order_id, blogger_id=blogger_id, in_offer=False
                    )
                )
                return
            insert = (
                sqlite_insert
                if db.get_bind().dialect.name == "sqlite"
                else pg_insert
            )
            dispatch = OfferDispatchModel.__table__
            await db.execute(
                insert(OfferDispatchModel)
                .values(
                    order_id=order_id, blogger_id=blogger_id, in_offer=False
                )
                .on_conflict_do_nothing(
                    index_elements=(dispatch.c.order_id, dispatch.c.blogger_id)
                )
            )
            column = OFFER_CHANNELS.c[f"{channel.value}_sent_at"]
            sent_at = datetime.now(timezone.utc)
            values: dict[str, datetime | str] = {column.key: sent_at}
            if message_id is not None:
                values["creator_card_message_id"] = message_id
            await db.execute(
                insert(OFFER_CHANNELS)
                .values(
                    order_id=order_id,
                    blogger_id=blogger_id,
                    **values,
                )
                .on_conflict_do_update(
                    index_elements=(
                        OFFER_CHANNELS.c.order_id,
                        OFFER_CHANNELS.c.blogger_id,
                    ),
                    set_=values,
                    where=column.is_(None),
                )
            )

    async def creator_card_matches(
        self,
        order_id: UUID,
        blogger_id: UUID,
        channel: MessengerType,
        message_id: str,
    ) -> bool:
        async with _resolve_session(self.session_factory, None) as db:
            sent = OFFER_CHANNELS.c[f"{channel.value}_sent_at"]
            return bool(
                await db.scalar(
                    select(OFFER_CHANNELS.c.order_id).where(
                        OFFER_CHANNELS.c.order_id == order_id,
                        OFFER_CHANNELS.c.blogger_id == blogger_id,
                        OFFER_CHANNELS.c.creator_card_message_id == message_id,
                        sent.is_not(None),
                    )
                )
            )

    async def mark_creator_card_updated(
        self, order_id: UUID, blogger_id: UUID, message_id: str
    ) -> None:
        async with _resolve_session(self.session_factory, None) as db:
            await db.execute(
                update(OFFER_CHANNELS)
                .where(
                    OFFER_CHANNELS.c.order_id == order_id,
                    OFFER_CHANNELS.c.blogger_id == blogger_id,
                    OFFER_CHANNELS.c.creator_card_message_id == message_id,
                    OFFER_CHANNELS.c.creator_card_updated_at.is_(None),
                )
                .values(creator_card_updated_at=datetime.now(timezone.utc))
            )

    async def recover_creator_card_receipt(
        self,
        order_id: UUID,
        blogger_id: UUID,
        channel: MessengerType,
        message_id: str,
    ) -> bool:
        """A provider callback proves delivery after a lost send response."""
        from ugc_bot.infrastructure.db.dispatch_control import CLAIMS, CONTROLS

        async with _resolve_session(self.session_factory, None) as db:
            order = await db.get(OrderModel, order_id, with_for_update=True)
            if order is None or not order.creator_offer_card:
                return False
            key = (
                OFFER_CHANNELS.c.order_id == order_id,
                OFFER_CHANNELS.c.blogger_id == blogger_id,
            )
            receipt = (
                (await db.execute(select(OFFER_CHANNELS).where(*key)))
                .mappings()
                .one_or_none()
            )
            if receipt and receipt["creator_card_message_id"] is not None:
                return (
                    receipt["creator_card_message_id"] == message_id
                    and receipt[f"{channel.value}_sent_at"] is not None
                )
            claimed = await db.scalar(
                select(CLAIMS.c.blogger_id)
                .join(CONTROLS, CLAIMS.c.order_id == CONTROLS.c.order_id)
                .where(
                    CLAIMS.c.order_id == order_id,
                    CLAIMS.c.blogger_id == blogger_id,
                    CLAIMS.c.run > 0,
                    CLAIMS.c.run <= CONTROLS.c.run,
                    CLAIMS.c.rejected.is_(False),
                )
            )
            if claimed is None:
                return False
            await self.record_sent(
                order_id,
                blogger_id,
                session=db,
                channel=channel,
                message_id=message_id,
            )
            await db.execute(
                update(OFFER_CHANNELS)
                .where(*key, OFFER_CHANNELS.c.creator_card_message_id.is_(None))
                .values(creator_card_message_id=message_id)
            )
            return True

    async def record_card_action(
        self,
        order_id: UUID,
        blogger_id: UUID,
        channel: MessengerType,
        callback_id: str,
        action: str,
    ) -> None:
        if not callback_id:
            return
        async with _resolve_session(self.session_factory, None) as db:
            insert = (
                sqlite_insert
                if db.get_bind().dialect.name == "sqlite"
                else pg_insert
            )
            events = OFFER_CARD_ACTION_EVENTS
            await db.execute(
                insert(events)
                .values(
                    channel=channel.value,
                    callback_digest=hashlib.sha256(
                        callback_id.encode()
                    ).hexdigest(),
                    order_id=order_id,
                    blogger_id=blogger_id,
                    action=action,
                    occurred_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_nothing(
                    index_elements=(events.c.channel, events.c.callback_digest)
                )
            )

    async def record_response_started(
        self, order_id: UUID, blogger_id: UUID
    ) -> None:
        async with _resolve_session(self.session_factory, None) as db:
            insert = (
                sqlite_insert
                if db.get_bind().dialect.name == "sqlite"
                else pg_insert
            )
            started = insert(OFFER_CHANNELS).from_select(
                ("order_id", "blogger_id", "response_started_at"),
                select(
                    OfferDispatchModel.order_id,
                    OfferDispatchModel.blogger_id,
                    func.now(),
                ).where(
                    OfferDispatchModel.order_id == order_id,
                    OfferDispatchModel.blogger_id == blogger_id,
                    OfferDispatchModel.accepted.is_(None),
                ),
            )
            start_column = OFFER_CHANNELS.c.response_started_at
            await db.execute(
                started.on_conflict_do_update(
                    index_elements=(
                        OFFER_CHANNELS.c.order_id,
                        OFFER_CHANNELS.c.blogger_id,
                    ),
                    set_={start_column.key: started.excluded[start_column.key]},
                    where=start_column.is_(None),
                )
            )

    async def record_response(
        self,
        order_id: UUID,
        blogger_id: UUID,
        accepted: bool,
        in_offer: bool,
        session: object | None = None,
        manager_id: UUID | None = None,
        rejection_reason: str | None = None,
        desired_price: Decimal | None = None,
        *,
        channel: MessengerType | None = None,
    ) -> None:
        """Update dispatch with response (accepted/in_offer) and updated_at."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            now = datetime.now(timezone.utc)
            key = (
                OfferDispatchModel.order_id == order_id,
                OfferDispatchModel.blogger_id == blogger_id,
            )
            if channel is not None:
                previous = (
                    await db_session.execute(
                        select(OfferDispatchModel.accepted)
                        .where(*key)
                        .with_for_update()
                    )
                ).one_or_none()
                if previous is not None and previous[0] is None:
                    await db_session.execute(
                        remember_offer_response(
                            order_id, blogger_id, channel, now
                        )
                    )
            await db_session.execute(
                update(OfferDispatchModel)
                .where(*key)
                .values(
                    accepted=accepted,
                    in_offer=in_offer,
                    updated_at=now,
                    manager_id=manager_id,
                    rejection_reason=rejection_reason,
                    desired_price=desired_price,
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

    async def list_by_order_and_rejection_reason(
        self,
        order_id: UUID,
        rejection_reason: str,
        limit: int = 20,
        offset: int = 0,
        session: object | None = None,
    ) -> list[OfferDispatch]:
        """List dispatches rejected with a specific reason."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(OfferDispatchModel)
                .where(
                    OfferDispatchModel.order_id == order_id,
                    OfferDispatchModel.rejection_reason == rejection_reason,
                )
                .order_by(
                    OfferDispatchModel.updated_at.asc().nullslast(),
                    OfferDispatchModel.created_at.asc(),
                )
                .offset(offset)
                .limit(limit)
            )
            results = exec_result.scalars().all()
            return [_to_offer_dispatch_entity(m) for m in results]

    async def count_by_order_and_rejection_reason(
        self,
        order_id: UUID,
        rejection_reason: str,
        session: object | None = None,
    ) -> int:
        """Count dispatches rejected with a specific reason."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(func.count())
                .select_from(OfferDispatchModel)
                .where(
                    OfferDispatchModel.order_id == order_id,
                    OfferDispatchModel.rejection_reason == rejection_reason,
                )
            )
            result = exec_result.scalar_one()
            return int(result)

    async def get_by_order_and_blogger(
        self,
        order_id: UUID,
        blogger_id: UUID,
        session: object | None = None,
        *,
        for_update: bool = False,
    ) -> OfferDispatch | None:
        """Fetch a dispatch, optionally locking it until caller commit."""
        if for_update and not isinstance(session, AsyncSession):
            raise ValueError("A row lock requires an explicit transaction")
        stmt = (
            select(OfferDispatchModel)
            .where(
                OfferDispatchModel.order_id == order_id,
                OfferDispatchModel.blogger_id == blogger_id,
            )
            .execution_options(populate_existing=True)
        )
        if for_update:
            stmt = stmt.with_for_update()
        async with _resolve_session(self.session_factory, session) as s:
            result = await s.execute(stmt)
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

    async def set_manager(
        self,
        order_id: UUID,
        blogger_id: UUID,
        manager_id: UUID,
        session: object | None = None,
    ) -> None:
        """Set manager_id for a dispatch."""
        async with _resolve_session(self.session_factory, session) as s:
            await s.execute(
                update(OfferDispatchModel)
                .where(
                    OfferDispatchModel.order_id == order_id,
                    OfferDispatchModel.blogger_id == blogger_id,
                )
                .values(
                    manager_id=manager_id,
                    updated_at=datetime.now(timezone.utc),
                )
            )


@dataclass(slots=True)
class SqlAlchemyInteractionRepository(InteractionRepository):
    """SQLAlchemy-backed interaction repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get_by_id_for_update(
        self, interaction_id: UUID, session: object | None = None
    ) -> Interaction | None:
        if not isinstance(session, AsyncSession):
            raise ValueError(
                "Persisted feedback requires an explicit transaction"
            )
        model = await session.scalar(
            select(InteractionModel)
            .where(InteractionModel.interaction_id == interaction_id)
            .with_for_update()
        )
        return _to_interaction_entity(model) if model is not None else None

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
            previous = await db_session.scalar(
                select(InteractionModel)
                .where(
                    InteractionModel.interaction_id
                    == interaction.interaction_id
                )
                .with_for_update()
            )
            guards = SqlAlchemyLegacyFinancialGuardRepository(
                self.session_factory
            )
            # Capture pre-migration ISSUE before an ordinary edit can erase it.
            reopen = previous is not None and (
                previous.status != InteractionStatus.ISSUE
                or previous.from_blogger != interaction.from_blogger
                or previous.from_advertiser != interaction.from_advertiser
            )
            if (
                previous is not None
                and previous.status == InteractionStatus.ISSUE
            ):
                await guards.block_for_interaction(
                    _to_interaction_entity(previous), session=db_session
                )
            model = _to_interaction_model(interaction)
            await db_session.merge(model)
            if interaction.status == InteractionStatus.ISSUE:
                await db_session.flush()
                await guards.block_for_interaction(
                    interaction, session=db_session, reopen=reopen
                )

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
            result = list(exec_result.scalars().all())
            if len(result) > 5000:
                logger.warning(
                    "Large unfulfilled interaction set: %d blogger IDs",
                    len(result),
                )
            return result


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
        rejection_reason=RejectionReason(model.rejection_reason)
        if model.rejection_reason
        else None,
        desired_price=model.desired_price,
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

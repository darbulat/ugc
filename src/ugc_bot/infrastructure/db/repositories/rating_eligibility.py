"""Rating authorization reads share the rating write's locked transaction."""

from uuid import UUID

from sqlalchemy import select

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
    require_current_principal,
)
from ugc_bot.application.rating_eligibility_ports import (
    RatingEligibility,
    RatingParticipant,
)
from ugc_bot.domain.enums import InteractionStatus, RaterRole, UserStatus
from ugc_bot.infrastructure.db.collaboration_models import CollaborationModel
from ugc_bot.infrastructure.db.models import (
    InteractionModel,
    ManagerOrderModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session


class SqlAlchemyRatingEligibilityRepository:
    async def load(
        self,
        actor_id: UUID,
        order_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal | None,
        owner_only: bool,
        session: object | None,
    ) -> RatingEligibility:
        db = _session(session)
        actor = await db.scalar(
            select(UserModel)
            .where(UserModel.user_id == actor_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if actor is None or actor.status != UserStatus.ACTIVE:
            raise ValueError("rating_access_denied")
        require_current_principal(
            principal, actor_id, actor.user_id, actor.telegram_id, actor.max_id
        )
        order = await db.scalar(
            select(OrderModel)
            .where(OrderModel.order_id == order_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if order is None:
            raise ValueError("rating_access_denied")
        if order.advertiser_id == actor_id:
            role = RaterRole.ADVERTISER
        elif owner_only:
            raise ValueError("rating_access_denied")
        elif actor.admin:
            role = RaterRole.ADMIN
        elif (
            await db.scalar(
                select(ManagerOrderModel.user_id).where(
                    ManagerOrderModel.user_id == actor_id,
                    ManagerOrderModel.order_id == order_id,
                )
            )
            is not None
        ):
            role = RaterRole.MANAGER
        else:
            raise ValueError("rating_access_denied")

        # Completion belongs to the concrete creator/order pair. Order status,
        # delivery of contacts and a success claim are insufficient evidence.
        participants: dict[UUID, RatingParticipant] = {}
        legacy = (
            await db.execute(
                select(
                    InteractionModel.blogger_id,
                    UserModel.username,
                    InteractionModel.status,
                )
                .join(
                    UserModel, UserModel.user_id == InteractionModel.blogger_id
                )
                .where(
                    InteractionModel.order_id == order_id,
                    InteractionModel.advertiser_id == order.advertiser_id,
                )
            )
        ).all()
        for blogger_id, name, status in legacy:
            previous = participants.get(blogger_id)
            participants[blogger_id] = RatingParticipant(
                blogger_id,
                name,
                status == InteractionStatus.OK
                or bool(previous and previous.completed),
            )
        financial = (
            await db.execute(
                select(
                    CollaborationModel.creator_id,
                    UserModel.username,
                    CollaborationModel.state,
                )
                .join(
                    UserModel,
                    UserModel.user_id == CollaborationModel.creator_id,
                )
                .where(
                    CollaborationModel.order_id == order_id,
                    CollaborationModel.client_id == order.advertiser_id,
                )
            )
        ).all()
        for blogger_id, name, state in financial:
            previous = participants.get(blogger_id)
            participants[blogger_id] = RatingParticipant(
                blogger_id,
                name,
                state in ("success_final", "available")
                or bool(previous and previous.completed),
            )
        return RatingEligibility(
            role,
            tuple(
                sorted(participants.values(), key=lambda p: str(p.blogger_id))
            ),
        )

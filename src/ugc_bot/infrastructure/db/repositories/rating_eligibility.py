"""Rating authorization reads share the rating write's locked transaction."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update

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
from ugc_bot.infrastructure.db.creator_transfer_models import TRANSFERS
from ugc_bot.infrastructure.db.models import (
    InteractionModel,
    ManagerOrderModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.creator_transfers import (
    delivery_history,
    transfers_installed,
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
        await self._supplemental(db, order, participants)
        return RatingEligibility(
            role,
            tuple(
                sorted(participants.values(), key=lambda p: str(p.blogger_id))
            ),
        )

    @staticmethod
    async def _supplemental(db, order, participants):
        if not order.financial_version or order.complimentary:
            return
        order_id, client_id = order.order_id, order.advertiser_id
        # Historical paid contacts remain participants after reassignment.
        for row in await delivery_history(db, order_id):
            creator_id = row["creator_id"]
            contact = row["contact"]
            participants.setdefault(
                creator_id,
                RatingParticipant(
                    creator_id,
                    contact.get("name") or contact.get("username") or "Креатор",
                    False,
                ),
            )
        extras = []
        if await transfers_installed(db):
            extras = (
                await db.execute(
                    select(
                        TRANSFERS.c.creator_id,
                        TRANSFERS.c.feedback,
                        UserModel.username,
                    )
                    .join(
                        UserModel, UserModel.user_id == TRANSFERS.c.creator_id
                    )
                    .where(
                        TRANSFERS.c.order_id == order_id,
                        TRANSFERS.c.client_id == client_id,
                        TRANSFERS.c.state == "sent",
                    )
                )
            ).all()
        for creator_id, feedback, name in extras:
            previous = participants.get(creator_id)
            participants[creator_id] = RatingParticipant(
                creator_id,
                name,
                bool(previous and previous.completed) or feedback == "worked",
                True,
                feedback,
            )

    async def feedback(self, actor_id, order_id, creator_id, value, *, session):
        # Only the order owner's non-billable, successfully delivered handoff.
        await _session(session).execute(
            update(TRANSFERS)
            .where(
                TRANSFERS.c.order_id == order_id,
                TRANSFERS.c.creator_id == creator_id,
                TRANSFERS.c.client_id == actor_id,
                TRANSFERS.c.state == "sent",
            )
            .values(feedback=value, feedback_at=datetime.now(timezone.utc))
        )

"""In-memory counterpart of server-loaded rating eligibility."""

from dataclasses import dataclass, field
from uuid import UUID

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
    require_current_principal,
)
from ugc_bot.application.rating_eligibility_ports import (
    RatingEligibility,
    RatingParticipant,
)
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import RaterRole, UserStatus


@dataclass
class InMemoryRatingEligibilityRepository:
    users: dict[UUID, User] = field(default_factory=dict)
    owners: dict[UUID, UUID] = field(default_factory=dict)
    managers: set[tuple[UUID, UUID]] = field(default_factory=set)
    participants: dict[UUID, tuple[RatingParticipant, ...]] = field(
        default_factory=dict
    )

    async def load(
        self,
        actor_id: UUID,
        order_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal | None,
        owner_only: bool,
        session: object | None,
    ) -> RatingEligibility:
        actor = self.users.get(actor_id)
        if (
            actor is None
            or actor.status != UserStatus.ACTIVE
            or order_id not in self.owners
        ):
            raise ValueError("rating_access_denied")
        require_current_principal(
            principal, actor_id, actor.user_id, actor.telegram_id, actor.max_id
        )
        if self.owners[order_id] == actor_id:
            role = RaterRole.ADVERTISER
        elif owner_only:
            raise ValueError("rating_access_denied")
        elif actor.admin:
            role = RaterRole.ADMIN
        elif (actor_id, order_id) in self.managers:
            role = RaterRole.MANAGER
        else:
            raise ValueError("rating_access_denied")
        return RatingEligibility(role, self.participants.get(order_id, ()))

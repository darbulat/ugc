"""Server-loaded rating authorization and actual creator-work completion."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.domain.enums import RaterRole


@dataclass(frozen=True, slots=True)
class RatingParticipant:
    blogger_id: UUID
    display_name: str
    completed: bool
    supplemental: bool = False
    feedback: str | None = None


@dataclass(frozen=True, slots=True)
class RatingEligibility:
    """Current actor capability plus the order's actual participants."""

    role: RaterRole
    participants: tuple[RatingParticipant, ...]


class RatingEligibilityRepository(Protocol):
    async def feedback(
        self,
        actor_id: UUID,
        order_id: UUID,
        creator_id: UUID,
        value: str,
        *,
        session: object | None,
    ) -> None: ...

    async def load(
        self,
        actor_id: UUID,
        order_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal | None,
        owner_only: bool,
        session: object | None,
    ) -> RatingEligibility:
        """Authorize current actor while holding its user and order locks."""
        ...

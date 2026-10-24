"""One configured physical namespace and immutable trusted proof ownership.

Caller bank labels never construct these identities. A configured source/account
resolver must recognize them first; absence stays an unapplied exception.
Historical immutable P01 outcomes and new claims use the exact same key/mutex.
"""

import json
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from ugc_bot.domain.corrections import require_text, require_uuid


@dataclass(frozen=True, slots=True, kw_only=True)
class PhysicalProofIdentity:
    source: str
    account: str
    direction: Literal["incoming", "outgoing"]
    reference: str

    def __post_init__(self) -> None:
        for value in (self.source, self.account):
            require_text(value, 256)
        require_text(self.reference, 4000)
        if self.direction not in ("incoming", "outgoing"):
            raise ValueError("physical_proof_direction_invalid")

    @property
    def key(self) -> str:
        """JSON component encoding cannot collide at delimiter boundaries."""
        return json.dumps(
            (self.source, self.account, self.direction, self.reference),
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PhysicalProofOwner:
    producer: Literal["payout", "refund", "repayment"]
    intent_id: UUID
    observation_id: UUID
    command_id: UUID

    def __post_init__(self) -> None:
        if self.producer not in ("payout", "refund", "repayment"):
            raise ValueError("physical_proof_producer_invalid")
        for value in (self.intent_id, self.observation_id, self.command_id):
            require_uuid(value)


class PhysicalProofUnavailable(ValueError):
    """Recognition/provenance is unavailable; never interpret it as unused."""

    def __init__(self) -> None:
        super().__init__("physical_proof_unavailable")


class PhysicalProofConflict(ValueError):
    """A distinct economic owner prevents reuse; original ownership remains."""

    def __init__(self) -> None:
        super().__init__("physical_proof_owner_conflict")


class PhysicalProofAuthority(Protocol):
    async def lock(
        self, identity: PhysicalProofIdentity, *, session: object
    ) -> None: ...

    async def owners(
        self, identity: PhysicalProofIdentity, *, session: object
    ) -> tuple[PhysicalProofOwner, ...]:
        """Retain historical owners including unapplied P01.

        Unrecognized identity or missing/ambiguous provenance raises
        PhysicalProofUnavailable; an empty tuple means recognized unused only.
        """
        ...

    async def claim(
        self,
        identity: PhysicalProofIdentity,
        owner: PhysicalProofOwner,
        *,
        session: object,
    ) -> PhysicalProofOwner:
        """Same producer/intent returns its original owner; never reassign.

        Raises PhysicalProofConflict for any distinct historical owner and
        PhysicalProofUnavailable for unrecognized identity or provenance.
        Both bounded failures preserve the caller's outer transaction.
        """
        ...

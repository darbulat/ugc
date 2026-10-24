"""Server-only proof context and the historical direct-network read port."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ugc_bot.domain.identity_history import (
    HistoricalBindingInputs,
    IdentityCountInputs,
    aware_utc,
)


@dataclass(frozen=True, slots=True)
class IdentityEvidence:
    source: str
    business_key: str
    fact_at: datetime

    def __post_init__(self) -> None:
        if self.source not in {"instagram_webhook", "manual_code"}:
            raise ValueError("trusted_identity_source_required")
        if not self.business_key.strip() or len(self.business_key) > 256:
            raise ValueError("identity_proof_key_required")
        object.__setattr__(self, "fact_at", aware_utc(self.fact_at))


_EVIDENCE: ContextVar[IdentityEvidence | None] = ContextVar(
    "trusted_creator_identity_evidence",
    default=None,
)


def current_identity_evidence() -> IdentityEvidence | None:
    return _EVIDENCE.get()


@contextmanager
def identity_evidence(evidence: IdentityEvidence) -> Iterator[None]:
    """Enter only after server proof validation; this is not an API DTO."""
    token = _EVIDENCE.set(evidence)
    try:
        yield
    finally:
        _EVIDENCE.reset(token)


class CreatorIdentityHistoryRepository(Protocol):
    async def acquire_snapshot_barrier(
        self, *, session: object | None
    ) -> None: ...

    async def read_direct_binding(
        self,
        referred_user_id: UUID,
        as_of: datetime,
        *,
        session: object | None = None,
    ) -> HistoricalBindingInputs: ...

    async def read_network(
        self,
        partner_user_id: UUID,
        as_of: datetime,
        *,
        session: object | None = None,
    ) -> IdentityCountInputs: ...

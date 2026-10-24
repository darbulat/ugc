"""Allocate a captured position once, before any contact send."""

from dataclasses import dataclass
from uuid import UUID

from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.paid_selection_ports import (
    PaidSelectionRepository,
    SelectionInterest,
)
from ugc_bot.application.ports import TransactionManager


@dataclass
class PaidSelectionInterestService:
    repository: PaidSelectionRepository
    transactions: TransactionManager
    clock: Clock
    enabled: bool = False

    async def respond(
        self, order_id: UUID, creator_id: UUID
    ) -> SelectionInterest | None:
        # Route legacy orders before attempting any new financial writes.
        attempt = 0
        while True:
            try:
                async with self.transactions.transaction() as session:
                    users = await self.repository.discover(
                        order_id, session=session
                    )
                    if users is None:
                        return None
                    if not self.enabled:
                        raise ValueError("financial_core_disabled")
                    locked = tuple(sorted(set(users) | {creator_id}, key=str))
                    await self.repository.lock_users(locked, session=session)
                    return await self.repository.confirm(
                        order_id,
                        creator_id,
                        locked,
                        self.clock.now,
                        session=session,
                    )
            except ValueError as exc:
                if (
                    str(exc) != "selection_scope_changed_retry_required"
                    or attempt == 2
                ):
                    raise
                attempt += 1

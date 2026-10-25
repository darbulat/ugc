"""Bounded, keyset-paged progression of original captured selection orders."""

import logging
from dataclasses import dataclass, field
from uuid import UUID

from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.services.selection_maturity_service import (
    SelectionMaturityService,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SelectionMaturitySweepResult:
    attempted: int
    closed: int
    deferred: int


@dataclass(slots=True)
class SelectionMaturitySweepService:
    maturity: SelectionMaturityService
    transactions: TransactionManager
    _cursor: UUID | None = field(default=None, init=False)

    async def run_once(
        self, *, limit: int = 100
    ) -> SelectionMaturitySweepResult:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("selection_sweep_limit_invalid")
        async with self.transactions.transaction() as session:
            orders = await self.maturity.repository.list_orders(
                after=self._cursor, limit=limit, session=session
            )
        closed, deferred = 0, 0
        for order_id in orders:
            try:
                async with self.transactions.transaction() as session:
                    result = await self.maturity.refresh(
                        order_id, session=session
                    )
                closed += result["state"] == "closed"
            except ValueError as exc:
                deferred += 1
                logger.warning(
                    "Selection maturity deferred",
                    extra={"order_id": str(order_id), "reason": str(exc)},
                )
        self._cursor = orders[-1] if len(orders) == limit else None
        return SelectionMaturitySweepResult(len(orders), closed, deferred)

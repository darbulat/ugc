"""Read live unresolved disputes before any v1 financial state mutation."""

from uuid import UUID

from ugc_bot.application.work_entitlement_ports import (
    WorkDisputeCase,
    WorkEntitlementRepository,
)


class WorkFinancialGuard:
    def __init__(self, repository: WorkEntitlementRepository):
        self.repository = repository

    async def case_for_item(
        self, paid_item_id: UUID, *, session: object
    ) -> WorkDisputeCase | None:
        """Caller already holds the item barrier; this never adds User locks."""
        return await self.repository.get_dispute_case(
            paid_item_id, session=session
        )

    async def require_clear(
        self, paid_item_id: UUID, *, session: object
    ) -> None:
        if await self.case_for_item(paid_item_id, session=session) is not None:
            raise ValueError("work_disputed")

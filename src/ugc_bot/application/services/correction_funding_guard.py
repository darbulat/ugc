"""Live correction permission after the caller's gross/source barriers.

This reader does not acquire locks or write facts. Captured gross validation
and complete prospective User/wallet discovery belong to the caller. There
is no ordinary forward bypass for the separate delayed-assessment path.
"""

from uuid import UUID

from ugc_bot.application.correction_ports import CorrectionRepository
from ugc_bot.domain.corrections import ComponentFunding, require_uuid


class LiveCorrectionFundingGuard:
    def __init__(self, repository: CorrectionRepository) -> None:
        self.repository = repository

    async def load_item(
        self, paid_item_id: UUID, *, session: object
    ) -> tuple[ComponentFunding, ...]:
        require_uuid(paid_item_id)
        funding = await self.repository.live_funding(
            paid_item_id, session=session
        )
        if (
            type(funding) is not tuple
            or not funding
            or any(
                not isinstance(line, ComponentFunding)
                or line.paid_item_id != paid_item_id
                or line.component not in ("selection", "accompaniment")
                or line.gross_minor <= 0
                for line in funding
            )
        ):
            raise ValueError("correction_funding_unavailable")
        components = {line.component for line in funding}
        if (
            "selection" not in components
            or len(components) != len(funding)
            or len({line.allocation_key for line in funding}) != len(funding)
            or len({line.payment_id for line in funding}) != 1
        ):
            raise ValueError("correction_funding_unavailable")
        return funding

    async def require_forward_clear(
        self, paid_item_id: UUID, *, session: object
    ) -> None:
        funding = await self.load_item(paid_item_id, session=session)
        if not all(line.state_consistent for line in funding):
            raise ValueError("correction_funding_unavailable")
        if any(
            line.unresolved_case_ids or line.unresolved_observation_ids
            for line in funding
        ):
            raise ValueError("correction_unresolved")
        if any(line.cumulative_refund_minor for line in funding):
            raise ValueError("correction_component_refunded")

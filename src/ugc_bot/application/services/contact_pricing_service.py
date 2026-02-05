"""Service for contact pricing."""

from dataclasses import dataclass

from ugc_bot.application.ports import (
    ContactPricingRepository,
    TransactionManager,
)
from ugc_bot.infrastructure.db.session import with_optional_tx


@dataclass(slots=True)
class ContactPricingService:
    """Service for contact pricing lookup."""

    pricing_repo: ContactPricingRepository
    transaction_manager: TransactionManager | None = None

    async def get_price(self, bloggers_count: int) -> float | None:
        """Get price for bloggers count."""

        async def _run(session: object | None):
            pricing = await self.pricing_repo.get_by_bloggers_count(
                bloggers_count, session=session
            )
            return pricing.price if pricing else None

        return await with_optional_tx(self.transaction_manager, _run)

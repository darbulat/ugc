"""Service for contact pricing."""

from dataclasses import dataclass

from ugc_bot.application.ports import ContactPricingRepository, TransactionManager


@dataclass(slots=True)
class ContactPricingService:
    """Service for contact pricing lookup."""

    pricing_repo: ContactPricingRepository
    transaction_manager: TransactionManager | None = None

    async def get_price(self, bloggers_count: int) -> float | None:
        """Get price for bloggers count."""

        if self.transaction_manager is None:
            pricing = await self.pricing_repo.get_by_bloggers_count(bloggers_count)
        else:
            async with self.transaction_manager.transaction() as session:
                pricing = await self.pricing_repo.get_by_bloggers_count(
                    bloggers_count, session=session
                )
        return pricing.price if pricing else None

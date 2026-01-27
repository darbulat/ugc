"""Service for contact pricing."""

from dataclasses import dataclass

from ugc_bot.application.ports import ContactPricingRepository


@dataclass(slots=True)
class ContactPricingService:
    """Service for contact pricing lookup."""

    pricing_repo: ContactPricingRepository

    async def get_price(self, bloggers_count: int) -> float | None:
        """Get price for bloggers count."""

        pricing = await self.pricing_repo.get_by_bloggers_count(bloggers_count)
        return pricing.price if pricing else None

"""Tests for contact pricing service."""

from datetime import datetime, timezone

import pytest

from ugc_bot.application.services.contact_pricing_service import (
    ContactPricingService,
)
from ugc_bot.domain.entities import ContactPricing
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryContactPricingRepository,
)


@pytest.mark.asyncio
async def test_get_price_without_transaction_manager() -> None:
    """get_price uses repo directly when transaction_manager is None."""
    repo = InMemoryContactPricingRepository()
    await repo.save(
        ContactPricing(
            bloggers_count=3,
            price=1500.0,
            updated_at=datetime.now(timezone.utc),
        )
    )
    service = ContactPricingService(pricing_repo=repo, transaction_manager=None)
    got = await service.get_price(3)
    assert got == 1500.0


@pytest.mark.asyncio
async def test_get_price_with_transaction_manager(fake_tm) -> None:
    """get_price uses transaction when transaction_manager is set."""
    repo = InMemoryContactPricingRepository()
    await repo.save(
        ContactPricing(
            bloggers_count=5,
            price=2500.0,
            updated_at=datetime.now(timezone.utc),
        )
    )
    service = ContactPricingService(
        pricing_repo=repo, transaction_manager=fake_tm
    )
    got = await service.get_price(5)
    assert got == 2500.0

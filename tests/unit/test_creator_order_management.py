"""Unit tests for manager creator order management feature."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.infrastructure.memory_repositories import (
    InMemoryOfferDispatchRepository,
)

ORDER_ID = UUID("00000000-0000-0000-0000-000000000d00")
BLOGGER_ID = UUID("00000000-0000-0000-0000-000000000d01")
ADV_ID = UUID("00000000-0000-0000-0000-000000000d02")
MGR_ID = UUID("00000000-0000-0000-0000-000000000d03")


@pytest.mark.asyncio
async def test_set_in_offer_updates_value() -> None:
    """set_in_offer updates the in_offer flag to False."""
    repo = InMemoryOfferDispatchRepository()
    await repo.record_sent(ORDER_ID, BLOGGER_ID)
    await repo.set_in_offer(ORDER_ID, BLOGGER_ID, False)
    result = await repo.get_by_order_and_blogger(ORDER_ID, BLOGGER_ID)
    assert result is not None
    assert result.in_offer is False


@pytest.mark.asyncio
async def test_set_in_offer_can_set_true() -> None:
    """set_in_offer can also set in_offer back to True."""
    repo = InMemoryOfferDispatchRepository()
    await repo.record_sent(ORDER_ID, BLOGGER_ID)
    await repo.set_in_offer(ORDER_ID, BLOGGER_ID, False)
    await repo.set_in_offer(ORDER_ID, BLOGGER_ID, True)
    result = await repo.get_by_order_and_blogger(ORDER_ID, BLOGGER_ID)
    assert result is not None
    assert result.in_offer is True


@pytest.mark.asyncio
async def test_set_in_offer_noop_when_missing() -> None:
    """set_in_offer does not raise if dispatch does not exist."""
    repo = InMemoryOfferDispatchRepository()
    await repo.set_in_offer(ORDER_ID, BLOGGER_ID, False)  # no exception
    result = await repo.get_by_order_and_blogger(ORDER_ID, BLOGGER_ID)
    assert result is None


from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.domain.enums import InteractionStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryInteractionRepository,
)


def _make_interaction_service() -> InteractionService:
    """Create InteractionService with InMemory repos."""
    return InteractionService(
        interaction_repo=InMemoryInteractionRepository(),
        transaction_manager=None,
        postpone_delay_minutes=60,
        max_postpone_count=3,
        metrics_collector=None,
        referral_income_service=None,
    )


@pytest.mark.asyncio
async def test_cancel_interaction_sets_deleted() -> None:
    """cancel_interaction sets PENDING interaction to DELETED."""
    service = _make_interaction_service()
    await service.create_for_contacts_sent(ORDER_ID, BLOGGER_ID, ADV_ID)
    await service.cancel_interaction(ORDER_ID, BLOGGER_ID, ADV_ID)
    interaction = await service._get_by_participants(ORDER_ID, BLOGGER_ID, ADV_ID)
    assert interaction is not None
    assert interaction.status == InteractionStatus.DELETED


@pytest.mark.asyncio
async def test_cancel_interaction_noop_when_already_deleted() -> None:
    """cancel_interaction is no-op if interaction already DELETED."""
    service = _make_interaction_service()
    await service.create_for_contacts_sent(ORDER_ID, BLOGGER_ID, ADV_ID)
    await service.cancel_interaction(ORDER_ID, BLOGGER_ID, ADV_ID)
    await service.cancel_interaction(ORDER_ID, BLOGGER_ID, ADV_ID)  # second call
    interaction = await service._get_by_participants(ORDER_ID, BLOGGER_ID, ADV_ID)
    assert interaction is not None
    assert interaction.status == InteractionStatus.DELETED


@pytest.mark.asyncio
async def test_cancel_interaction_noop_when_not_found() -> None:
    """cancel_interaction is no-op when no interaction exists."""
    service = _make_interaction_service()
    await service.cancel_interaction(ORDER_ID, BLOGGER_ID, ADV_ID)  # no exception

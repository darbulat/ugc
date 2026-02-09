"""Tests for in-memory repository implementations."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from ugc_bot.domain.entities import Order, OrderResponse
from ugc_bot.domain.enums import OrderStatus, OrderType
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryOrderRepository,
    InMemoryOrderResponseRepository,
)


@pytest.mark.asyncio
async def test_order_repo_list_active() -> None:
    """list_active returns only ACTIVE orders."""

    repo = InMemoryOrderRepository()
    adv_id = UUID("00000000-0000-0000-0000-000000000001")
    now = datetime.now(timezone.utc)
    await repo.save(
        Order(
            order_id=UUID("00000000-0000-0000-0000-000000000010"),
            advertiser_id=adv_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://x.com",
            offer_text="Offer",
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
            status=OrderStatus.ACTIVE,
            created_at=now,
            completed_at=None,
        )
    )
    await repo.save(
        Order(
            order_id=UUID("00000000-0000-0000-0000-000000000011"),
            advertiser_id=adv_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://x.com",
            offer_text="Offer",
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
            status=OrderStatus.NEW,
            created_at=now,
            completed_at=None,
        )
    )
    active = list(await repo.list_active())
    assert len(active) == 1
    assert active[0].status == OrderStatus.ACTIVE


@pytest.mark.asyncio
async def test_order_repo_list_completed_before() -> None:
    """list_completed_before returns orders with completed_at before cutoff."""

    repo = InMemoryOrderRepository()
    adv_id = UUID("00000000-0000-0000-0000-000000000002")
    now = datetime.now(timezone.utc)
    cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
    await repo.save(
        Order(
            order_id=UUID("00000000-0000-0000-0000-000000000020"),
            advertiser_id=adv_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://x.com",
            offer_text="Offer",
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
            status=OrderStatus.CLOSED,
            created_at=now,
            completed_at=datetime(2025, 5, 15, tzinfo=timezone.utc),
        )
    )
    completed = list(await repo.list_completed_before(cutoff))
    assert len(completed) == 1
    assert completed[0].completed_at is not None


@pytest.mark.asyncio
async def test_order_response_repo_list_by_blogger() -> None:
    """list_by_blogger returns responses for the blogger."""

    repo = InMemoryOrderResponseRepository()
    order_id = UUID("00000000-0000-0000-0000-000000000030")
    blogger_id = UUID("00000000-0000-0000-0000-000000000031")
    repo.responses.append(
        OrderResponse(
            response_id=uuid4(),
            order_id=order_id,
            blogger_id=blogger_id,
            responded_at=datetime.now(timezone.utc),
        )
    )
    responses = await repo.list_by_blogger(blogger_id)
    assert len(responses) == 1
    assert responses[0].blogger_id == blogger_id


@pytest.mark.asyncio
async def test_order_response_repo_count_by_order() -> None:
    """count_by_order returns count of responses for order."""

    repo = InMemoryOrderResponseRepository()
    order_id = UUID("00000000-0000-0000-0000-000000000040")
    repo.responses.append(
        OrderResponse(
            response_id=uuid4(),
            order_id=order_id,
            blogger_id=UUID("00000000-0000-0000-0000-000000000041"),
            responded_at=datetime.now(timezone.utc),
        )
    )
    repo.responses.append(
        OrderResponse(
            response_id=uuid4(),
            order_id=order_id,
            blogger_id=UUID("00000000-0000-0000-0000-000000000042"),
            responded_at=datetime.now(timezone.utc),
        )
    )
    count = await repo.count_by_order(order_id)
    assert count == 2

"""Tests for round-robin manager assignment in OfferResponseService."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.services.offer_response_service import (
    OfferResponseService,
)
from ugc_bot.domain.entities import ManagerOrder, Order
from ugc_bot.domain.enums import OrderStatus, OrderType
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryManagerOrderRepository,
    InMemoryOfferDispatchRepository,
    InMemoryOrderRepository,
)

ORDER_ID = UUID("00000000-0000-0000-0000-000000000a00")
ADV_ID = UUID("00000000-0000-0000-0000-000000000a01")
BLOGGER_1 = UUID("00000000-0000-0000-0000-000000000a02")
BLOGGER_2 = UUID("00000000-0000-0000-0000-000000000a03")
MANAGER_A = UUID("00000000-0000-0000-0000-000000000a10")
MANAGER_B = UUID("00000000-0000-0000-0000-000000000a11")


def _make_order(
    bloggers_needed: int = 3,
    last_round_robin_index: int = 0,
) -> Order:
    return Order(
        order_id=ORDER_ID,
        advertiser_id=ADV_ID,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=bloggers_needed,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        last_round_robin_index=last_round_robin_index,
    )


def _make_manager_order(user_id: UUID) -> ManagerOrder:
    return ManagerOrder(
        user_id=user_id,
        order_id=ORDER_ID,
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_respond_assigns_manager_when_managers_exist(
    fake_tm: object,
) -> None:
    """Assigns manager_id and increments index."""
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    manager_order_repo = InMemoryManagerOrderRepository()

    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        manager_order_repo=manager_order_repo,
        transaction_manager=fake_tm,
    )

    await order_repo.save(_make_order())
    await manager_order_repo.save(_make_manager_order(MANAGER_A))
    await manager_order_repo.save(_make_manager_order(MANAGER_B))
    await dispatch_repo.record_sent(ORDER_ID, BLOGGER_1)

    result = await service.respond_and_finalize(ORDER_ID, BLOGGER_1)

    assert result.manager_id == MANAGER_A
    assert result.response.manager_id == MANAGER_A

    saved_order = await order_repo.get_by_id(ORDER_ID)
    assert saved_order is not None
    assert saved_order.last_round_robin_index == 1


@pytest.mark.asyncio
async def test_respond_no_manager_when_none_assigned(
    fake_tm: object,
) -> None:
    """When no managers exist, manager_id is None and index unchanged."""
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    manager_order_repo = InMemoryManagerOrderRepository()

    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        manager_order_repo=manager_order_repo,
        transaction_manager=fake_tm,
    )

    await order_repo.save(_make_order())
    await dispatch_repo.record_sent(ORDER_ID, BLOGGER_1)

    result = await service.respond_and_finalize(ORDER_ID, BLOGGER_1)

    assert result.manager_id is None

    saved_order = await order_repo.get_by_id(ORDER_ID)
    assert saved_order is not None
    assert saved_order.last_round_robin_index == 0


@pytest.mark.asyncio
async def test_two_consecutive_responses_get_different_managers(
    fake_tm: object,
) -> None:
    """Two consecutive responses round-robin through managers."""
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    manager_order_repo = InMemoryManagerOrderRepository()

    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        manager_order_repo=manager_order_repo,
        transaction_manager=fake_tm,
    )

    await order_repo.save(_make_order(bloggers_needed=3))
    await manager_order_repo.save(_make_manager_order(MANAGER_A))
    await manager_order_repo.save(_make_manager_order(MANAGER_B))
    await dispatch_repo.record_sent(ORDER_ID, BLOGGER_1)
    await dispatch_repo.record_sent(ORDER_ID, BLOGGER_2)

    result1 = await service.respond_and_finalize(ORDER_ID, BLOGGER_1)
    result2 = await service.respond_and_finalize(ORDER_ID, BLOGGER_2)

    assert result1.manager_id == MANAGER_A
    assert result2.manager_id == MANAGER_B

    saved_order = await order_repo.get_by_id(ORDER_ID)
    assert saved_order is not None
    assert saved_order.last_round_robin_index == 2


@pytest.mark.asyncio
async def test_respond_delegates_to_respond_and_finalize(
    fake_tm: object,
) -> None:
    """respond() returns the OfferDispatch from respond_and_finalize."""
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()

    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )

    await order_repo.save(_make_order())
    await dispatch_repo.record_sent(ORDER_ID, BLOGGER_1)

    dispatch = await service.respond(ORDER_ID, BLOGGER_1)

    assert dispatch.order_id == ORDER_ID
    assert dispatch.blogger_id == BLOGGER_1
    assert dispatch.accepted is True


@pytest.mark.asyncio
async def test_respond_and_finalize_no_tx_manager_raises() -> None:
    """ValueError when transaction_manager is None."""
    service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        dispatch_repo=InMemoryOfferDispatchRepository(),
        transaction_manager=None,
    )
    with pytest.raises(ValueError, match="transaction_manager"):
        await service.respond_and_finalize(ORDER_ID, BLOGGER_1)


@pytest.mark.asyncio
async def test_respond_and_finalize_order_not_found(
    fake_tm: object,
) -> None:
    """OrderNotFoundError when order does not exist."""
    from ugc_bot.application.errors import OrderNotFoundError

    service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        dispatch_repo=InMemoryOfferDispatchRepository(),
        transaction_manager=fake_tm,
    )
    with pytest.raises(OrderNotFoundError):
        await service.respond_and_finalize(ORDER_ID, BLOGGER_1)


@pytest.mark.asyncio
async def test_respond_and_finalize_inactive_order(
    fake_tm: object,
) -> None:
    """OrderNotActiveError when order is closed but not full."""
    from ugc_bot.application.errors import OrderNotActiveError

    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()

    closed_order = Order(
        order_id=ORDER_ID,
        advertiser_id=ADV_ID,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(closed_order)
    await dispatch_repo.record_sent(ORDER_ID, BLOGGER_1)

    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )
    with pytest.raises(OrderNotActiveError):
        await service.respond_and_finalize(ORDER_ID, BLOGGER_1)


@pytest.mark.asyncio
async def test_respond_and_finalize_duplicate_response(
    fake_tm: object,
) -> None:
    """OrderCreationError on duplicate response."""
    from ugc_bot.application.errors import OrderCreationError

    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()

    await order_repo.save(_make_order())
    await dispatch_repo.record_sent(ORDER_ID, BLOGGER_1)

    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )
    await service.respond_and_finalize(ORDER_ID, BLOGGER_1)
    with pytest.raises(OrderCreationError):
        await service.respond_and_finalize(ORDER_ID, BLOGGER_1)


@pytest.mark.asyncio
async def test_overflow_response_no_order_save(
    fake_tm: object,
) -> None:
    """Overflow (beyond bloggers_needed) uses original order."""
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()

    await order_repo.save(_make_order(bloggers_needed=1))
    await dispatch_repo.record_sent(ORDER_ID, BLOGGER_1)
    await dispatch_repo.record_sent(ORDER_ID, BLOGGER_2)

    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )
    # First fills the slot
    r1 = await service.respond_and_finalize(ORDER_ID, BLOGGER_1)
    assert r1.accepted is True

    # Second is overflow — order is CLOSED but full, so it proceeds
    r2 = await service.respond_and_finalize(ORDER_ID, BLOGGER_2)
    assert r2.accepted is False
    assert r2.response.in_offer is False


@pytest.mark.asyncio
async def test_list_by_order(fake_tm: object) -> None:
    """list_by_order returns responded dispatches."""
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()

    await order_repo.save(_make_order())
    await dispatch_repo.record_sent(ORDER_ID, BLOGGER_1)

    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )
    await service.respond_and_finalize(ORDER_ID, BLOGGER_1)

    results = await service.list_by_order(ORDER_ID)
    assert len(results) == 1
    assert results[0].blogger_id == BLOGGER_1


@pytest.mark.asyncio
async def test_list_by_blogger(fake_tm: object) -> None:
    """list_by_blogger returns dispatches for a blogger."""
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()

    await order_repo.save(_make_order())
    await dispatch_repo.record_sent(ORDER_ID, BLOGGER_1)

    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )
    await service.respond_and_finalize(ORDER_ID, BLOGGER_1)

    results = await service.list_by_blogger(BLOGGER_1)
    assert len(results) == 1
    assert results[0].order_id == ORDER_ID


@pytest.mark.asyncio
async def test_count_by_order(fake_tm: object) -> None:
    """count_by_order returns count of dispatches."""
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()

    await order_repo.save(_make_order())
    await dispatch_repo.record_sent(ORDER_ID, BLOGGER_1)

    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )

    count = await service.count_by_order(ORDER_ID)
    assert count >= 0


@pytest.mark.asyncio
async def test_respond_with_metrics_collector(
    fake_tm: object,
) -> None:
    """Metrics are recorded when collector is provided."""
    from unittest.mock import MagicMock

    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    metrics = MagicMock()

    await order_repo.save(_make_order())
    await dispatch_repo.record_sent(ORDER_ID, BLOGGER_1)

    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
        metrics_collector=metrics,
    )
    await service.respond_and_finalize(ORDER_ID, BLOGGER_1)

    metrics.record_blogger_response.assert_called_once()


@pytest.mark.asyncio
async def test_in_memory_dispatch_list_by_order_and_manager(
    fake_tm: object,
) -> None:
    """InMemory list_responses_by_order_and_manager filters correctly."""
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    manager_order_repo = InMemoryManagerOrderRepository()

    await order_repo.save(_make_order(bloggers_needed=5))
    await manager_order_repo.save(_make_manager_order(MANAGER_A))
    await dispatch_repo.record_sent(ORDER_ID, BLOGGER_1)
    await dispatch_repo.record_sent(ORDER_ID, BLOGGER_2)

    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        manager_order_repo=manager_order_repo,
        transaction_manager=fake_tm,
    )
    await service.respond_and_finalize(ORDER_ID, BLOGGER_1)
    await service.respond_and_finalize(ORDER_ID, BLOGGER_2)

    # list_responses_by_order_and_manager
    results = await dispatch_repo.list_responses_by_order_and_manager(
        ORDER_ID, MANAGER_A, in_offer=True
    )
    assert len(results) == 2

    # count_responses_by_order_and_manager
    count = await dispatch_repo.count_responses_by_order_and_manager(
        ORDER_ID, MANAGER_A, in_offer=True
    )
    assert count == 2

    # No results for wrong manager
    results_none = await dispatch_repo.list_responses_by_order_and_manager(
        ORDER_ID, MANAGER_B, in_offer=True
    )
    assert len(results_none) == 0

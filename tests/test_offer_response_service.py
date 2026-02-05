"""Tests for offer response service."""

from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import UUID

import pytest

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.services.offer_response_service import OfferResponseService
from ugc_bot.domain.entities import Order
from ugc_bot.domain.enums import OrderStatus, OrderType
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryOrderRepository,
    InMemoryOrderResponseRepository,
)


@pytest.mark.asyncio
async def test_offer_response_requires_transaction_manager() -> None:
    """Raise when transaction_manager is None."""
    service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        response_repo=InMemoryOrderResponseRepository(),
        transaction_manager=None,
    )
    with pytest.raises(ValueError, match="transaction_manager"):
        await service.respond_and_finalize(
            order_id=UUID("00000000-0000-0000-0000-000000000800"),
            blogger_id=UUID("00000000-0000-0000-0000-000000000802"),
        )


@pytest.mark.asyncio
async def test_offer_response_success(fake_tm: object) -> None:
    """Create response for active order."""

    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    service = OfferResponseService(
        order_repo=order_repo,
        response_repo=response_repo,
        transaction_manager=fake_tm,
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000800"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000801"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    response = await service.respond(
        order_id=order.order_id,
        blogger_id=UUID("00000000-0000-0000-0000-000000000802"),
    )
    assert response.order_id == order.order_id


@pytest.mark.asyncio
async def test_offer_response_limit(fake_tm: object) -> None:
    """Prevent responses above limit."""

    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    service = OfferResponseService(
        order_repo=order_repo,
        response_repo=response_repo,
        transaction_manager=fake_tm,
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000810"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000811"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)
    await service.respond(
        order_id=order.order_id,
        blogger_id=UUID("00000000-0000-0000-0000-000000000812"),
    )

    with pytest.raises(OrderCreationError):
        await service.respond(
            order_id=order.order_id,
            blogger_id=UUID("00000000-0000-0000-0000-000000000813"),
        )


@pytest.mark.asyncio
async def test_offer_response_order_not_found(fake_tm: object) -> None:
    """Fail when order is missing."""

    service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        response_repo=InMemoryOrderResponseRepository(),
        transaction_manager=fake_tm,
    )

    with pytest.raises(OrderCreationError):
        await service.respond(
            order_id=UUID("00000000-0000-0000-0000-000000000820"),
            blogger_id=UUID("00000000-0000-0000-0000-000000000821"),
        )


@pytest.mark.asyncio
async def test_offer_response_requires_active_order(fake_tm: object) -> None:
    """Fail when order is not active."""

    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    service = OfferResponseService(
        order_repo=order_repo,
        response_repo=response_repo,
        transaction_manager=fake_tm,
    )

    await order_repo.save(
        Order(
            order_id=UUID("00000000-0000-0000-0000-000000000830"),
            advertiser_id=UUID("00000000-0000-0000-0000-000000000831"),
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=1,
            status=OrderStatus.NEW,
            created_at=datetime.now(timezone.utc),
            completed_at=None,
        )
    )

    with pytest.raises(OrderCreationError):
        await service.respond(
            order_id=UUID("00000000-0000-0000-0000-000000000830"),
            blogger_id=UUID("00000000-0000-0000-0000-000000000832"),
        )


@pytest.mark.asyncio
async def test_offer_response_finalize_closes_order(fake_tm: object) -> None:
    """Finalize response closes order and sets contacts."""

    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    service = OfferResponseService(
        order_repo=order_repo,
        response_repo=response_repo,
        transaction_manager=fake_tm,
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000840"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000841"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    result = await service.respond_and_finalize(
        order_id=order.order_id,
        blogger_id=UUID("00000000-0000-0000-0000-000000000842"),
    )

    updated = await order_repo.get_by_id(order.order_id)
    assert updated is not None
    assert updated.status == OrderStatus.CLOSED
    assert updated.completed_at is not None
    assert result.response_count == 1


@pytest.mark.asyncio
async def test_offer_response_transaction_manager(fake_tm: object) -> None:
    """Use transaction manager path for finalize."""

    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    service = OfferResponseService(
        order_repo=order_repo,
        response_repo=response_repo,
        transaction_manager=fake_tm,
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000850"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000851"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    result = await service.respond_and_finalize(
        order_id=order.order_id,
        blogger_id=UUID("00000000-0000-0000-0000-000000000852"),
    )

    assert result.order.order_id == order.order_id
    assert result.response_count == 1
    assert result.order.completed_at is None
    assert result.order.status == OrderStatus.ACTIVE

    updated = await order_repo.get_by_id(order.order_id)
    assert updated is not None
    assert updated.completed_at is None


@pytest.mark.asyncio
async def test_offer_response_completed_at_set_only_when_last_blogger_responds(
    fake_tm: object,
) -> None:
    """completed_at is set only when the last blogger responds."""

    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    service = OfferResponseService(
        order_repo=order_repo,
        response_repo=response_repo,
        transaction_manager=fake_tm,
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000900"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000901"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    result1 = await service.respond_and_finalize(
        order_id=order.order_id,
        blogger_id=UUID("00000000-0000-0000-0000-000000000902"),
    )
    assert result1.order.completed_at is None
    assert result1.order.status == OrderStatus.ACTIVE

    result2 = await service.respond_and_finalize(
        order_id=order.order_id,
        blogger_id=UUID("00000000-0000-0000-0000-000000000903"),
    )
    assert result2.order.completed_at is not None
    assert result2.order.status == OrderStatus.CLOSED

    updated = await order_repo.get_by_id(order.order_id)
    assert updated is not None
    assert updated.completed_at is not None


@pytest.mark.asyncio
async def test_offer_response_records_metrics_when_enabled(fake_tm: object) -> None:
    """Record metrics when collector is provided."""

    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    metrics = Mock()
    service = OfferResponseService(
        order_repo=order_repo,
        response_repo=response_repo,
        metrics_collector=metrics,
        transaction_manager=fake_tm,
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000860"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000861"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    blogger_id = UUID("00000000-0000-0000-0000-000000000862")
    await service.respond_and_finalize(order_id=order.order_id, blogger_id=blogger_id)

    metrics.record_blogger_response.assert_called_once_with(
        order_id=str(order.order_id),
        blogger_id=str(blogger_id),
    )


@pytest.mark.asyncio
async def test_offer_response_tx_order_not_found(fake_tm: object) -> None:
    """Transaction path: fail when order is missing."""

    service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        response_repo=InMemoryOrderResponseRepository(),
        transaction_manager=fake_tm,
    )

    with pytest.raises(OrderCreationError):
        await service.respond_and_finalize(
            order_id=UUID("00000000-0000-0000-0000-000000000870"),
            blogger_id=UUID("00000000-0000-0000-0000-000000000871"),
        )


@pytest.mark.asyncio
async def test_offer_response_tx_requires_active_order(fake_tm: object) -> None:
    """Transaction path: fail when order is not active."""

    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    service = OfferResponseService(
        order_repo=order_repo,
        response_repo=response_repo,
        transaction_manager=fake_tm,
    )

    await order_repo.save(
        Order(
            order_id=UUID("00000000-0000-0000-0000-000000000880"),
            advertiser_id=UUID("00000000-0000-0000-0000-000000000881"),
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=1,
            status=OrderStatus.NEW,
            created_at=datetime.now(timezone.utc),
            completed_at=None,
        )
    )

    with pytest.raises(OrderCreationError):
        await service.respond_and_finalize(
            order_id=UUID("00000000-0000-0000-0000-000000000880"),
            blogger_id=UUID("00000000-0000-0000-0000-000000000882"),
        )


@pytest.mark.asyncio
async def test_offer_response_tx_duplicate_response_is_rejected(
    fake_tm: object,
) -> None:
    """Transaction path: reject duplicate response."""

    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    service = OfferResponseService(
        order_repo=order_repo,
        response_repo=response_repo,
        transaction_manager=fake_tm,
    )

    order_id = UUID("00000000-0000-0000-0000-000000000890")
    blogger_id = UUID("00000000-0000-0000-0000-000000000892")
    await order_repo.save(
        Order(
            order_id=order_id,
            advertiser_id=UUID("00000000-0000-0000-0000-000000000891"),
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=2,
            status=OrderStatus.ACTIVE,
            created_at=datetime.now(timezone.utc),
            completed_at=None,
        )
    )

    await service.respond_and_finalize(order_id=order_id, blogger_id=blogger_id)
    with pytest.raises(OrderCreationError):
        await service.respond_and_finalize(order_id=order_id, blogger_id=blogger_id)

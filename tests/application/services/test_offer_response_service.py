"""Tests for offer response service."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest

from ugc_bot.application.errors import (
    OrderCreationError,
    OrderNotActiveError,
    OrderNotFoundError,
)
from ugc_bot.application.services.offer_response_service import (
    OfferResponseService,
)
from ugc_bot.domain.entities import Order, User
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    OrderType,
    UserStatus,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryOfferDispatchRepository,
    InMemoryOrderRepository,
    InMemoryUserRepository,
)


@pytest.mark.asyncio
async def test_offer_response_requires_transaction_manager() -> None:
    """Raise when transaction_manager is None."""
    service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        dispatch_repo=InMemoryOfferDispatchRepository(),
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
    dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000800"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000801"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)
    await dispatch_repo.record_sent(
        order.order_id, UUID("00000000-0000-0000-0000-000000000802")
    )

    response = await service.respond(
        order_id=order.order_id,
        blogger_id=UUID("00000000-0000-0000-0000-000000000802"),
    )
    assert response.order_id == order.order_id


@pytest.mark.asyncio
async def test_offer_response_overflow_saved_with_accepted_false(
    fake_tm: object,
) -> None:
    """When limit reached, overflow response is saved with accepted=False."""

    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000810"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000811"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)
    await dispatch_repo.record_sent(
        order.order_id, UUID("00000000-0000-0000-0000-000000000812")
    )
    await dispatch_repo.record_sent(
        order.order_id, UUID("00000000-0000-0000-0000-000000000813")
    )
    first = await service.respond_and_finalize(
        order_id=order.order_id,
        blogger_id=UUID("00000000-0000-0000-0000-000000000812"),
    )
    assert first.accepted is True
    assert first.response.in_offer is True

    second = await service.respond_and_finalize(
        order_id=order.order_id,
        blogger_id=UUID("00000000-0000-0000-0000-000000000813"),
    )
    assert second.accepted is False
    assert second.response.in_offer is False
    total = await dispatch_repo.count_by_order(order.order_id)
    assert total == 2
    accepted_count = await dispatch_repo.count_accepted_by_order(order.order_id)
    assert accepted_count == 1


@pytest.mark.asyncio
async def test_respond_and_finalize_preserves_order_min_max_followers(
    fake_tm: object,
) -> None:
    """Regression: creator accept must not drop min_followers, max_followers."""

    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000815"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000816"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        min_followers=1000,
        max_followers=50000,
    )
    await order_repo.save(order)
    await dispatch_repo.record_sent(
        order.order_id, UUID("00000000-0000-0000-0000-000000000817")
    )
    result = await service.respond_and_finalize(
        order_id=order.order_id,
        blogger_id=UUID("00000000-0000-0000-0000-000000000817"),
    )
    assert result.order.status == OrderStatus.CLOSED
    saved = await order_repo.get_by_id(order.order_id)
    assert saved is not None
    assert saved.min_followers == 1000
    assert saved.max_followers == 50000


@pytest.mark.asyncio
async def test_offer_response_order_not_found(fake_tm: object) -> None:
    """Fail when order is missing."""

    service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        dispatch_repo=InMemoryOfferDispatchRepository(),
        transaction_manager=fake_tm,
    )

    with pytest.raises(OrderNotFoundError):
        await service.respond(
            order_id=UUID("00000000-0000-0000-0000-000000000820"),
            blogger_id=UUID("00000000-0000-0000-0000-000000000821"),
        )


@pytest.mark.asyncio
async def test_offer_response_requires_active_order(fake_tm: object) -> None:
    """Fail when order is not active."""

    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )

    await order_repo.save(
        Order(
            order_id=UUID("00000000-0000-0000-0000-000000000830"),
            advertiser_id=UUID("00000000-0000-0000-0000-000000000831"),
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Offer",
            barter_description=None,
            price=1000.0,
            bloggers_needed=1,
            status=OrderStatus.NEW,
            created_at=datetime.now(timezone.utc),
            completed_at=None,
        )
    )

    with pytest.raises(OrderNotActiveError):
        await service.respond(
            order_id=UUID("00000000-0000-0000-0000-000000000830"),
            blogger_id=UUID("00000000-0000-0000-0000-000000000832"),
        )


@pytest.mark.asyncio
async def test_offer_response_finalize_closes_order(fake_tm: object) -> None:
    """Finalize response closes order and sets contacts."""

    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000840"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000841"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)
    await dispatch_repo.record_sent(
        order.order_id, UUID("00000000-0000-0000-0000-000000000842")
    )

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
    dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000850"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000851"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)
    await dispatch_repo.record_sent(
        order.order_id, UUID("00000000-0000-0000-0000-000000000852")
    )

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
    dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000900"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000901"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)
    await dispatch_repo.record_sent(
        order.order_id, UUID("00000000-0000-0000-0000-000000000902")
    )
    await dispatch_repo.record_sent(
        order.order_id, UUID("00000000-0000-0000-0000-000000000903")
    )

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
async def test_offer_response_records_metrics_when_enabled(
    fake_tm: object,
) -> None:
    """Record metrics when collector is provided."""

    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    metrics = Mock()
    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        metrics_collector=metrics,
        transaction_manager=fake_tm,
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000860"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000861"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    blogger_id = UUID("00000000-0000-0000-0000-000000000862")
    await dispatch_repo.record_sent(order.order_id, blogger_id)
    await service.respond_and_finalize(
        order_id=order.order_id, blogger_id=blogger_id
    )

    metrics.record_blogger_response.assert_called_once_with(
        order_id=str(order.order_id),
        blogger_id=str(blogger_id),
    )


@pytest.mark.asyncio
async def test_offer_response_tx_order_not_found(fake_tm: object) -> None:
    """Transaction path: fail when order is missing."""

    service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        dispatch_repo=InMemoryOfferDispatchRepository(),
        transaction_manager=fake_tm,
    )

    with pytest.raises(OrderNotFoundError):
        await service.respond_and_finalize(
            order_id=UUID("00000000-0000-0000-0000-000000000870"),
            blogger_id=UUID("00000000-0000-0000-0000-000000000871"),
        )


@pytest.mark.asyncio
async def test_offer_response_tx_requires_active_order(fake_tm: object) -> None:
    """Transaction path: fail when order is not active."""

    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )

    await order_repo.save(
        Order(
            order_id=UUID("00000000-0000-0000-0000-000000000880"),
            advertiser_id=UUID("00000000-0000-0000-0000-000000000881"),
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Offer",
            barter_description=None,
            price=1000.0,
            bloggers_needed=1,
            status=OrderStatus.NEW,
            created_at=datetime.now(timezone.utc),
            completed_at=None,
        )
    )

    with pytest.raises(OrderNotActiveError):
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
    dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
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
            barter_description=None,
            price=1000.0,
            bloggers_needed=2,
            status=OrderStatus.ACTIVE,
            created_at=datetime.now(timezone.utc),
            completed_at=None,
        )
    )
    await dispatch_repo.record_sent(order_id, blogger_id)

    await service.respond_and_finalize(order_id=order_id, blogger_id=blogger_id)
    with pytest.raises(OrderCreationError):
        await service.respond_and_finalize(
            order_id=order_id, blogger_id=blogger_id
        )


@pytest.mark.asyncio
async def test_respond_and_finalize_closed_triggers_advertiser_referral(
    fake_tm: object,
) -> None:
    """Closing the order calls record_advertiser_referral_income."""

    order_id = UUID("00000000-0000-0000-0000-000000003001")
    advertiser_id = UUID("00000000-0000-0000-0000-000000003002")
    blogger_id = UUID("00000000-0000-0000-0000-000000003003")

    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    user_repo = InMemoryUserRepository()

    order = Order(
        order_id=order_id,
        advertiser_id=advertiser_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)
    await dispatch_repo.record_sent(order_id, blogger_id)

    advertiser = User(
        user_id=advertiser_id,
        external_id="adv_ext_3",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser3",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        country="ru",
    )
    await user_repo.save(advertiser)

    referral_income_service = AsyncMock()
    service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
        user_repo=user_repo,
        referral_income_service=referral_income_service,
    )

    result = await service.respond_and_finalize(
        order_id=order_id,
        blogger_id=blogger_id,
    )

    assert result.order.status == OrderStatus.CLOSED
    (
        referral_income_service.record_advertiser_referral_income.assert_awaited_once()
    )
    mock_fn = referral_income_service.record_advertiser_referral_income
    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs["advertiser_id"] == advertiser_id
    assert call_kwargs["advertiser_country_code"] == "ru"

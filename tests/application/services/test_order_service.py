"""Tests for order service."""

from unittest.mock import patch
from uuid import UUID

import pytest

from tests.helpers.factories import create_test_advertiser
from tests.helpers.services import build_order_service
from ugc_bot.application.errors import OrderCreationError, UserNotFoundError
from ugc_bot.domain.enums import OrderType, UserStatus


@pytest.mark.asyncio
async def test_create_order_success(
    user_repo, advertiser_repo, order_repo
) -> None:
    """Create order with valid data."""

    user_id = await create_test_advertiser(
        user_repo, advertiser_repo, status=UserStatus.ACTIVE
    )

    service = build_order_service(user_repo, advertiser_repo, order_repo)
    order = await service.create_order(
        advertiser_id=user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
    )

    assert await order_repo.get_by_id(order.order_id) is not None


@pytest.mark.asyncio
async def test_create_order_invalid_user(
    user_repo, advertiser_repo, order_repo
) -> None:
    """Fail when user is missing."""

    service = build_order_service(user_repo, advertiser_repo, order_repo)

    with pytest.raises(UserNotFoundError):
        await service.create_order(
            advertiser_id=UUID("00000000-0000-0000-0000-000000000301"),
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Offer",
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
        )


@pytest.mark.asyncio
async def test_create_order_validation_errors(
    user_repo, advertiser_repo, order_repo
) -> None:
    """Validate required fields and price."""

    user_id = await create_test_advertiser(
        user_repo, advertiser_repo, status=UserStatus.ACTIVE
    )

    service = build_order_service(user_repo, advertiser_repo, order_repo)

    with pytest.raises(OrderCreationError):
        await service.create_order(
            advertiser_id=user_id,
            order_type=OrderType.UGC_ONLY,
            product_link="",
            offer_text="Offer",
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
        )

    with pytest.raises(OrderCreationError):
        await service.create_order(
            advertiser_id=user_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="",
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
        )

    with pytest.raises(OrderCreationError):
        await service.create_order(
            advertiser_id=user_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Offer",
            barter_description=None,
            price=0.0,
            bloggers_needed=3,
        )

    with pytest.raises(OrderCreationError):
        await service.create_order(
            advertiser_id=user_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Offer",
            barter_description=None,
            price=1000.0,
            bloggers_needed=7,
        )


@pytest.mark.asyncio
async def test_create_order_requires_advertiser_profile(
    user_repo, advertiser_repo, order_repo
) -> None:
    """Reject users without advertiser profile."""

    user_id = await create_test_advertiser(
        user_repo, advertiser_repo, status=UserStatus.ACTIVE
    )
    advertiser_repo.profiles.clear()

    service = build_order_service(user_repo, advertiser_repo, order_repo)
    with pytest.raises(OrderCreationError):
        await service.create_order(
            advertiser_id=user_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Offer",
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
        )


@pytest.mark.asyncio
async def test_create_order_blocked_user_rejected(
    user_repo, advertiser_repo, order_repo
) -> None:
    """Blocked users cannot create orders."""

    user_id = await create_test_advertiser(
        user_repo, advertiser_repo, status=UserStatus.BLOCKED
    )
    service = build_order_service(user_repo, advertiser_repo, order_repo)
    with pytest.raises(OrderCreationError, match="Blocked"):
        await service.create_order(
            advertiser_id=user_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Offer",
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
        )


@pytest.mark.asyncio
async def test_create_order_paused_user_rejected(
    user_repo, advertiser_repo, order_repo
) -> None:
    """Paused users cannot create orders."""

    user_id = await create_test_advertiser(
        user_repo, advertiser_repo, status=UserStatus.PAUSE
    )
    service = build_order_service(user_repo, advertiser_repo, order_repo)
    with pytest.raises(OrderCreationError, match="Paused"):
        await service.create_order(
            advertiser_id=user_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Offer",
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
        )


@pytest.mark.asyncio
async def test_create_order_negative_price_rejected(
    user_repo, advertiser_repo, order_repo
) -> None:
    """Negative price is rejected."""

    user_id = await create_test_advertiser(
        user_repo, advertiser_repo, status=UserStatus.ACTIVE
    )
    service = build_order_service(user_repo, advertiser_repo, order_repo)
    with pytest.raises(OrderCreationError, match="negative"):
        await service.create_order(
            advertiser_id=user_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Offer",
            barter_description=None,
            price=-100.0,
            bloggers_needed=3,
        )


@pytest.mark.asyncio
async def test_create_order_price_exceeds_max_rejected(
    user_repo, advertiser_repo, order_repo
) -> None:
    """Price exceeding NUMERIC(10,2) limit is rejected."""

    user_id = await create_test_advertiser(
        user_repo, advertiser_repo, status=UserStatus.ACTIVE
    )
    service = build_order_service(
        user_repo, advertiser_repo, order_repo, max_order_price=10_000.0
    )
    with pytest.raises(OrderCreationError, match="exceeds maximum"):
        await service.create_order(
            advertiser_id=user_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Offer",
            barter_description=None,
            price=10_001.0,
            bloggers_needed=3,
        )


@pytest.mark.asyncio
async def test_is_new_advertiser_returns_true_when_no_orders(
    user_repo, advertiser_repo, order_repo, fake_tm
) -> None:
    """is_new_advertiser returns True when advertiser has no orders."""
    user_id = await create_test_advertiser(
        user_repo, advertiser_repo, status=UserStatus.ACTIVE
    )
    service = build_order_service(
        user_repo, advertiser_repo, order_repo, transaction_manager=fake_tm
    )
    assert await service.is_new_advertiser(user_id) is True


@pytest.mark.asyncio
async def test_is_new_advertiser_returns_false_when_has_orders(
    user_repo, advertiser_repo, order_repo, fake_tm
) -> None:
    """is_new_advertiser returns False when advertiser has orders."""
    user_id = await create_test_advertiser(
        user_repo, advertiser_repo, status=UserStatus.ACTIVE
    )
    service = build_order_service(
        user_repo, advertiser_repo, order_repo, transaction_manager=fake_tm
    )
    await service.create_order(
        advertiser_id=user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
    )
    assert await service.is_new_advertiser(user_id) is False


@pytest.mark.asyncio
async def test_create_order_metrics_recorded_when_collector_set(
    user_repo, advertiser_repo, order_repo
) -> None:
    """When metrics_collector is set, record_order_created is called."""
    from unittest.mock import MagicMock

    user_id = await create_test_advertiser(
        user_repo, advertiser_repo, status=UserStatus.ACTIVE
    )
    metrics_collector = MagicMock()
    metrics_collector.record_order_created = MagicMock()
    service = build_order_service(user_repo, advertiser_repo, order_repo)
    service.metrics_collector = metrics_collector

    order = await service.create_order(
        advertiser_id=user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
    )

    metrics_collector.record_order_created.assert_called_once()
    call_kw = metrics_collector.record_order_created.call_args[1]
    assert call_kw["order_id"] == str(order.order_id)
    assert call_kw["advertiser_id"] == str(user_id)
    assert call_kw["price"] == 1000.0
    assert call_kw["bloggers_needed"] == 3


@pytest.mark.asyncio
async def test_create_order_new_advertiser_bloggers_over_10_rejected(
    user_repo, advertiser_repo, order_repo
) -> None:
    """New advertiser cannot request more than 10 bloggers."""
    user_id = await create_test_advertiser(
        user_repo, advertiser_repo, status=UserStatus.ACTIVE
    )
    service = build_order_service(user_repo, advertiser_repo, order_repo)

    with patch(
        "ugc_bot.application.services.order_service._validate_order_input"
    ) as mock_val:
        mock_val.return_value = (
            "https://example.com",
            "Offer",
            None,
        )
        with pytest.raises(
            OrderCreationError, match="NEW advertisers can request up to 10"
        ):
            await service.create_order(
                advertiser_id=user_id,
                order_type=OrderType.UGC_ONLY,
                product_link="https://example.com",
                offer_text="Offer",
                barter_description=None,
                price=1000.0,
                bloggers_needed=15,
            )


@pytest.mark.asyncio
async def test_create_order_and_list_with_transaction_manager(
    fake_tm: object, user_repo, advertiser_repo, order_repo
) -> None:
    """Cover transaction_manager path for create_order and list_orders."""

    user_id = await create_test_advertiser(
        user_repo, advertiser_repo, status=UserStatus.ACTIVE
    )
    service = build_order_service(
        user_repo, advertiser_repo, order_repo, transaction_manager=fake_tm
    )
    order = await service.create_order(
        advertiser_id=user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
    )
    assert order.order_id is not None
    orders = await service.list_by_advertiser(advertiser_id=user_id)
    assert len(orders) >= 1
    assert any(o.order_id == order.order_id for o in orders)

"""Tests for order service."""

from uuid import UUID

import pytest

from ugc_bot.application.errors import OrderCreationError, UserNotFoundError
from ugc_bot.domain.enums import OrderType, UserStatus
from tests.helpers.factories import create_test_advertiser
from tests.helpers.services import build_order_service


@pytest.mark.asyncio
async def test_create_order_success(user_repo, advertiser_repo, order_repo) -> None:
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
        ugc_requirements=None,
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
            ugc_requirements=None,
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
            ugc_requirements=None,
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
            ugc_requirements=None,
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
            ugc_requirements=None,
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
            ugc_requirements=None,
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
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
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
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
    )
    assert order.order_id is not None
    orders = await service.list_by_advertiser(advertiser_id=user_id)
    assert len(orders) >= 1
    assert any(o.order_id == order.order_id for o in orders)

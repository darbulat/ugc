"""Tests for order service."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.errors import OrderCreationError, UserNotFoundError
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.domain.entities import AdvertiserProfile, User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryOrderRepository,
    InMemoryUserRepository,
)


def _seed_advertiser(
    repo: InMemoryUserRepository,
    advertiser_repo: InMemoryAdvertiserProfileRepository,
    status: UserStatus,
) -> UUID:
    """Seed an advertiser user."""

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000300"),
        external_id="888",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=status,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    repo.save(user)
    advertiser_repo.save(
        AdvertiserProfile(
            user_id=user.user_id, contact="contact", instagram_url=None, confirmed=False
        )
    )
    return user.user_id


def test_create_order_success() -> None:
    """Create order with valid data."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    user_id = _seed_advertiser(user_repo, advertiser_repo, UserStatus.ACTIVE)

    service = OrderService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
    )
    order = service.create_order(
        advertiser_id=user_id,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
    )

    assert order_repo.get_by_id(order.order_id) is not None


def test_create_order_invalid_user() -> None:
    """Fail when user is missing."""

    service = OrderService(
        user_repo=InMemoryUserRepository(),
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
        order_repo=InMemoryOrderRepository(),
    )

    with pytest.raises(UserNotFoundError):
        service.create_order(
            advertiser_id=UUID("00000000-0000-0000-0000-000000000301"),
            product_link="https://example.com",
            offer_text="Offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
        )


def test_create_order_new_advertiser_restrictions() -> None:
    """Enforce NEW advertiser restrictions."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    user_id = _seed_advertiser(user_repo, advertiser_repo, UserStatus.ACTIVE)

    service = OrderService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
    )

    with pytest.raises(OrderCreationError):
        service.create_order(
            advertiser_id=user_id,
            product_link="https://example.com",
            offer_text="Offer",
            ugc_requirements=None,
            barter_description="Barter",
            price=1000.0,
            bloggers_needed=3,
        )

    with pytest.raises(OrderCreationError):
        service.create_order(
            advertiser_id=user_id,
            product_link="https://example.com",
            offer_text="Offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=20,
        )


def test_create_order_validation_errors() -> None:
    """Validate required fields and price."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    user_id = _seed_advertiser(user_repo, advertiser_repo, UserStatus.ACTIVE)

    service = OrderService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
    )

    with pytest.raises(OrderCreationError):
        service.create_order(
            advertiser_id=user_id,
            product_link="",
            offer_text="Offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
        )

    with pytest.raises(OrderCreationError):
        service.create_order(
            advertiser_id=user_id,
            product_link="https://example.com",
            offer_text="",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
        )

    with pytest.raises(OrderCreationError):
        service.create_order(
            advertiser_id=user_id,
            product_link="https://example.com",
            offer_text="Offer",
            ugc_requirements=None,
            barter_description=None,
            price=0.0,
            bloggers_needed=3,
        )

    with pytest.raises(OrderCreationError):
        service.create_order(
            advertiser_id=user_id,
            product_link="https://example.com",
            offer_text="Offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=7,
        )


def test_create_order_requires_advertiser_profile() -> None:
    """Reject users without advertiser profile."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    user_id = _seed_advertiser(user_repo, advertiser_repo, UserStatus.ACTIVE)
    advertiser_repo.profiles.clear()

    service = OrderService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
    )
    with pytest.raises(OrderCreationError):
        service.create_order(
            advertiser_id=user_id,
            product_link="https://example.com",
            offer_text="Offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
        )


def test_create_order_blocked_user() -> None:
    """Reject order creation for blocked users."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    user_id = _seed_advertiser(user_repo, advertiser_repo, UserStatus.BLOCKED)

    service = OrderService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
    )

    with pytest.raises(OrderCreationError, match="Blocked users"):
        service.create_order(
            advertiser_id=user_id,
            product_link="https://example.com",
            offer_text="Offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
        )


def test_create_order_paused_user() -> None:
    """Reject order creation for paused users."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    user_id = _seed_advertiser(user_repo, advertiser_repo, UserStatus.PAUSE)

    service = OrderService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
    )

    with pytest.raises(OrderCreationError, match="Paused users"):
        service.create_order(
            advertiser_id=user_id,
            product_link="https://example.com",
            offer_text="Offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
        )

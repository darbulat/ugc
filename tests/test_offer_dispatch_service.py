"""Tests for offer dispatch service."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.services.offer_dispatch_service import OfferDispatchService
from ugc_bot.domain.entities import BloggerProfile, Order, User
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    OrderStatus,
    UserRole,
    UserStatus,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryOrderRepository,
    InMemoryUserRepository,
)


def test_dispatch_selects_confirmed_bloggers() -> None:
    """Dispatch returns only confirmed active bloggers."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()

    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000600"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000601"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    order_repo.save(order)

    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000602"),
        external_id="100",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        role=UserRole.BLOGGER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(blogger)
    blogger_repo.save(
        BloggerProfile(
            user_id=blogger.user_id,
            instagram_url="https://instagram.com/blogger",
            confirmed=True,
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        )
    )

    assert service.dispatch(order.order_id) == [blogger]


def test_dispatch_requires_active_order() -> None:
    """Dispatch fails for inactive orders."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()

    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000610"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000611"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    order_repo.save(order)

    with pytest.raises(OrderCreationError):
        service.dispatch(order.order_id)


def test_dispatch_skips_ineligible_bloggers() -> None:
    """Skip bloggers with missing user or invalid role/status."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()

    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000620"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000621"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    order_repo.save(order)

    blogger_repo.save(
        BloggerProfile(
            user_id=UUID("00000000-0000-0000-0000-000000000622"),
            instagram_url="https://instagram.com/ghost",
            confirmed=True,
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        )
    )

    user_repo.save(
        User(
            user_id=UUID("00000000-0000-0000-0000-000000000623"),
            external_id="101",
            messenger_type=MessengerType.TELEGRAM,
            username="advertiser",
            role=UserRole.ADVERTISER,
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
        )
    )
    blogger_repo.save(
        BloggerProfile(
            user_id=UUID("00000000-0000-0000-0000-000000000623"),
            instagram_url="https://instagram.com/advertiser",
            confirmed=True,
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        )
    )

    assert service.dispatch(order.order_id) == []


def test_dispatch_no_profiles_returns_empty() -> None:
    """Return empty list when no confirmed profiles."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()

    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000640"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000641"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    order_repo.save(order)

    assert service.dispatch(order.order_id) == []

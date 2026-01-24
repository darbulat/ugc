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
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(blogger)
    blogger_repo.save(
        BloggerProfile(
            user_id=blogger.user_id,
            instagram_url="https://instagram.com/blogger",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        )
    )
    # Update user with confirmed Instagram
    confirmed_blogger = User(
        user_id=blogger.user_id,
        external_id=blogger.external_id,
        messenger_type=blogger.messenger_type,
        username=blogger.username,
        status=blogger.status,
        issue_count=blogger.issue_count,
        created_at=blogger.created_at,
        instagram_url="https://instagram.com/blogger",
        confirmed=True,
    )
    user_repo.save(confirmed_blogger)

    assert service.dispatch(order.order_id) == [confirmed_blogger]


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
    """Skip bloggers with missing user or invalid status."""

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
            status=UserStatus.BLOCKED,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
        )
    )
    blogger_repo.save(
        BloggerProfile(
            user_id=UUID("00000000-0000-0000-0000-000000000623"),
            instagram_url="https://instagram.com/advertiser",
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


def test_dispatch_excludes_order_author() -> None:
    """Do not send order to its author even if they are a confirmed blogger."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()

    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
    )

    advertiser_id = UUID("00000000-0000-0000-0000-000000000650")
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000651"),
        advertiser_id=advertiser_id,
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

    # Advertiser who is also a blogger
    advertiser_blogger = User(
        user_id=advertiser_id,
        external_id="200",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser_blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(advertiser_blogger)
    blogger_repo.save(
        BloggerProfile(
            user_id=advertiser_id,
            instagram_url="https://instagram.com/advertiser",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        )
    )
    # Update advertiser_blogger with confirmed Instagram
    confirmed_advertiser = User(
        user_id=advertiser_blogger.user_id,
        external_id=advertiser_blogger.external_id,
        messenger_type=advertiser_blogger.messenger_type,
        username=advertiser_blogger.username,
        status=advertiser_blogger.status,
        issue_count=advertiser_blogger.issue_count,
        created_at=advertiser_blogger.created_at,
        instagram_url="https://instagram.com/advertiser",
        confirmed=True,
    )
    user_repo.save(confirmed_advertiser)

    # Another blogger
    other_blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000652"),
        external_id="201",
        messenger_type=MessengerType.TELEGRAM,
        username="other_blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(other_blogger)
    blogger_repo.save(
        BloggerProfile(
            user_id=other_blogger.user_id,
            instagram_url="https://instagram.com/other",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        )
    )
    # Update other_blogger with confirmed Instagram
    confirmed_other = User(
        user_id=other_blogger.user_id,
        external_id=other_blogger.external_id,
        messenger_type=other_blogger.messenger_type,
        username=other_blogger.username,
        status=other_blogger.status,
        issue_count=other_blogger.issue_count,
        created_at=other_blogger.created_at,
        instagram_url="https://instagram.com/other",
        confirmed=True,
    )
    user_repo.save(confirmed_other)

    # Should only return other_blogger, not advertiser_blogger
    result = service.dispatch(order.order_id)
    assert len(result) == 1
    assert result[0].user_id == other_blogger.user_id
    assert result[0].user_id != advertiser_id

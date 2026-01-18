"""Tests for repository mapping helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from ugc_bot.domain.entities import BloggerProfile, Order, User
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    OrderStatus,
    UserRole,
    UserStatus,
)
from ugc_bot.infrastructure.db.repositories import (
    _to_blogger_profile_entity,
    _to_blogger_profile_model,
    _to_order_entity,
    _to_order_model,
    _to_user_entity,
    _to_user_model,
)


def test_user_mapping_roundtrip() -> None:
    """Ensure user mapping keeps core attributes."""

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000010"),
        external_id="123",
        messenger_type=MessengerType.TELEGRAM,
        username="alice",
        role=UserRole.BLOGGER,
        status=UserStatus.ACTIVE,
        issue_count=1,
        created_at=datetime.now(timezone.utc),
    )

    model = _to_user_model(user)
    entity = _to_user_entity(model)

    assert entity.external_id == user.external_id
    assert entity.messenger_type == user.messenger_type
    assert entity.role == user.role


def test_blogger_profile_mapping_roundtrip() -> None:
    """Ensure blogger profile mapping keeps core attributes."""

    profile = BloggerProfile(
        user_id=UUID("00000000-0000-0000-0000-000000000011"),
        instagram_url="https://instagram.com/test_user",
        confirmed=False,
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1500.0,
        updated_at=datetime.now(timezone.utc),
    )

    model = _to_blogger_profile_model(profile)
    entity = _to_blogger_profile_entity(model)

    assert entity.instagram_url == profile.instagram_url
    assert entity.audience_gender == profile.audience_gender
    assert entity.price == profile.price


def test_order_mapping_roundtrip() -> None:
    """Ensure order mapping keeps core attributes."""

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000210"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000211"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )

    model = _to_order_model(order)
    entity = _to_order_entity(model)

    assert entity.product_link == order.product_link
    assert entity.bloggers_needed == order.bloggers_needed

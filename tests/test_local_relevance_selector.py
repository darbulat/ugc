"""Tests for local relevance selector."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from ugc_bot.domain.entities import BloggerProfile, Order
from ugc_bot.domain.enums import AudienceGender, OrderStatus
from ugc_bot.infrastructure.llm.local_relevance_selector import (
    LocalBloggerRelevanceSelector,
)


def test_local_relevance_selector_limits() -> None:
    """Return the first profiles up to limit."""

    selector = LocalBloggerRelevanceSelector()
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000950"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000951"),
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
    profiles = [
        BloggerProfile(
            user_id=UUID("00000000-0000-0000-0000-000000000952"),
            instagram_url="https://instagram.com/blogger",
            confirmed=True,
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        ),
        BloggerProfile(
            user_id=UUID("00000000-0000-0000-0000-000000000953"),
            instagram_url="https://instagram.com/blogger2",
            confirmed=True,
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        ),
    ]

    selected = selector.select(order=order, profiles=profiles, limit=1)
    assert selected == [profiles[0].user_id]

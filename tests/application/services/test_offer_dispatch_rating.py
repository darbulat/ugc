"""Rating-aware tests for offer dispatch."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
)
from ugc_bot.domain.entities import BloggerProfile, BloggerRating, Order, User
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    OrderStatus,
    OrderType,
    RaterRole,
    UserStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryBloggerRatingRepository,
    InMemoryInteractionRepository,
    InMemoryOfferDispatchRepository,
    InMemoryOrderRepository,
    InMemoryUserRepository,
)


async def _save_user_with_profile(
    user_repo: InMemoryUserRepository,
    blogger_repo: InMemoryBloggerProfileRepository,
    user_id: UUID,
    telegram_id: str,
) -> None:
    """Create active user and confirmed profile for dispatch tests."""
    await user_repo.save(
        User(
            user_id=user_id,
            telegram_id=telegram_id,
            messenger_type=MessengerType.TELEGRAM,
            username=f"user-{telegram_id}",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
        )
    )
    await blogger_repo.save(
        BloggerProfile(
            user_id=user_id,
            instagram_url=f"https://instagram.com/{telegram_id}",
            confirmed=True,
            city="Moscow",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=datetime.now(timezone.utc),
        )
    )


@pytest.mark.asyncio
async def test_dispatch_sorts_by_rating_desc_and_puts_unrated_last() -> None:
    """Dispatch should sort creators by avg rating descending."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    rating_repo = InMemoryBloggerRatingRepository()
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
        blogger_rating_repo=rating_repo,
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000201"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000202"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    await order_repo.save(order)
    high = UUID("00000000-0000-0000-0000-000000000211")
    low = UUID("00000000-0000-0000-0000-000000000212")
    unrated = UUID("00000000-0000-0000-0000-000000000213")
    await _save_user_with_profile(user_repo, blogger_repo, high, "901")
    await _save_user_with_profile(user_repo, blogger_repo, low, "902")
    await _save_user_with_profile(user_repo, blogger_repo, unrated, "903")
    await rating_repo.save(
        BloggerRating(
            rating_id=UUID("00000000-0000-0000-0000-000000000221"),
            blogger_id=high,
            order_id=UUID("00000000-0000-0000-0000-000000000231"),
            rater_id=order.advertiser_id,
            rater_role=RaterRole.ADVERTISER,
            score=5,
            comment=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    await rating_repo.save(
        BloggerRating(
            rating_id=UUID("00000000-0000-0000-0000-000000000222"),
            blogger_id=low,
            order_id=UUID("00000000-0000-0000-0000-000000000232"),
            rater_id=order.advertiser_id,
            rater_role=RaterRole.ADVERTISER,
            score=3,
            comment=None,
            created_at=datetime.now(timezone.utc),
        )
    )

    result = await service.dispatch(order.order_id)
    assert [u.user_id for u in result] == [high, low, unrated]


@pytest.mark.asyncio
async def test_dispatch_min_rating_filters_low_but_keeps_unrated() -> None:
    """Min rating should filter low-rated users while keeping unrated users."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    rating_repo = InMemoryBloggerRatingRepository()
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
        blogger_rating_repo=rating_repo,
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000301"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000302"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        min_rating=4.0,
    )
    await order_repo.save(order)
    good = UUID("00000000-0000-0000-0000-000000000311")
    bad = UUID("00000000-0000-0000-0000-000000000312")
    unrated = UUID("00000000-0000-0000-0000-000000000313")
    await _save_user_with_profile(user_repo, blogger_repo, good, "911")
    await _save_user_with_profile(user_repo, blogger_repo, bad, "912")
    await _save_user_with_profile(user_repo, blogger_repo, unrated, "913")
    await rating_repo.save(
        BloggerRating(
            rating_id=UUID("00000000-0000-0000-0000-000000000321"),
            blogger_id=good,
            order_id=UUID("00000000-0000-0000-0000-000000000331"),
            rater_id=order.advertiser_id,
            rater_role=RaterRole.ADVERTISER,
            score=5,
            comment=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    await rating_repo.save(
        BloggerRating(
            rating_id=UUID("00000000-0000-0000-0000-000000000322"),
            blogger_id=bad,
            order_id=UUID("00000000-0000-0000-0000-000000000332"),
            rater_id=order.advertiser_id,
            rater_role=RaterRole.ADVERTISER,
            score=2,
            comment=None,
            created_at=datetime.now(timezone.utc),
        )
    )

    result = await service.dispatch(order.order_id)
    assert [u.user_id for u in result] == [good, unrated]

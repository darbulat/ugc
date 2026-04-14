"""Integration tests for SqlAlchemyBloggerRatingRepository."""

from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError

from ugc_bot.domain.entities import BloggerRating, Order, User
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    OrderType,
    RaterRole,
    UserStatus,
)
from ugc_bot.infrastructure.db.repositories.orders import (
    SqlAlchemyOrderRepository,
)
from ugc_bot.infrastructure.db.repositories.ratings import (
    SqlAlchemyBloggerRatingRepository,
)
from ugc_bot.infrastructure.db.repositories.user import SqlAlchemyUserRepository


async def _seed_user(
    repo: SqlAlchemyUserRepository, user_id: UUID, telegram_id: str
) -> None:
    """Insert minimal user row for FK references."""
    await repo.save(
        User(
            user_id=user_id,
            telegram_id=telegram_id,
            messenger_type=MessengerType.TELEGRAM,
            username=f"user-{str(user_id)[:8]}",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
        )
    )


async def _seed_order(
    repo: SqlAlchemyOrderRepository,
    order_id: UUID,
    advertiser_id: UUID,
) -> None:
    """Insert minimal active order row for FK references."""
    await repo.save(
        Order(
            order_id=order_id,
            advertiser_id=advertiser_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com/product",
            offer_text="Offer",
            barter_description=None,
            price=1000.0,
            bloggers_needed=1,
            status=OrderStatus.ACTIVE,
            created_at=datetime.now(timezone.utc),
        )
    )


@pytest.mark.asyncio
async def test_blogger_rating_repository_save_and_avg(session_factory) -> None:
    """Repository should persist ratings and calculate average correctly."""
    user_repo = SqlAlchemyUserRepository(session_factory=session_factory)
    order_repo = SqlAlchemyOrderRepository(session_factory=session_factory)
    repo = SqlAlchemyBloggerRatingRepository(session_factory=session_factory)
    blogger_id = UUID("00000000-0000-0000-0000-000000000401")
    advertiser_id = UUID("00000000-0000-0000-0000-000000000402")
    manager_id = UUID("00000000-0000-0000-0000-000000000403")
    order_id_1 = UUID("00000000-0000-0000-0000-000000000411")
    order_id_2 = UUID("00000000-0000-0000-0000-000000000412")

    await _seed_user(user_repo, blogger_id, "4001")
    await _seed_user(user_repo, advertiser_id, "4002")
    await _seed_user(user_repo, manager_id, "4003")
    await _seed_order(order_repo, order_id_1, advertiser_id)
    await _seed_order(order_repo, order_id_2, advertiser_id)

    await repo.save(
        BloggerRating(
            rating_id=UUID("00000000-0000-0000-0000-000000000421"),
            blogger_id=blogger_id,
            order_id=order_id_1,
            rater_id=advertiser_id,
            rater_role=RaterRole.ADVERTISER,
            score=5,
            comment="Great",
            created_at=datetime.now(timezone.utc),
        )
    )
    await repo.save(
        BloggerRating(
            rating_id=UUID("00000000-0000-0000-0000-000000000422"),
            blogger_id=blogger_id,
            order_id=order_id_2,
            rater_id=manager_id,
            rater_role=RaterRole.MANAGER,
            score=3,
            comment="Normal",
            created_at=datetime.now(timezone.utc),
        )
    )

    avg = await repo.get_avg_rating(blogger_id)
    assert avg == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_blogger_rating_unique_constraint(session_factory) -> None:
    """DB should enforce one rating per blogger+order pair."""
    user_repo = SqlAlchemyUserRepository(session_factory=session_factory)
    order_repo = SqlAlchemyOrderRepository(session_factory=session_factory)
    repo = SqlAlchemyBloggerRatingRepository(session_factory=session_factory)
    blogger_id = UUID("00000000-0000-0000-0000-000000000501")
    advertiser_id = UUID("00000000-0000-0000-0000-000000000502")
    order_id = UUID("00000000-0000-0000-0000-000000000511")

    await _seed_user(user_repo, blogger_id, "5001")
    await _seed_user(user_repo, advertiser_id, "5002")
    await _seed_order(order_repo, order_id, advertiser_id)

    rating_1 = BloggerRating(
        rating_id=UUID("00000000-0000-0000-0000-000000000521"),
        blogger_id=blogger_id,
        order_id=order_id,
        rater_id=advertiser_id,
        rater_role=RaterRole.ADVERTISER,
        score=5,
        comment=None,
        created_at=datetime.now(timezone.utc),
    )
    rating_2 = BloggerRating(
        rating_id=UUID("00000000-0000-0000-0000-000000000522"),
        blogger_id=blogger_id,
        order_id=order_id,
        rater_id=advertiser_id,
        rater_role=RaterRole.ADVERTISER,
        score=4,
        comment=None,
        created_at=datetime.now(timezone.utc),
    )

    await repo.save(rating_1)

    with pytest.raises(IntegrityError):
        await repo.save(rating_2)

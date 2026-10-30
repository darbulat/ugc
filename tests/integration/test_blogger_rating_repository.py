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
    """DB should enforce one rating per creator/order/evaluator."""
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


@pytest.mark.asyncio
async def test_effective_rating_preserves_authored_history(
    session_factory,
) -> None:
    """Advertiser wins a pair; other orders retain newest manager fallback."""
    from dataclasses import replace
    from datetime import timedelta
    from uuid import uuid4

    user_repo = SqlAlchemyUserRepository(session_factory=session_factory)
    order_repo = SqlAlchemyOrderRepository(session_factory=session_factory)
    repo = SqlAlchemyBloggerRatingRepository(session_factory=session_factory)
    blogger, owner, manager, admin, order, other_order = (
        uuid4() for _ in range(6)
    )
    for user in (blogger, owner, manager, admin):
        await _seed_user(user_repo, user, str(user))
    for item in (order, other_order):
        await _seed_order(order_repo, item, owner)
    now = datetime.now(timezone.utc)

    def rating(order_id, actor, role, score, at):
        return BloggerRating(
            uuid4(), blogger, order_id, actor, role, score, None, at
        )

    historical = rating(order, manager, RaterRole.MANAGER, 1, now)
    advertiser = rating(
        order, owner, RaterRole.ADVERTISER, 5, now - timedelta(days=1)
    )
    for row in (
        historical,
        advertiser,
        rating(order, admin, RaterRole.ADMIN, 2, now + timedelta(seconds=1)),
        rating(other_order, manager, RaterRole.MANAGER, 1, now),
        rating(
            other_order, admin, RaterRole.ADMIN, 3, now + timedelta(seconds=1)
        ),
    ):
        await repo.save(row)
    assert (
        await repo.get_by_blogger_and_order(blogger, order)
    ).rating_id == advertiser.rating_id
    assert (
        await repo.get_by_blogger_and_order(blogger, other_order)
    ).score == 3
    assert (
        await repo.get_by_blogger_order_and_rater(blogger, order, manager)
    ).rating_id == historical.rating_id
    assert await repo.get_avg_rating(blogger) == 4
    assert await repo.get_avg_ratings_for_bloggers([blogger, uuid4()]) == {
        blogger: 4
    }
    await repo.save(
        replace(advertiser, score=1, updated_at=now + timedelta(seconds=2))
    )
    assert await repo.get_avg_rating(blogger) == 2
    assert len(await repo.list_by_blogger(blogger)) == 5

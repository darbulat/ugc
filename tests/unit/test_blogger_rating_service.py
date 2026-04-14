"""Unit tests for BloggerRatingService."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.errors import (
    InvalidRatingScoreError,
    RatingAlreadyExistsError,
)
from ugc_bot.application.services.blogger_rating_service import (
    BloggerRatingService,
)
from ugc_bot.domain.enums import RaterRole
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerRatingRepository,
)


@pytest.mark.asyncio
async def test_rate_blogger_saves_valid_rating() -> None:
    """rate_blogger should persist a valid rating."""
    repo = InMemoryBloggerRatingRepository()
    service = BloggerRatingService(rating_repo=repo)

    rating = await service.rate_blogger(
        blogger_id=UUID("00000000-0000-0000-0000-000000000101"),
        order_id=UUID("00000000-0000-0000-0000-000000000102"),
        rater_id=UUID("00000000-0000-0000-0000-000000000103"),
        rater_role=RaterRole.ADVERTISER,
        score=5,
        comment="Great collaboration",
    )

    assert rating.score == 5
    assert rating.comment == "Great collaboration"
    assert rating.created_at <= datetime.now(timezone.utc)
    assert len(repo.ratings) == 1


@pytest.mark.asyncio
async def test_rate_blogger_rejects_duplicate_for_same_order() -> None:
    """rate_blogger should reject duplicate blogger+order rating."""
    repo = InMemoryBloggerRatingRepository()
    service = BloggerRatingService(rating_repo=repo)
    blogger_id = UUID("00000000-0000-0000-0000-000000000111")
    order_id = UUID("00000000-0000-0000-0000-000000000112")

    await service.rate_blogger(
        blogger_id=blogger_id,
        order_id=order_id,
        rater_id=UUID("00000000-0000-0000-0000-000000000113"),
        rater_role=RaterRole.MANAGER,
        score=4,
    )

    with pytest.raises(RatingAlreadyExistsError):
        await service.rate_blogger(
            blogger_id=blogger_id,
            order_id=order_id,
            rater_id=UUID("00000000-0000-0000-0000-000000000114"),
            rater_role=RaterRole.ADMIN,
            score=5,
        )


@pytest.mark.asyncio
async def test_rate_blogger_rejects_invalid_score() -> None:
    """rate_blogger should fail when score is outside 1..5."""
    repo = InMemoryBloggerRatingRepository()
    service = BloggerRatingService(rating_repo=repo)

    with pytest.raises(InvalidRatingScoreError):
        await service.rate_blogger(
            blogger_id=UUID("00000000-0000-0000-0000-000000000121"),
            order_id=UUID("00000000-0000-0000-0000-000000000122"),
            rater_id=UUID("00000000-0000-0000-0000-000000000123"),
            rater_role=RaterRole.ADVERTISER,
            score=0,
        )

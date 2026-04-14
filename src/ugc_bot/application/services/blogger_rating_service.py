"""Service for blogger ratings."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from ugc_bot.application.errors import (
    InvalidRatingScoreError,
    RatingAlreadyExistsError,
)
from ugc_bot.application.ports import (
    BloggerRatingRepository,
    TransactionManager,
)
from ugc_bot.domain.entities import BloggerRating
from ugc_bot.domain.enums import RaterRole
from ugc_bot.infrastructure.db.session import with_optional_tx


@dataclass(slots=True)
class BloggerRatingService:
    """Handle blogger rating creation and read access."""

    rating_repo: BloggerRatingRepository
    transaction_manager: TransactionManager | None = None

    async def rate_blogger(
        self,
        blogger_id: UUID,
        order_id: UUID,
        rater_id: UUID,
        rater_role: RaterRole,
        score: int,
        comment: str | None = None,
        session: object | None = None,
    ) -> BloggerRating:
        """Create a rating for a blogger and enforce uniqueness per order."""
        if score < 1 or score > 5:
            raise InvalidRatingScoreError("Score must be in range [1, 5].")

        async def _run(sess: object | None) -> BloggerRating:
            existing = await self.rating_repo.get_by_blogger_and_order(
                blogger_id=blogger_id,
                order_id=order_id,
                session=sess,
            )
            if existing is not None:
                raise RatingAlreadyExistsError(
                    "Rating already exists for blogger and order."
                )
            rating = BloggerRating(
                rating_id=uuid4(),
                blogger_id=blogger_id,
                order_id=order_id,
                rater_id=rater_id,
                rater_role=rater_role,
                score=score,
                comment=comment,
                created_at=datetime.now(timezone.utc),
                updated_at=None,
            )
            await self.rating_repo.save(rating, session=sess)
            return rating

        if session is not None:
            return await _run(session)
        return await with_optional_tx(self.transaction_manager, _run)

    async def get_blogger_avg_rating(
        self, blogger_id: UUID, session: object | None = None
    ) -> float | None:
        """Return average blogger rating or None when there are no ratings."""
        if session is not None:
            return await self.rating_repo.get_avg_rating(
                blogger_id, session=session
            )

        async def _run(sess: object | None) -> float | None:
            return await self.rating_repo.get_avg_rating(
                blogger_id, session=sess
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def get_blogger_ratings(
        self, blogger_id: UUID, session: object | None = None
    ) -> list[BloggerRating]:
        """Return blogger ratings sorted newest first."""
        if session is not None:
            return await self.rating_repo.list_by_blogger(
                blogger_id, session=session
            )

        async def _run(sess: object | None) -> list[BloggerRating]:
            return await self.rating_repo.list_by_blogger(
                blogger_id, session=sess
            )

        return await with_optional_tx(self.transaction_manager, _run)

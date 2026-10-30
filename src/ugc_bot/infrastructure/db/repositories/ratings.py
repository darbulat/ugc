"""SQLAlchemy blogger rating repository."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ugc_bot.application.ports import BloggerRatingRepository
from ugc_bot.domain.entities import BloggerRating
from ugc_bot.domain.enums import RaterRole
from ugc_bot.infrastructure.db.models import BloggerRatingModel
from ugc_bot.infrastructure.db.repositories._shared import _resolve_session


@dataclass(slots=True)
class SqlAlchemyBloggerRatingRepository(BloggerRatingRepository):
    """SQLAlchemy-backed blogger rating repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def save(
        self, rating: BloggerRating, session: object | None = None
    ) -> None:
        """Persist a blogger rating."""
        model = _to_blogger_rating_model(rating)
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            await db_session.merge(model)

    async def get_by_blogger_and_order(
        self,
        blogger_id: UUID,
        order_id: UUID,
        session: object | None = None,
    ) -> BloggerRating | None:
        """Read the effective rating for a creator/order pair."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(BloggerRatingModel)
                .where(
                    BloggerRatingModel.blogger_id == blogger_id,
                    BloggerRatingModel.order_id == order_id,
                )
                .order_by(*_effective_order())
                .limit(1)
            )
            model = exec_result.scalar_one_or_none()
            return _to_blogger_rating_entity(model) if model else None

    async def get_by_blogger_order_and_rater(
        self,
        blogger_id: UUID,
        order_id: UUID,
        rater_id: UUID,
        session: object | None = None,
    ) -> BloggerRating | None:
        """Fetch only the evaluator's own rating for an update."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            model = await db_session.scalar(
                select(BloggerRatingModel).where(
                    BloggerRatingModel.blogger_id == blogger_id,
                    BloggerRatingModel.order_id == order_id,
                    BloggerRatingModel.rater_id == rater_id,
                )
            )
            return _to_blogger_rating_entity(model) if model else None

    async def get_avg_rating(
        self, blogger_id: UUID, session: object | None = None
    ) -> float | None:
        """Average one effective score for each creator/order pair."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            ranked = (
                select(
                    BloggerRatingModel.score,
                    func.row_number()
                    .over(
                        partition_by=BloggerRatingModel.order_id,
                        order_by=_effective_order(),
                    )
                    .label("position"),
                )
                .where(BloggerRatingModel.blogger_id == blogger_id)
                .subquery()
            )
            avg = await db_session.scalar(
                select(func.avg(ranked.c.score)).where(ranked.c.position == 1)
            )
            return float(avg) if avg is not None else None

    async def list_by_blogger(
        self, blogger_id: UUID, session: object | None = None
    ) -> list[BloggerRating]:
        """Return blogger ratings sorted newest first."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(BloggerRatingModel)
                .where(BloggerRatingModel.blogger_id == blogger_id)
                .order_by(
                    BloggerRatingModel.created_at.desc(),
                    BloggerRatingModel.rating_id.desc(),
                )
            )
            return [
                _to_blogger_rating_entity(item)
                for item in exec_result.scalars()
            ]

    async def get_avg_ratings_for_bloggers(
        self,
        blogger_ids: list[UUID],
        session: object | None = None,
    ) -> dict[UUID, float]:
        """Return average ratings for a list of blogger ids."""
        if not blogger_ids:
            return {}
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            ranked = (
                select(
                    BloggerRatingModel.blogger_id,
                    BloggerRatingModel.score,
                    func.row_number()
                    .over(
                        partition_by=(
                            BloggerRatingModel.blogger_id,
                            BloggerRatingModel.order_id,
                        ),
                        order_by=_effective_order(),
                    )
                    .label("position"),
                )
                .where(BloggerRatingModel.blogger_id.in_(blogger_ids))
                .subquery()
            )
            rows = (
                await db_session.execute(
                    select(ranked.c.blogger_id, func.avg(ranked.c.score))
                    .where(ranked.c.position == 1)
                    .group_by(ranked.c.blogger_id)
                )
            ).all()
            return {
                blogger_id: float(avg_score)
                for blogger_id, avg_score in rows
                if avg_score is not None
            }


def _effective_order():
    """Prefer advertiser, then latest write, then stable identity."""
    return (
        case(
            (BloggerRatingModel.rater_role == RaterRole.ADVERTISER, 0), else_=1
        ),
        func.coalesce(
            BloggerRatingModel.updated_at, BloggerRatingModel.created_at
        ).desc(),
        BloggerRatingModel.created_at.desc(),
        BloggerRatingModel.rating_id.desc(),
    )


def _to_blogger_rating_entity(model: BloggerRatingModel) -> BloggerRating:
    """Map blogger rating ORM model to domain entity."""
    return BloggerRating(
        rating_id=model.rating_id,
        blogger_id=model.blogger_id,
        order_id=model.order_id,
        rater_id=model.rater_id,
        rater_role=model.rater_role,
        score=model.score,
        comment=model.comment,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _to_blogger_rating_model(rating: BloggerRating) -> BloggerRatingModel:
    """Map blogger rating domain entity to ORM model."""
    return BloggerRatingModel(
        rating_id=rating.rating_id,
        blogger_id=rating.blogger_id,
        order_id=rating.order_id,
        rater_id=rating.rater_id,
        rater_role=rating.rater_role,
        score=rating.score,
        comment=rating.comment,
        created_at=rating.created_at,
        updated_at=rating.updated_at,
    )

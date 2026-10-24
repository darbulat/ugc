"""SQLAlchemy Instagram verification and stats repositories."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, cast
from uuid import UUID

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ugc_bot.application.legacy_link_ports import LegacySqlParticipant
from ugc_bot.application.ports import (
    InstagramStatsRepository,
    InstagramVerificationRepository,
)
from ugc_bot.domain.entities import InstagramStats, InstagramVerificationCode
from ugc_bot.infrastructure.db.models import (
    InstagramStatsModel,
    InstagramVerificationCodeModel,
)
from ugc_bot.infrastructure.db.repositories._shared import _resolve_session


@dataclass(slots=True)
class SqlAlchemyInstagramVerificationRepository(
    InstagramVerificationRepository, LegacySqlParticipant
):
    """SQLAlchemy-backed Instagram verification repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def current_legacy_code(self, code_id, user_id, code, *, session):
        if (
            not isinstance(session, AsyncSession)
            or not session.in_transaction()
        ):
            return None
        model = await session.scalar(
            select(InstagramVerificationCodeModel)
            .where(
                InstagramVerificationCodeModel.code_id == code_id,
                InstagramVerificationCodeModel.user_id == user_id,
                InstagramVerificationCodeModel.code == code,
                InstagramVerificationCodeModel.used.is_(False),
                InstagramVerificationCodeModel.expires_at
                > datetime.now(timezone.utc),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            model is None
            or model.used
            or model.expires_at <= datetime.now(timezone.utc)
        ):
            return None
        return _to_verification_entity(model)

    async def save(
        self, code: InstagramVerificationCode, session: object | None = None
    ) -> None:
        """Persist verification code."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            model = _to_verification_model(code)
            await db_session.merge(model)

    async def get_valid_code(
        self, user_id: UUID, code: str, session: object | None = None
    ) -> Optional[InstagramVerificationCode]:
        """Fetch a valid, unexpired verification code."""
        now = datetime.now(timezone.utc)
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(InstagramVerificationCodeModel).where(
                    InstagramVerificationCodeModel.user_id == user_id,
                    InstagramVerificationCodeModel.code == code,
                    InstagramVerificationCodeModel.used.is_(False),
                    InstagramVerificationCodeModel.expires_at > now,
                )
            )
            result = exec_result.scalar_one_or_none()
            if result is None:
                return None
            if result.used or result.expires_at <= now:
                return None  # defensive: query already filters
            if result.code != code or result.user_id != user_id:
                return None
            return _to_verification_entity(result)

    async def mark_used(
        self, code_id: UUID, session: object | None = None
    ) -> None:
        """Mark verification code as used."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            model = await db_session.get(
                InstagramVerificationCodeModel, code_id
            )
            if model is None:
                return
            model.used = True

    async def get_valid_code_by_code(
        self, code: str, session: object | None = None
    ) -> Optional[InstagramVerificationCode]:
        """Fetch a valid, unexpired verification code by code string."""
        now = datetime.now(timezone.utc)
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(InstagramVerificationCodeModel).where(
                    InstagramVerificationCodeModel.code == code,
                    InstagramVerificationCodeModel.used.is_(False),
                    InstagramVerificationCodeModel.expires_at > now,
                )
            )
            result = exec_result.scalar_one_or_none()
            if result is None:
                return None
            if result.used or result.expires_at <= now:
                return None
            return _to_verification_entity(result)


@dataclass(slots=True)
class SqlAlchemyInstagramStatsRepository(InstagramStatsRepository):
    """SQLAlchemy-backed Instagram stats repository (Rapid API results)."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get_by_user_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[InstagramStats]:
        """Fetch Instagram stats by user id."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(InstagramStatsModel).where(
                    InstagramStatsModel.user_id == user_id
                )
            )
            result = exec_result.scalar_one_or_none()
            return _to_instagram_stats_entity(result) if result else None

    async def get_by_user_ids(
        self,
        user_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, InstagramStats]:
        """Fetch Instagram stats by user IDs in one query."""
        if not user_ids:
            return {}
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(InstagramStatsModel).where(
                    InstagramStatsModel.user_id.in_(user_ids)
                )
            )
            rows = exec_result.scalars().all()
            return {
                row.user_id: _to_instagram_stats_entity(row) for row in rows
            }

    async def save(
        self, stats: InstagramStats, session: object | None = None
    ) -> None:
        """Persist or update Instagram stats (upsert by user_id)."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            model = _to_instagram_stats_model(stats)
            await db_session.merge(model)

    async def touch_fetched_at(
        self,
        user_id: UUID,
        fetched_at: datetime,
        session: object | None = None,
    ) -> None:
        """Update only fetched_at; insert minimal row if absent."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            result = cast(
                CursorResult,
                await db_session.execute(
                    update(InstagramStatsModel)
                    .where(InstagramStatsModel.user_id == user_id)
                    .values(fetched_at=fetched_at)
                ),
            )
            if result.rowcount == 0:
                db_session.add(
                    InstagramStatsModel(
                        user_id=user_id,
                        raw_response={},
                        fetched_at=fetched_at,
                    )
                )
                await db_session.flush()


def _to_verification_entity(
    model: InstagramVerificationCodeModel,
) -> InstagramVerificationCode:
    """Map verification ORM model to domain entity."""
    return InstagramVerificationCode(
        code_id=model.code_id,
        user_id=model.user_id,
        code=model.code,
        expires_at=model.expires_at,
        used=model.used,
        created_at=model.created_at,
        link_max_id=model.link_max_id,
        link_max_chat_id=model.link_max_chat_id,
        link_username=model.link_username,
        link_phone=model.link_phone,
    )


def _to_verification_model(
    code: InstagramVerificationCode,
) -> InstagramVerificationCodeModel:
    """Map domain verification entity to ORM model."""
    return InstagramVerificationCodeModel(
        code_id=code.code_id,
        user_id=code.user_id,
        code=code.code,
        expires_at=code.expires_at,
        used=code.used,
        created_at=code.created_at,
        link_max_id=code.link_max_id,
        link_max_chat_id=code.link_max_chat_id,
        link_username=code.link_username,
        link_phone=code.link_phone,
    )


def _to_instagram_stats_entity(model: InstagramStatsModel) -> InstagramStats:
    """Map Instagram stats ORM model to domain entity."""
    return InstagramStats(
        user_id=model.user_id,
        raw_response=model.raw_response,
        fetched_at=model.fetched_at,
        followers_count=model.followers_count,
        follows_count=model.follows_count,
        media_count=model.media_count,
        instagram_username=model.instagram_username,
        biography=model.biography,
        provider=model.provider,
        instagram_id=model.instagram_id,
        full_name=model.full_name,
        is_professional_account=model.is_professional_account,
        is_business_account=model.is_business_account,
        category_name=model.category_name,
        external_url=model.external_url,
        avg_likes=model.avg_likes,
        avg_comments=model.avg_comments,
        avg_video_views=model.avg_video_views,
        engagement_rate=model.engagement_rate,
        posting_frequency_days=model.posting_frequency_days,
        total_video_count=model.total_video_count,
        total_photo_count=model.total_photo_count,
        video_ratio=model.video_ratio,
        followers_to_follows_ratio=model.followers_to_follows_ratio,
        comments_to_likes_ratio=model.comments_to_likes_ratio,
    )


def _to_instagram_stats_model(stats: InstagramStats) -> InstagramStatsModel:
    """Map domain Instagram stats entity to ORM model."""
    return InstagramStatsModel(
        user_id=stats.user_id,
        raw_response=stats.raw_response,
        fetched_at=stats.fetched_at,
        followers_count=stats.followers_count,
        follows_count=stats.follows_count,
        media_count=stats.media_count,
        instagram_username=stats.instagram_username,
        biography=stats.biography,
        provider=stats.provider,
        instagram_id=stats.instagram_id,
        full_name=stats.full_name,
        is_professional_account=stats.is_professional_account,
        is_business_account=stats.is_business_account,
        category_name=stats.category_name,
        external_url=stats.external_url,
        avg_likes=stats.avg_likes,
        avg_comments=stats.avg_comments,
        avg_video_views=stats.avg_video_views,
        engagement_rate=stats.engagement_rate,
        posting_frequency_days=stats.posting_frequency_days,
        total_video_count=stats.total_video_count,
        total_photo_count=stats.total_photo_count,
        video_ratio=stats.video_ratio,
        followers_to_follows_ratio=stats.followers_to_follows_ratio,
        comments_to_likes_ratio=stats.comments_to_likes_ratio,
    )

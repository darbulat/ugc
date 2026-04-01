"""SQLAlchemy blogger and advertiser profile repositories."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from geoalchemy2.elements import WKTElement
from geoalchemy2.functions import ST_Intersects
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    BloggerProfileRepository,
)
from ugc_bot.domain.entities import AdvertiserProfile, BloggerProfile
from ugc_bot.domain.enums import BloggerGender, WorkFormat
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    InstagramStatsModel,
)
from ugc_bot.infrastructure.db.repositories._shared import (
    _geometry_to_wkt,
    _require_session,
    _resolve_session,
    _wkt_to_geometry_element,
)


@dataclass(slots=True)
class SqlAlchemyBloggerProfileRepository(BloggerProfileRepository):
    """SQLAlchemy-backed blogger profile repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get_by_user_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[BloggerProfile]:
        """Fetch blogger profile by user id."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(BloggerProfileModel).where(
                    BloggerProfileModel.user_id == user_id
                )
            )
            result = exec_result.scalar_one_or_none()
            return _to_blogger_profile_entity(result) if result else None

    async def get_by_user_ids(
        self,
        user_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, BloggerProfile]:
        """Fetch blogger profiles by user IDs in one query."""
        if not user_ids:
            return {}
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(BloggerProfileModel).where(
                    BloggerProfileModel.user_id.in_(user_ids)
                )
            )
            rows = exec_result.scalars().all()
            return {
                row.user_id: _to_blogger_profile_entity(row) for row in rows
            }

    async def get_by_instagram_url(
        self, instagram_url: str, session: object | None = None
    ) -> Optional[BloggerProfile]:
        """Fetch blogger profile by Instagram URL."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(BloggerProfileModel).where(
                    BloggerProfileModel.instagram_url == instagram_url
                )
            )
            result = exec_result.scalar_one_or_none()
            return _to_blogger_profile_entity(result) if result else None

    async def get_by_instagram_username(
        self, username: str, session: object | None = None
    ) -> Optional[BloggerProfile]:
        """Fetch blogger profile by Instagram username (case-insensitive)."""
        pattern = f"%instagram.com/{username.lower().strip('/')}"
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(BloggerProfileModel).where(
                    func.lower(BloggerProfileModel.instagram_url).like(pattern)
                )
            )
            result = exec_result.scalar_one_or_none()
            return _to_blogger_profile_entity(result) if result else None

    async def save(
        self, profile: BloggerProfile, session: object | None = None
    ) -> None:
        """Persist blogger profile."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            model = _to_blogger_profile_model(profile)
            await db_session.merge(model)

    async def list_confirmed_user_ids(
        self,
        session: object | None = None,
        location_geometry_wkt: Optional[str] = None,
    ) -> list[UUID]:
        """List confirmed blogger user ids.

        When location_geometry_wkt is set (PostgreSQL only), only return
        bloggers whose location_geometry intersects the order geometry.
        """
        import logging

        logger = logging.getLogger(__name__)

        db_session = _require_session(
            session if isinstance(session, AsyncSession) else None
        )
        stmt = select(BloggerProfileModel.user_id).where(
            BloggerProfileModel.confirmed.is_(True)
        )
        if location_geometry_wkt and location_geometry_wkt.strip():
            try:
                bind = db_session.sync_session.get_bind()
                if (
                    getattr(bind, "dialect", None)
                    and getattr(bind.dialect, "name", None) == "postgresql"
                ):
                    order_geom = WKTElement(
                        location_geometry_wkt.strip(), srid=4326
                    )
                    stmt = stmt.where(
                        BloggerProfileModel.location_geometry.isnot(None),
                        ST_Intersects(
                            BloggerProfileModel.location_geometry,
                            order_geom,
                        ),
                    )
            except AttributeError:
                pass
            except Exception as e:
                wkt_preview = (
                    (location_geometry_wkt or "")[:100]
                    if location_geometry_wkt
                    else ""
                )
                logger.warning(
                    "Invalid order location_geometry WKT, returning no "
                    "bloggers: %s",
                    e,
                    extra={"wkt_preview": wkt_preview},
                )
                return []
        exec_result = await db_session.execute(stmt)
        results = exec_result.scalars()
        return list(results)

    async def list_confirmed_with_instagram_id(
        self,
        limit: int,
        offset: int = 0,
        stats_older_than: Optional[datetime] = None,
        session: object | None = None,
    ) -> list[BloggerProfile]:
        """List confirmed profiles with non-empty instagram_user_id.

        When stats_older_than is set, only profiles with no instagram_stats
        row or instagram_stats.fetched_at < stats_older_than are returned.
        """
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            base_conditions = (
                BloggerProfileModel.confirmed.is_(True),
                BloggerProfileModel.instagram_user_id.isnot(None),
                BloggerProfileModel.instagram_user_id != "",
            )
            if stats_older_than is None:
                stmt = (
                    select(BloggerProfileModel)
                    .where(*base_conditions)
                    .order_by(
                        BloggerProfileModel.instagram_stats_fetched_at.asc().nulls_first(),
                        BloggerProfileModel.user_id,
                    )
                    .limit(limit)
                    .offset(offset)
                )
            else:
                stmt = (
                    select(BloggerProfileModel)
                    .outerjoin(
                        InstagramStatsModel,
                        BloggerProfileModel.user_id
                        == InstagramStatsModel.user_id,
                    )
                    .where(
                        *base_conditions,
                        or_(
                            InstagramStatsModel.fetched_at.is_(None),
                            InstagramStatsModel.fetched_at < stats_older_than,
                        ),
                    )
                    .order_by(
                        InstagramStatsModel.fetched_at.asc().nulls_first(),
                        BloggerProfileModel.user_id,
                    )
                    .limit(limit)
                    .offset(offset)
                )
            result = await db_session.execute(stmt)
            rows = result.scalars().all()
            return [_to_blogger_profile_entity(row) for row in rows]


@dataclass(slots=True)
class SqlAlchemyAdvertiserProfileRepository(AdvertiserProfileRepository):
    """SQLAlchemy-backed advertiser profile repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get_by_user_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[AdvertiserProfile]:
        """Fetch advertiser profile by user id."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(AdvertiserProfileModel).where(
                    AdvertiserProfileModel.user_id == user_id
                )
            )
            result = exec_result.scalar_one_or_none()
            return _to_advertiser_profile_entity(result) if result else None

    async def get_by_user_ids(
        self,
        user_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, AdvertiserProfile]:
        """Fetch advertiser profiles by user IDs in one query."""
        if not user_ids:
            return {}
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(AdvertiserProfileModel).where(
                    AdvertiserProfileModel.user_id.in_(user_ids)
                )
            )
            rows = exec_result.scalars().all()
            return {
                row.user_id: _to_advertiser_profile_entity(row) for row in rows
            }

    async def save(
        self, profile: AdvertiserProfile, session: object | None = None
    ) -> None:
        """Persist advertiser profile."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            model = _to_advertiser_profile_model(profile)
            await db_session.merge(model)


def _to_blogger_profile_entity(
    model: BloggerProfileModel,
) -> BloggerProfile:
    """Map blogger profile ORM model to domain entity."""
    work_format = model.work_format
    if isinstance(work_format, str):
        work_format = WorkFormat(work_format)
    blogger_gender = model.blogger_gender
    if blogger_gender is not None and isinstance(blogger_gender, str):
        blogger_gender = BloggerGender(blogger_gender)
    return BloggerProfile(
        user_id=model.user_id,
        instagram_url=model.instagram_url,
        confirmed=model.confirmed,
        city=model.city,
        topics=model.topics,
        audience_gender=model.audience_gender,
        audience_age_min=model.audience_age_min,
        audience_age_max=model.audience_age_max,
        audience_geo=model.audience_geo,
        price=float(model.price),
        barter=model.barter,
        work_format=work_format,
        wanted_to_change_terms_count=model.wanted_to_change_terms_count,
        created_at=model.created_at,
        updated_at=model.updated_at,
        blogger_gender=blogger_gender,
        instagram_user_id=model.instagram_user_id,
        instagram_followers_count=model.instagram_followers_count,
        instagram_username=model.instagram_username,
        instagram_stats_fetched_at=model.instagram_stats_fetched_at,
        birth_date=model.birth_date,
        region=model.region,
        location_geometry=_geometry_to_wkt(model.location_geometry),
        country=model.country,
        currency=model.currency,
        agreement_confirmed_at=model.agreement_confirmed_at,
        phone=model.phone,
    )


def _to_blogger_profile_model(
    profile: BloggerProfile,
) -> BloggerProfileModel:
    """Map domain blogger profile entity to ORM model."""
    return BloggerProfileModel(
        user_id=profile.user_id,
        instagram_url=profile.instagram_url,
        confirmed=profile.confirmed,
        city=profile.city,
        topics=profile.topics,
        audience_gender=profile.audience_gender,
        audience_age_min=profile.audience_age_min,
        audience_age_max=profile.audience_age_max,
        audience_geo=profile.audience_geo,
        price=profile.price,
        barter=profile.barter,
        work_format=profile.work_format,
        wanted_to_change_terms_count=profile.wanted_to_change_terms_count,
        created_at=profile.created_at or profile.updated_at,
        updated_at=profile.updated_at,
        blogger_gender=profile.blogger_gender,
        instagram_user_id=profile.instagram_user_id,
        instagram_followers_count=profile.instagram_followers_count,
        instagram_username=profile.instagram_username,
        instagram_stats_fetched_at=profile.instagram_stats_fetched_at,
        birth_date=profile.birth_date,
        region=profile.region,
        location_geometry=_wkt_to_geometry_element(profile.location_geometry),
        country=profile.country,
        currency=profile.currency,
        agreement_confirmed_at=profile.agreement_confirmed_at,
        phone=profile.phone,
    )


def _to_advertiser_profile_entity(
    model: AdvertiserProfileModel,
) -> AdvertiserProfile:
    """Map advertiser profile ORM model to domain entity."""
    return AdvertiserProfile(
        user_id=model.user_id,
        phone=model.contact,
        brand=model.brand or "",
        site_link=model.site_link,
        city=model.city,
        company_activity=model.company_activity,
        created_at=model.created_at,
        updated_at=model.updated_at,
        agreement_confirmed_at=model.agreement_confirmed_at,
    )


def _to_advertiser_profile_model(
    profile: AdvertiserProfile,
) -> AdvertiserProfileModel:
    """Map domain advertiser profile entity to ORM model."""
    return AdvertiserProfileModel(
        user_id=profile.user_id,
        contact=profile.phone,
        brand=profile.brand or None,
        site_link=profile.site_link,
        city=profile.city,
        company_activity=profile.company_activity,
        created_at=profile.created_at or datetime.now(timezone.utc),
        updated_at=profile.updated_at or datetime.now(timezone.utc),
        agreement_confirmed_at=profile.agreement_confirmed_at,
    )

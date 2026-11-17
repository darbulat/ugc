"""Referrer-scoped reads and follow-ups for the manager's creator directory."""

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.domain.enums import UserStatus
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    ManagerCreatorFollowupModel,
    UserModel,
    UserReferralBindingModel,
)
from ugc_bot.infrastructure.db.repositories.bot_availability import (
    creator_directory_status,
)
from ugc_bot.infrastructure.db.social_models import SocialAccountModel

InstagramFilter = Literal["all", "verified", "unverified", "due"]


def _verified():
    profile = BloggerProfileModel
    return and_(
        profile.confirmed.is_(True),
        func.trim(func.coalesce(profile.instagram_user_id, "")) != "",
    )


def _due():
    remind_at = ManagerCreatorFollowupModel.remind_at
    return and_(~_verified(), or_(remind_at.is_(None), remind_at <= func.now()))


def invited_creator_scope(query, owner_id: UUID):
    """The direct, non-deleted creator memberships shown in the directory."""
    binding = UserReferralBindingModel
    return (
        query.select_from(binding)
        .join(UserModel, UserModel.user_id == binding.referred_user_id)
        .join(
            BloggerProfileModel,
            BloggerProfileModel.user_id == UserModel.user_id,
        )
        .where(
            binding.referrer_user_id == owner_id,
            UserModel.user_id != owner_id,
            UserModel.status != UserStatus.DELETED,
        )
    )


def _invited_creators_query(principal: AuthenticatedMessengerPrincipal):
    """Scope both list and detail to the current native account's referrals."""
    inviter = aliased(UserModel)
    native_id = (
        inviter.telegram_id
        if principal.platform == "telegram"
        else inviter.max_id
    )
    return (
        invited_creator_scope(
            select(
                UserModel,
                BloggerProfileModel,
                creator_directory_status().label("status"),
            ),
            principal.user_id,
        )
        .join(
            inviter,
            inviter.user_id == UserReferralBindingModel.referrer_user_id,
        )
        .where(native_id == principal.external_id)
    )


def _with_followups(query, manager_id: UUID):
    followup = ManagerCreatorFollowupModel
    return query.add_columns(
        _verified().label("instagram_verified"),
        _due().label("followup_due"),
        followup.remind_at,
    ).outerjoin(
        followup,
        and_(
            followup.manager_id == manager_id,
            followup.creator_id == UserModel.user_id,
        ),
    )


def _page(
    query,
    *,
    bot_unavailable: bool,
    offset: int,
    limit: int,
    q: str,
):
    if bot_unavailable:
        query = query.where(
            creator_directory_status() == UserStatus.BOT_BLOCKED
        )
    term = q.strip().removeprefix("@").strip()
    if term:
        query = query.where(
            or_(
                UserModel.username.icontains(term, autoescape=True),
                UserModel.telegram.icontains(term, autoescape=True),
                BloggerProfileModel.instagram_username.icontains(
                    term, autoescape=True
                ),
                BloggerProfileModel.instagram_url.icontains(
                    term, autoescape=True
                ),
                BloggerProfileModel.city.icontains(term, autoescape=True),
            )
        )
    return (
        query.order_by(UserModel.created_at.desc(), UserModel.user_id)
        .offset(offset)
        .limit(limit + 1)
    )


async def invited_creator_page(
    session: AsyncSession,
    principal: AuthenticatedMessengerPrincipal,
    *,
    bot_unavailable: bool,
    offset: int,
    limit: int,
    q: str = "",
):
    query = _page(
        _invited_creators_query(principal),
        bot_unavailable=bot_unavailable,
        offset=offset,
        limit=limit,
        q=q,
    )
    return (await session.execute(query)).all()


async def invited_creator_followup_page(
    session: AsyncSession,
    principal: AuthenticatedMessengerPrincipal,
    *,
    bot_unavailable: bool,
    offset: int,
    limit: int,
    q: str,
    instagram: InstagramFilter,
):
    query = _with_followups(
        _invited_creators_query(principal), principal.user_id
    )
    due_count = await session.scalar(
        select(func.count()).select_from(
            query.where(_due()).with_only_columns(UserModel.user_id).subquery()
        )
    )
    if instagram == "verified":
        query = query.where(_verified())
    elif instagram == "unverified":
        query = query.where(~_verified())
    elif instagram == "due":
        query = query.where(_due())
    query = _page(
        query, bot_unavailable=bot_unavailable, offset=offset, limit=limit, q=q
    )
    rows = (await session.execute(query)).all()
    return rows, due_count or 0


async def invited_creator_card(
    session: AsyncSession,
    principal: AuthenticatedMessengerPrincipal,
    creator_id: UUID,
):
    # The binding and links are read in the same statement.
    social = SocialAccountModel
    query = (
        _with_followups(_invited_creators_query(principal), principal.user_id)
        .add_columns(
            social.platform.label("social_platform"),
            social.url.label("social_url"),
            social.handle.label("social_handle"),
        )
        .outerjoin(social, social.user_id == UserModel.user_id)
        .where(UserModel.user_id == creator_id)
        .order_by(social.platform)
    )
    return (await session.execute(query)).all()


async def postpone_creator_followup(
    session: AsyncSession,
    principal: AuthenticatedMessengerPrincipal,
    creator_id: UUID,
    delay: timedelta,
) -> datetime | None:
    """Postpone contact for an unverified creator in the manager's own base."""
    eligible = (
        _invited_creators_query(principal)
        .with_only_columns(UserModel.user_id)
        .where(UserModel.user_id == creator_id, ~_verified())
        .with_for_update(of=(UserReferralBindingModel, BloggerProfileModel))
    )
    if await session.scalar(eligible) is None:
        return None
    followup = ManagerCreatorFollowupModel
    statement = insert(followup).values(
        manager_id=principal.user_id,
        creator_id=creator_id,
        remind_at=func.now() + delay,
    )
    return await session.scalar(
        statement.on_conflict_do_update(
            index_elements=[followup.manager_id, followup.creator_id],
            set_={"remind_at": statement.excluded.remind_at},
        ).returning(followup.remind_at)
    )

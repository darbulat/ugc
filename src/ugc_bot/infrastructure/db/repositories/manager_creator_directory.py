"""Referrer-scoped reads for the manager's creator directory."""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.domain.enums import UserStatus
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    UserModel,
    UserReferralBindingModel,
)
from ugc_bot.infrastructure.db.repositories.bot_availability import (
    creator_directory_status,
)
from ugc_bot.infrastructure.db.social_models import SocialAccountModel


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


async def invited_creator_page(
    session: AsyncSession,
    principal: AuthenticatedMessengerPrincipal,
    *,
    bot_unavailable: bool,
    offset: int,
    limit: int,
    q: str = "",
):
    query = _invited_creators_query(principal)
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
        await session.execute(
            query.order_by(UserModel.created_at.desc(), UserModel.user_id)
            .offset(offset)
            .limit(limit + 1)
        )
    ).all()


async def invited_creator_card(
    session: AsyncSession,
    principal: AuthenticatedMessengerPrincipal,
    creator_id: UUID,
):
    # The binding and links are read in the same statement.
    social = SocialAccountModel
    query = (
        _invited_creators_query(principal)
        .add_columns(social.platform, social.url, social.handle)
        .outerjoin(social, social.user_id == UserModel.user_id)
        .where(UserModel.user_id == creator_id)
        .order_by(social.platform)
    )
    return (await session.execute(query)).all()

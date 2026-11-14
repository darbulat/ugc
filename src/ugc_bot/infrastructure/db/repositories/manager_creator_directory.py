"""Referrer-scoped reads for the manager's creator directory."""

from uuid import UUID

from sqlalchemy import select
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
from ugc_bot.infrastructure.db.social_models import SocialAccountModel


def _invited_creators_query(principal: AuthenticatedMessengerPrincipal):
    """Scope both list and detail to the current native account's referrals."""
    binding = UserReferralBindingModel
    creator = BloggerProfileModel
    inviter = aliased(UserModel)
    native_id = (
        inviter.telegram_id
        if principal.platform == "telegram"
        else inviter.max_id
    )
    return (
        select(UserModel, creator)
        .select_from(binding)
        .join(inviter, inviter.user_id == binding.referrer_user_id)
        .join(UserModel, UserModel.user_id == binding.referred_user_id)
        .join(creator, creator.user_id == UserModel.user_id)
        .where(
            inviter.user_id == principal.user_id,
            native_id == principal.external_id,
            UserModel.user_id != inviter.user_id,
            UserModel.status != UserStatus.DELETED,
        )
    )


async def invited_creator_page(
    session: AsyncSession,
    principal: AuthenticatedMessengerPrincipal,
    *,
    bot_unavailable: bool,
    offset: int,
    limit: int,
):
    query = _invited_creators_query(principal)
    if bot_unavailable:
        query = query.where(UserModel.status == UserStatus.BOT_BLOCKED)
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

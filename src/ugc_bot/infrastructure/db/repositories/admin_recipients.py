"""Resolve one explicitly named Telegram administrator."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.domain.enums import UserStatus
from ugc_bot.infrastructure.db.models import UserModel


async def active_admin_telegram_address(
    db: AsyncSession, handle: str
) -> str | None:
    addresses = (
        await db.scalars(
            select(UserModel.telegram_id)
            .where(
                func.lower(UserModel.telegram) == handle,
                UserModel.admin.is_(True),
                UserModel.status == UserStatus.ACTIVE,
                UserModel.telegram_id.is_not(None),
            )
            .limit(2)
        )
    ).all()
    return addresses[0] if len(addresses) == 1 else None

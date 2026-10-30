"""SQL attachment authorization and transactional order binding."""

from dataclasses import asdict

import sqlalchemy as sa

from ugc_bot.application.order_image_ports import OrderImage
from ugc_bot.domain.enums import UserStatus
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.order_image_models import IMAGES
from ugc_bot.infrastructure.db.repositories.financial_items import _session


class SqlAlchemyOrderImageRepository:
    async def authorize(self, owner, principal, *, session):
        db = _session(session)
        user = await db.scalar(
            sa.select(UserModel)
            .where(UserModel.user_id == owner)
            .with_for_update(key_share=True)
        )
        if user is None or user.status != UserStatus.ACTIVE:
            return False
        if principal is not None:
            external = (
                user.telegram_id
                if principal.platform == "telegram"
                else user.max_id
            )
            if principal.user_id != owner or external != principal.external_id:
                return False
        return (
            await db.scalar(
                sa.select(AdvertiserProfileModel.user_id).where(
                    AdvertiserProfileModel.user_id == owner
                )
            )
            is not None
        )

    async def save(self, value, *, session):
        await _session(session).execute(
            sa.insert(IMAGES).values(**asdict(value))
        )

    async def get(self, token, *, session):
        result = await _session(session).execute(
            sa.select(IMAGES).where(IMAGES.c.token == token).with_for_update()
        )
        value = result.mappings().first()
        return OrderImage(**value) if value else None

    async def bind(self, token, order_id, *, session):
        db = _session(session)
        image = await self.get(token, session=session)
        owner = await db.scalar(
            sa.select(OrderModel.advertiser_id).where(
                OrderModel.order_id == order_id
            )
        )
        if image is None or owner != image.owner_id:
            raise PermissionError("image_order_owner_required")
        await db.execute(
            sa.update(IMAGES)
            .where(IMAGES.c.token == token)
            .values(order_id=order_id)
        )

    async def expired(self, at, *, session):
        result = await _session(session).execute(
            sa.select(IMAGES)
            .where(IMAGES.c.expires_at <= at, IMAGES.c.order_id.is_(None))
            .with_for_update(skip_locked=True)
            .limit(100)
        )
        return [OrderImage(**value) for value in result.mappings()]

    async def delete(self, token, *, session):
        await _session(session).execute(
            sa.delete(IMAGES).where(
                IMAGES.c.token == token, IMAGES.c.order_id.is_(None)
            )
        )

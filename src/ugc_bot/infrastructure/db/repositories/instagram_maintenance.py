"""Serialize observations with canonical ownership, never with API calls."""

from dataclasses import replace
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.application.instagram_maintenance_ports import ProfileNotice
from ugc_bot.application.notice_delivery_ports import (
    ReceiptCallback,
    ReceiptCard,
)
from ugc_bot.application.ports import InstagramProfileInfo
from ugc_bot.domain.entities import BloggerProfile
from ugc_bot.domain.enums import InteractionStatus, OrderStatus, UserStatus
from ugc_bot.domain.instagram_maintenance import (
    REFRESH_CALLBACK,
    next_failure_count,
    next_profile_notice_at,
)
from ugc_bot.domain.social import SocialPlatform, normalize_social_url
from ugc_bot.infrastructure.db.instagram_maintenance_models import (
    HEALTH,
    NOTICES,
    OBSERVATIONS,
)
from ugc_bot.infrastructure.db.models import (
    InteractionModel,
    ItemAssignmentModel,
    OrderItemModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.profiles import (
    SqlAlchemyBloggerProfileRepository,
)
from ugc_bot.infrastructure.db.social_models import SocialAccountModel


def _db(session: object) -> AsyncSession:
    if not isinstance(session, AsyncSession) or not session.in_transaction():
        raise ValueError("instagram_maintenance_transaction_required")
    return session


class SqlAlchemyInstagramMaintenanceRepository:
    def __init__(
        self,
        profiles: SqlAlchemyBloggerProfileRepository,
        identity_context: str,
    ):
        if not identity_context.strip():
            raise ValueError("instagram_identity_context_required")
        self.profiles, self.context = profiles, identity_context.strip()

    async def _lock_profile(self, user_id: UUID, db: AsyncSession):
        # Same lock order as canonical profile writers and ownership proofs.
        await db.scalar(
            sa.select(UserModel.user_id)
            .where(UserModel.user_id == user_id)
            .with_for_update(key_share=True)
        )
        return await self.profiles.current_legacy_profile(user_id, session=db)

    async def _health(
        self, profile: BloggerProfile, at: datetime, db: AsyncSession
    ) -> dict:
        previous = (
            (
                await db.execute(
                    sa.select(HEALTH)
                    .where(HEALTH.c.user_id == profile.user_id)
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        if previous and previous["meta_id"] == profile.instagram_user_id:
            return dict(previous)
        _, handle = normalize_social_url(
            SocialPlatform.INSTAGRAM, profile.instagram_url
        )
        return dict(
            user_id=profile.user_id,
            meta_id=profile.instagram_user_id,
            id_kind="legacy_meta_id",
            identity_context=self.context,
            handle=handle,
            status="healthy",
            failure_count=0,
            last_failure_at=None,
            last_success_at=None,
            checked_at=at,
            episode=uuid4(),
        )

    async def _save_health(
        self,
        health: dict,
        old_handle: str,
        outcome: str,
        at: datetime,
        db: AsyncSession,
    ) -> None:
        await db.execute(
            insert(HEALTH)
            .values(**health)
            .on_conflict_do_update(
                index_elements=[HEALTH.c.user_id], set_=health
            )
        )
        await db.execute(
            sa.insert(OBSERVATIONS).values(
                observation_id=uuid4(),
                user_id=health["user_id"],
                meta_id=health["meta_id"],
                id_kind=health["id_kind"],
                identity_context=self.context,
                old_handle=old_handle,
                new_handle=health["handle"],
                outcome=outcome,
                observed_at=at,
            )
        )

    async def observe(
        self,
        profile: BloggerProfile,
        info: InstagramProfileInfo | None,
        at: datetime,
        *,
        error: str | None,
        session: object,
    ) -> bool:
        db = _db(session)
        current = await self._lock_profile(profile.user_id, db)
        if (
            current is None
            or not current.confirmed
            or current.instagram_user_id != profile.instagram_user_id
            or current.instagram_url != profile.instagram_url
        ):
            return False  # The owner edited/reverified during the HTTP lookup.
        health = await self._health(current, at, db)
        if health["identity_context"] != self.context:
            return False  # Scoped IDs cannot be moved between Meta apps.
        if at < health["checked_at"]:
            return False
        if info is not None and info.username:
            url, handle = normalize_social_url(
                SocialPlatform.INSTAGRAM,
                f"https://www.instagram.com/{info.username}",
            )
            updated = replace(
                current,
                instagram_url=url,
                instagram_username=handle,
                instagram_followers_count=(
                    info.followers_count
                    if info.followers_count is not None
                    else current.instagram_followers_count
                ),
                instagram_stats_fetched_at=(
                    at
                    if info.followers_count is not None
                    else current.instagram_stats_fetched_at
                ),
            )
            await self.profiles.save(updated, session=db)
            # Preserve real verification/metrics provenance on the social row.
            values: dict = dict(url=url, handle=handle, updated_at=at)
            if info.followers_count is not None:
                values.update(
                    followers_count=info.followers_count,
                    metrics_source="instagram_graph_api",
                    metrics_fetched_at=at,
                )
            await db.execute(
                sa.update(SocialAccountModel)
                .where(
                    SocialAccountModel.user_id == current.user_id,
                    SocialAccountModel.platform == "instagram",
                    SocialAccountModel.verified.is_(True),
                    SocialAccountModel.external_id == current.instagram_user_id,
                )
                .values(**values)
            )
            await self._success(updated, health, handle, at, db, verified=False)
            return True
        if error not in ("100/33", "not_found"):
            return False  # Token, permission, timeout and rate-limit failures.
        old_handle = health["handle"]
        count = next_failure_count(
            health["failure_count"], health["last_failure_at"], at
        )
        if count != health["failure_count"]:
            health["last_failure_at"] = at
        health.update(
            failure_count=count,
            checked_at=at,
            status="review" if count >= 2 else "suspect",
        )
        await self._save_health(health, old_handle, error, at, db)
        if count >= 2:
            await self._enqueue(
                health, current.user_id, None, "owner_refresh", at, db
            )
        return False

    async def verified(
        self,
        profile: BloggerProfile,
        at: datetime,
        *,
        previous_profile: BloggerProfile | None = None,
        session: object,
    ) -> None:
        db = _db(session)
        previous = (
            (
                await db.execute(
                    sa.select(HEALTH).where(HEALTH.c.user_id == profile.user_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        health = await self._health(profile, at, db)
        if previous is not None:
            health["handle"] = previous["handle"]
        _, handle = normalize_social_url(
            SocialPlatform.INSTAGRAM, profile.instagram_url
        )
        customer_refresh = bool(
            previous_profile is not None
            and previous_profile.instagram_user_id
            and (
                previous_profile.instagram_user_id != profile.instagram_user_id
                or previous_profile.instagram_username != handle
            )
        )
        await self._success(
            profile,
            health,
            handle,
            at,
            db,
            verified=True,
            customer_refresh=customer_refresh,
        )

    async def _success(
        self,
        profile: BloggerProfile,
        health: dict,
        handle: str,
        at: datetime,
        db: AsyncSession,
        *,
        verified: bool,
        customer_refresh: bool = False,
    ) -> None:
        old_handle = health["handle"]
        renamed = old_handle != handle
        if renamed or health["status"] != "healthy" or verified:
            health["episode"] = uuid4()
        health.update(
            handle=handle,
            status="healthy",
            failure_count=0,
            last_failure_at=None,
            last_success_at=at,
            checked_at=at,
        )
        if verified:
            health["id_kind"] = "instagram_scoped_id"
            health["identity_context"] = self.context
        await self._save_health(
            health, old_handle, "verified" if verified else "available", at, db
        )
        await db.execute(
            sa.update(NOTICES)
            .where(
                NOTICES.c.creator_id == profile.user_id,
                NOTICES.c.state == "ready",
                sa.or_(
                    NOTICES.c.purpose == "owner_refresh",
                    NOTICES.c.meta_id != profile.instagram_user_id,
                    NOTICES.c.handle != handle,
                ),
            )
            .values(
                state="obsolete",
                finished_at=at,
                reason="profile_recovered_or_changed",
            )
        )
        if renamed or customer_refresh:
            for order_id, recipient_id in await self._customers(
                profile.user_id, db
            ):
                await self._enqueue(
                    health, recipient_id, order_id, "customer_link", at, db
                )

    async def _customers(self, creator_id: UUID, db: AsyncSession) -> set:
        legacy = (
            sa.select(OrderModel.order_id, OrderModel.advertiser_id)
            .join(
                InteractionModel,
                InteractionModel.order_id == OrderModel.order_id,
            )
            .where(
                OrderModel.status == OrderStatus.ACTIVE,
                InteractionModel.blogger_id == creator_id,
                InteractionModel.status.in_(
                    (
                        InteractionStatus.PENDING,
                        InteractionStatus.OK,
                        InteractionStatus.ISSUE,
                    )
                ),
            )
        )
        paid = (
            sa.select(OrderModel.order_id, OrderModel.advertiser_id)
            .join(
                OrderItemModel, OrderItemModel.order_id == OrderModel.order_id
            )
            .join(
                ItemAssignmentModel,
                ItemAssignmentModel.paid_item_id == OrderItemModel.paid_item_id,
            )
            .where(
                OrderModel.status == OrderStatus.ACTIVE,
                ItemAssignmentModel.creator_id == creator_id,
                ItemAssignmentModel.valid_to.is_(None),
                OrderItemModel.captured_at.is_not(None),
            )
        )
        rows = await db.execute(legacy.union(paid))
        return {(row[0], row[1]) for row in rows if row[1] != creator_id}

    async def _enqueue(
        self,
        health: dict,
        recipient_id: UUID,
        order_id: UUID | None,
        purpose: str,
        at: datetime,
        db: AsyncSession,
    ) -> None:
        key = (
            f"instagram:{health['episode']}:{purpose}:{recipient_id}:{order_id}"
        )
        await db.execute(
            insert(NOTICES)
            .values(
                job_id=uuid5(NAMESPACE_URL, key),
                creator_id=health["user_id"],
                recipient_id=recipient_id,
                order_id=order_id,
                purpose=purpose,
                episode=health["episode"],
                meta_id=health["meta_id"],
                handle=health["handle"],
                state="ready",
                attempt_count=0,
                not_before=next_profile_notice_at(at),
                created_at=at,
            )
            .on_conflict_do_nothing(index_elements=[NOTICES.c.job_id])
        )

    async def claim(self, at: datetime, *, session: object):
        db = _db(session)
        if next_profile_notice_at(at) != at:
            return None
        # A crashed sender must never cause an automatic duplicate.
        await db.execute(
            sa.update(NOTICES)
            .where(NOTICES.c.state == "sending", NOTICES.c.lease_until <= at)
            .values(
                state="unknown", finished_at=at, reason="sender_lease_expired"
            )
        )
        for _ in range(20):
            job = (
                (
                    await db.execute(
                        sa.select(NOTICES)
                        .where(
                            NOTICES.c.state == "ready",
                            NOTICES.c.not_before <= at,
                        )
                        .order_by(NOTICES.c.created_at, NOTICES.c.job_id)
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if job is None:
                return None
            notice = await self._prepare(dict(job), at, db)
            if notice is not None:
                return notice
        return None

    async def _prepare(self, job: dict, at: datetime, db: AsyncSession):
        health = (
            (
                await db.execute(
                    sa.select(HEALTH).where(
                        HEALTH.c.user_id == job["creator_id"]
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        profile = await self.profiles.get_by_user_id(
            job["creator_id"], session=db
        )
        valid = (
            health is not None
            and profile is not None
            and profile.instagram_user_id == job["meta_id"]
            and health["meta_id"] == job["meta_id"]
        )
        if valid:
            assert health is not None and profile is not None
            valid = await self._eligible_job(job, health, profile, db)
        user = await db.get(UserModel, job["recipient_id"])
        address = None
        kind = "chat_id"
        channel = str(user.messenger_type) if user else ""
        if user is not None and user.status in (
            UserStatus.NEW,
            UserStatus.ACTIVE,
        ):
            if channel == "telegram":
                address = user.telegram_id
            elif channel == "max":
                address = user.max_chat_id or user.max_id
                kind = "chat_id" if user.max_chat_id else "user_id"
        if not valid or not address:
            await db.execute(
                sa.update(NOTICES)
                .where(NOTICES.c.job_id == job["job_id"])
                .values(
                    state="obsolete",
                    finished_at=at,
                    reason="profile_or_recipient_no_longer_eligible",
                )
            )
            return None
        text, card = self._message(job)
        lease = uuid4()
        await db.execute(
            sa.update(NOTICES)
            .where(NOTICES.c.job_id == job["job_id"])
            .values(
                state="sending",
                lease=lease,
                lease_until=at + timedelta(minutes=5),
                attempt_count=NOTICES.c.attempt_count + 1,
            )
        )
        return ProfileNotice(
            job["job_id"], lease, channel, address, kind, text, card
        )

    async def _eligible_job(self, job, health, profile, db) -> bool:
        if job["purpose"] == "owner_refresh":
            return (
                health["status"] == "review"
                and (health["episode"] == job["episode"])
                and profile.confirmed
            )
        return (
            health["status"] == "healthy"
            and (health["handle"] == job["handle"])
            and profile.confirmed
            and (job["order_id"], job["recipient_id"])
            in (await self._customers(job["creator_id"], db))
        )

    @staticmethod
    def _message(job):
        if job["purpose"] == "owner_refresh":
            text = (
                "Проверьте Instagram в профиле UMC\n"
                "Meta несколько раз не смогла открыть ваш аккаунт. "
                "Возможно, изменился ник или доступ к профилю. "
                "Укажите актуальную ссылку и подтвердите аккаунт "
                "обычным кодом. "
                "Это поможет снова получать подходящие предложения."
            )
            card = ReceiptCard(
                callbacks=(
                    ReceiptCallback("Обновить Instagram", REFRESH_CALLBACK),
                )
            )
        else:
            text = (
                "Актуальный Instagram блогера\n"
                f"Заказ {job['order_id']}: @{job['handle']}\n"
                f"https://www.instagram.com/{job['handle']}\n"
                "Используйте эту ссылку для связи по заказу."
            )
            card = ReceiptCard()
        return text, card

    async def finish(
        self,
        notice: ProfileNotice,
        state: str,
        at: datetime,
        *,
        reference: str | None = None,
        reason: str | None = None,
        retry_at: datetime | None = None,
        session: object,
    ) -> None:
        await _db(session).execute(
            sa.update(NOTICES)
            .where(
                NOTICES.c.job_id == notice.job_id,
                NOTICES.c.lease == notice.lease,
                NOTICES.c.state == "sending",
            )
            .values(
                state=state,
                provider_reference=reference,
                reason=reason,
                finished_at=None if state == "ready" else at,
                not_before=next_profile_notice_at(retry_at or at),
            )
        )

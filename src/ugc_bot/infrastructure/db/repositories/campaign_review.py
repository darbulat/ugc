"""Own draft persistence and private facts in the caller's transaction."""

from dataclasses import dataclass

from sqlalchemy import func, insert, select, text

from ugc_bot.application.campaign_ports import CampaignRepository
from ugc_bot.infrastructure.db.campaign_review_models import (
    COMMANDS,
    DRAFTS,
    REVISIONS,
)
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    UserModel,
    UserReferralBindingModel,
)
from ugc_bot.infrastructure.db.repositories.campaigns import mapping
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.social_models import SocialAccountModel


@dataclass
class SqlAlchemyCampaignReviewRepository:
    foundation: CampaignRepository

    async def _installed(self, db):
        ready = await db.scalar(
            text(
                "SELECT to_regclass('campaign_draft_commands') IS NOT NULL "
                "AND to_regclass('campaign_drafts') IS NOT NULL "
                "AND to_regclass('campaign_draft_revisions') IS NOT NULL "
                "AND to_regclass('creator_social_accounts') IS NOT NULL"
            )
        )
        if not ready:
            raise ValueError("campaign_drafts_unavailable")

    async def draft(self, owner_id, campaign_id, *, session):
        db = _session(session)
        await self._installed(db)
        return await mapping(
            db,
            select(REVISIONS)
            .where(
                REVISIONS.c.owner_id == owner_id,
                REVISIONS.c.campaign_id == campaign_id,
            )
            .order_by(REVISIONS.c.version.desc())
            .limit(1),
        )

    async def command(self, actor_id, key, *, session):
        db = _session(session)
        await self._installed(db)
        return await mapping(
            db,
            select(COMMANDS).where(
                COMMANDS.c.actor_id == actor_id, COMMANDS.c.operation_key == key
            ),
        )

    async def save(self, values, receipt, *, session):
        db = _session(session)
        await self._installed(db)
        await db.execute(insert(COMMANDS).values(**receipt))
        if values["version"] == 1:
            await db.execute(
                insert(DRAFTS).values(
                    campaign_id=values["campaign_id"],
                    owner_id=values["owner_id"],
                    operation_key=values["operation_key"],
                    created_at=values["recorded_at"],
                )
            )
        await db.execute(insert(REVISIONS).values(**values))

    async def list_drafts(self, owner_id, page, *, session):
        db = _session(session)
        await self._installed(db)
        latest = (
            select(
                REVISIONS.c.campaign_id,
                func.max(REVISIONS.c.version).label("version"),
            )
            .where(REVISIONS.c.owner_id == owner_id)
            .group_by(REVISIONS.c.campaign_id)
            .subquery()
        )
        statement = (
            select(REVISIONS)
            .join(
                latest,
                (latest.c.campaign_id == REVISIONS.c.campaign_id)
                & (latest.c.version == REVISIONS.c.version),
            )
            .where(REVISIONS.c.owner_id == owner_id)
            .order_by(REVISIONS.c.recorded_at.desc(), REVISIONS.c.campaign_id)
            .offset(page * 25)
            .limit(26)
        )
        return [dict(row) for row in (await db.execute(statement)).mappings()]

    async def candidates(self, owner_id, *, session):
        db = _session(session)
        await self._installed(db)
        ids = tuple(
            await db.scalars(
                select(UserReferralBindingModel.referred_user_id)
                .join(
                    UserModel,
                    UserModel.user_id
                    == UserReferralBindingModel.referred_user_id,
                )
                .where(UserReferralBindingModel.referrer_user_id == owner_id)
                .order_by(UserReferralBindingModel.referred_user_id)
            )
        )
        publisher = await self.foundation.current(
            "publisher", owner_id, session=session
        )
        for user_id in ids:
            context = await self.foundation.context(
                user_id, lock=False, session=session
            )
            # Retain campaign consent/routing facts, without freezing the
            # entire User row (including unrelated financial settings).
            context = {
                **context,
                "actor": {
                    key: context["actor"][key]
                    for key in (
                        "user_id",
                        "status",
                        "telegram_id",
                        "telegram_usable",
                    )
                },
                "inviter": {
                    key: context["inviter"][key]
                    for key in ("user_id", "status")
                }
                if context["inviter"] is not None
                else None,
            }
            consent = await self.foundation.current(
                "consent", user_id, session=session
            )
            proof = (
                await self.foundation.receipt(
                    consent["actor_id"],
                    consent["operation_key"],
                    session=session,
                )
                if consent and consent["active"]
                else None
            )
            profile = await mapping(
                db,
                select(
                    BloggerProfileModel.country,
                    BloggerProfileModel.region,
                    BloggerProfileModel.city,
                    BloggerProfileModel.topics,
                    BloggerProfileModel.work_format,
                ).where(BloggerProfileModel.user_id == user_id),
            )
            socials = [
                dict(row)
                for row in (
                    await db.execute(
                        select(
                            SocialAccountModel.platform,
                            SocialAccountModel.work_format,
                        ).where(SocialAccountModel.user_id == user_id)
                    )
                ).mappings()
            ]
            yield {
                "context": context,
                "publisher": publisher,
                "consent": consent,
                "receipt": proof,
                "profile": profile,
                "socials": socials,
            }

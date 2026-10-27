"""Shared User → identity-history → campaign barriers, immutable SQL facts."""

from uuid import UUID

from sqlalchemy import func, insert, or_, select, text

from ugc_bot.application.services.campaign_consent import binding_epoch
from ugc_bot.domain.campaigns import CampaignConflict
from ugc_bot.infrastructure.db.campaign_models import (
    COMMANDS,
    POLICIES,
    STREAMS,
)
from ugc_bot.infrastructure.db.identity_history_models import (
    BINDING_OBSERVATIONS,
)
from ugc_bot.infrastructure.db.identity_history_schema import (
    HISTORY_SNAPSHOT_LOCK_SQL,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    UserModel,
    UserReferralBindingModel,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session


async def mapping(db, statement):
    row = (await db.execute(statement)).mappings().one_or_none()
    return dict(row) if row is not None else None


class SqlAlchemyCampaignRepository:
    async def _installed(self, db):
        if not await db.scalar(
            text(
                "SELECT to_regclass('campaign_foundation_commands') "
                "IS NOT NULL AND to_regclass('campaign_policy_events') "
                "IS NOT NULL AND to_regclass('campaign_publisher_events') "
                "IS NOT NULL AND to_regclass('campaign_consent_events') "
                "IS NOT NULL AND "
                "to_regclass('creator_direct_binding_observations') IS NOT NULL"
            )
        ):
            raise ValueError("campaign_foundation_unavailable")

    async def begin_snapshot(self, *, session):
        db = _session(session)
        await db.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        )
        await self._installed(db)
        return await db.scalar(text("SELECT transaction_timestamp()"))

    async def _binding(self, db, actor):
        return await mapping(
            db,
            select(UserReferralBindingModel.__table__).where(
                UserReferralBindingModel.referred_user_id == actor
            ),
        )

    async def _binding_epoch(self, db, binding):
        if binding is None:
            return None
        table = BINDING_OBSERVATIONS
        subject = table.c.referred_user_id == binding["referred_user_id"]
        boundary = await db.scalar(
            select(func.max(table.c.observation_sequence)).where(
                subject,
                or_(
                    table.c.active.is_(False),
                    table.c.referrer_user_id != binding["referrer_user_id"],
                    table.c.created_at != binding["created_at"],
                ),
            )
        )
        rows = (
            await db.execute(
                select(table).where(
                    subject,
                    table.c.observation_sequence > (boundary or 0),
                )
            )
        ).mappings()
        return binding_epoch(binding, rows)

    async def context(self, actor_id, target_id=None, *, lock, session):
        db = _session(session)
        before = await self._binding(db, actor_id)
        ids = {actor_id}
        if target_id:
            ids.add(target_id)
        if before:
            ids.add(before["referrer_user_id"])
        users = {}
        for uid in sorted(ids, key=str):
            stmt = select(UserModel.__table__).where(UserModel.user_id == uid)
            if lock:
                stmt = stmt.with_for_update(read=True)
            user = await mapping(db, stmt)
            if user:
                address = user["telegram_id"] or ""
                user["telegram_usable"] = (
                    address.isascii() and address.isdigit() and int(address) > 0
                )
                users[uid] = user
        if actor_id not in users:
            raise LookupError("campaign_actor_not_found")
        if lock:
            await db.execute(text(HISTORY_SNAPSHOT_LOCK_SQL))
            await db.execute(
                text("SELECT pg_advisory_xact_lock(2119754201, 170434820)")
            )
            await self._installed(db)
        binding = await self._binding(db, actor_id)
        if binding != before:
            raise CampaignConflict("campaign_inviter_changed")
        profile = await mapping(
            db,
            select(BloggerProfileModel.__table__).where(
                BloggerProfileModel.user_id == actor_id
            ),
        )
        inviter = users.get(binding["referrer_user_id"]) if binding else None
        if inviter:
            inviter["label"] = await self._label(db, inviter["user_id"])
        epoch = await self._binding_epoch(db, binding)
        return {
            "actor": users[actor_id],
            "has_creator_profile": profile is not None,
            "target": users.get(target_id),
            "inviter": inviter,
            "canonical_identity": (profile["instagram_user_id"] or "").strip()
            if profile and profile["confirmed"]
            else None,
            "binding_created_at": binding["created_at"] if binding else None,
            "binding_sequence": epoch.sequence if epoch else None,
            "binding_witness_sequences": epoch.witness_sequences
            if epoch
            else (),
        }

    async def _label(self, db, uid):
        brand = await db.scalar(
            select(AdvertiserProfileModel.brand).where(
                AdvertiserProfileModel.user_id == uid
            )
        )
        if brand and brand.strip():
            return brand
        profile = await mapping(
            db,
            select(BloggerProfileModel.instagram_url).where(
                BloggerProfileModel.user_id == uid,
                BloggerProfileModel.confirmed.is_(True),
            ),
        )
        return profile["instagram_url"] if profile else None

    async def current(self, stream, subject=None, *, session):
        table = STREAMS[stream]
        stmt = select(table).order_by(table.c.version.desc()).limit(1)
        if stream != "policy":
            stmt = (
                stmt.where(table.c.owner_id == subject)
                if stream == "publisher"
                else stmt.where(table.c.creator_id == subject)
            )
        return await mapping(_session(session), stmt)

    async def receipt(self, actor_id, key, *, session):
        return await mapping(
            _session(session),
            select(COMMANDS).where(
                COMMANDS.c.actor_id == actor_id, COMMANDS.c.operation_key == key
            ),
        )

    async def known_terms(self, version, *, session):
        return await _session(session).scalar(
            select(POLICIES.c.terms_hash)
            .where(POLICIES.c.terms_version == version)
            .limit(1)
        )

    async def append(self, stream, values, *, session):
        await _session(session).execute(
            insert(STREAMS[stream]).values(**values)
        )

    async def save_receipt(self, values, *, session):
        await _session(session).execute(insert(COMMANDS).values(**values))

    async def accounts(self, search, page, *, session):
        db = _session(session)
        users = UserModel.__table__
        stmt = (
            select(users.c.user_id, users.c.status)
            .order_by(users.c.user_id)
            .offset(page * 25)
            .limit(26)
        )
        if search:
            # UUID lookup only; never search or expose contact fields.
            try:
                uid = UUID(search)
            except ValueError:
                return []
            stmt = stmt.where(users.c.user_id == uid)
        else:
            stmt = stmt.where(users.c.status == "active")
        result = []
        for account in (await db.execute(stmt)).mappings():
            uid = account["user_id"]
            grant = await self.current("publisher", uid, session=session)
            result.append(
                {
                    "owner_id": str(uid),
                    "label": await self._label(db, uid),
                    "version": grant["version"] if grant else 0,
                    "active": bool(grant and grant["active"]),
                    "status": str(account["status"]),
                    "can_grant": account["status"] == "active",
                    "can_revoke": bool(grant and grant["active"]),
                }
            )
        return result

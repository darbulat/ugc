"""Own-only nonlocking reads under one explicit read-only MVCC snapshot."""

from dataclasses import fields

from sqlalchemy import func, or_, select, text

from ugc_bot.application.financial_ports import JournalMovement
from ugc_bot.application.native_principal_ports import require_current_principal
from ugc_bot.application.partner_view_ports import (
    PAGE_SIZE,
    PartnerFinancialFacts,
    PartnerMovement,
    PartnerObligation,
    PartnerReadFacts,
)
from ugc_bot.application.services.financial_reconciliation_service import (
    BUCKETS,
)
from ugc_bot.infrastructure.db import models as m
from ugc_bot.infrastructure.db.collaboration_models import CollaborationModel
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.repositories.rate_overrides import (
    SqlAlchemyRateOverrideRepository,
)
from ugc_bot.infrastructure.db.social_models import SocialAccountModel


async def _installed(db, names):
    # Only fixed server-owned table names enter SQL; never client input.
    return bool(
        await db.scalar(
            text(
                "SELECT "
                + " AND ".join(
                    f"to_regclass('{name}') IS NOT NULL" for name in names
                )
            )
        )
    )


def _network(actor_id, at):
    users, binding, creator, client = (
        m.UserModel.__table__,
        m.UserReferralBindingModel.__table__,
        m.BloggerProfileModel.__table__,
        m.AdvertiserProfileModel.__table__,
    )
    manager = (
        select(m.ManagerOrderModel.user_id)
        .where(m.ManagerOrderModel.user_id == users.c.user_id)
        .exists()
    )
    return (
        select(
            users.c.user_id,
            users.c.created_at,
            users.c.status,
            creator.c.user_id.label("creator_id"),
            client.c.user_id.label("client_id"),
            manager.label("is_manager"),
            creator.c.instagram_url,
            creator.c.instagram_user_id,
            creator.c.confirmed,
        )
        .select_from(
            binding.join(users, users.c.user_id == binding.c.referred_user_id)
            .outerjoin(creator, creator.c.user_id == users.c.user_id)
            .outerjoin(client, client.c.user_id == users.c.user_id)
        )
        .where(
            binding.c.referrer_user_id == actor_id,
            binding.c.referred_user_id != actor_id,
            binding.c.created_at <= at,
            users.c.created_at <= at,
            or_(
                creator.c.user_id.is_not(None),
                client.c.user_id.is_not(None),
                manager,
                users.c.role_chosen_at.is_not(None),
            ),
        )
    )


async def _members(db, rows):
    ids = [r["user_id"] for r in rows]
    socials = {}
    if ids and await _installed(db, ("creator_social_accounts",)):
        for social in (
            await db.execute(
                select(SocialAccountModel.__table__)
                .where(SocialAccountModel.user_id.in_(ids))
                .order_by(SocialAccountModel.platform)
            )
        ).mappings():
            socials.setdefault(social["user_id"], []).append(social)
    stats = {}
    if ids and await _installed(db, ("instagram_stats",)):
        stats = {
            r["user_id"]: r
            for r in (
                await db.execute(
                    select(
                        m.InstagramStatsModel.user_id,
                        m.InstagramStatsModel.instagram_id,
                        m.InstagramStatsModel.followers_count,
                        m.InstagramStatsModel.provider,
                        m.InstagramStatsModel.fetched_at,
                    ).where(m.InstagramStatsModel.user_id.in_(ids))
                )
            ).mappings()
        }
    members = []
    for row in rows:
        uid = row["user_id"]
        accounts = []
        verified = bool(
            row["confirmed"] and (row["instagram_user_id"] or "").strip()
        )
        if row["instagram_url"]:
            metric = stats.get(uid)
            known = (
                verified
                and metric is not None
                and metric["instagram_id"] == row["instagram_user_id"]
                and metric["followers_count"] is not None
                and metric["provider"]
                and metric["fetched_at"]
            )
            accounts.append(
                {
                    "platform": "instagram",
                    "url": row["instagram_url"],
                    "verified": verified,
                    "verification_source": "canonical_profile"
                    if verified
                    else None,
                    "followers_count": metric["followers_count"]
                    if known
                    else None,
                    "metrics_source": metric["provider"] if known else None,
                    "metrics_fetched_at": metric["fetched_at"]
                    if known
                    else None,
                }
            )
        for account in socials.get(uid, ()):
            if account["platform"] == "instagram":
                if (
                    accounts
                    and verified
                    and account["verified"]
                    and account["external_id"] == row["instagram_user_id"]
                ):
                    accounts[0]["verification_source"] = account[
                        "verification_source"
                    ]
                    if (
                        account["followers_count"] is None
                        or not account["metrics_source"]
                        or account["metrics_fetched_at"] is None
                        or (
                            accounts[0]["metrics_fetched_at"] is not None
                            and accounts[0]["metrics_fetched_at"]
                            > account["metrics_fetched_at"]
                        )
                    ):
                        continue
                    accounts[0].update(
                        {
                            key: account[key]
                            for key in (
                                "followers_count",
                                "metrics_source",
                                "metrics_fetched_at",
                                "verification_source",
                            )
                        }
                    )
                continue
            accounts.append(
                {
                    key: account[key]
                    for key in (
                        "platform",
                        "url",
                        "verified",
                        "followers_count",
                        "metrics_source",
                        "metrics_fetched_at",
                        "verification_source",
                    )
                }
            )
        roles = [
            role
            for role, present in (
                ("creator", row["creator_id"]),
                ("client", row["client_id"]),
                ("manager", row["is_manager"]),
            )
            if present
        ]
        members.append(
            {
                "member_id": str(uid),
                "registered_at": row["created_at"],
                "status": str(row["status"]),
                "roles": roles,
                "socials": accounts,
            }
        )
    return tuple(members)


async def _financial(db, actor_id):
    names = (
        "financial_obligations",
        "rate_snapshots",
        "financial_movements",
        "financial_wallets",
    )
    if not await _installed(db, names):
        return None
    obligation, snapshot, movement, wallet = (
        m.FinancialObligationModel.__table__,
        m.RateSnapshotModel.__table__,
        m.FinancialMovementModel.__table__,
        m.FinancialWalletModel.__table__,
    )
    rows = (
        await db.execute(
            select(
                obligation,
                snapshot.c.rate_bps,
                snapshot.c.rate_source,
                snapshot.c.effective_at.label("snapshot_at"),
                snapshot.c.registered_at,
                snapshot.c.verified_count,
            )
            .join(snapshot, snapshot.c.id == obligation.c.snapshot_id)
            .where(
                obligation.c.recipient_id == actor_id,
                obligation.c.currency == "RUB",
            )
        )
    ).mappings()
    obligations = tuple(
        PartnerObligation(
            r["id"],
            r["kind"],
            r["order_id"],
            r["paid_item_id"],
            r["assignment_id"],
            r["amount_minor"],
            r["base_minor"],
            r["rate_bps"],
            r["rate_source"],
            r["policy_version"],
            r["snapshot_at"],
            r["registered_at"],
            r["verified_count"],
        )
        for r in rows
    )
    rows = (
        await db.execute(
            select(movement)
            .join(obligation, obligation.c.id == movement.c.obligation_id)
            .where(
                obligation.c.recipient_id == actor_id,
                movement.c.currency == "RUB",
            )
            .order_by(movement.c.append_order)
        )
    ).mappings()
    movements = tuple(
        PartnerMovement(
            r["id"],
            JournalMovement(
                **{f.name: r[f.name] for f in fields(JournalMovement)}
            ),
        )
        for r in rows
    )
    projection = (
        (
            await db.execute(
                select(wallet).where(
                    wallet.c.recipient_id == actor_id,
                    wallet.c.currency == "RUB",
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    return PartnerFinancialFacts(
        obligations,
        movements,
        {b: projection[b + "_minor"] for b in BUCKETS}
        if projection is not None
        else None,
    )


async def _overrides(db, actor_id, at):
    if not await _installed(
        db,
        (
            "financial_rate_overrides",
            "financial_override_events",
            "financial_policy_versions",
        ),
    ):
        return None
    repo = SqlAlchemyRateOverrideRepository()
    policy = m.FinancialPolicyVersionModel.__table__
    rate = m.Base.metadata.tables["financial_rate_overrides"]
    scopes = (
        await db.execute(
            select(rate.c.side, rate.c.policy_version)
            .distinct()
            .join(policy, policy.c.version == rate.c.policy_version)
            .where(
                rate.c.recipient_id == actor_id,
                policy.c.approved_at <= at,
                policy.c.effective_from <= at,
            )
        )
    ).all()
    result = []
    for side, version in scopes:
        try:
            approval = await repo.select_effective_override(
                actor_id, side, version, at, session=db
            )
        except ValueError:
            return None
        if approval is not None:
            result.append(
                {
                    "side": approval.side,
                    "policy_version": approval.policy_version,
                    "rate_bps": approval.rate_bps,
                    "effective_from": approval.effective_from,
                    "effective_until": approval.effective_until,
                }
            )
    return tuple(result)


async def _assignments(db, actor_id, page):
    if not await _installed(
        db, ("financial_collaborations", "item_assignments")
    ):
        return None, None
    c, a = CollaborationModel.__table__, m.ItemAssignmentModel.__table__
    query = (
        select(
            c.c.assignment_id,
            c.c.order_id,
            c.c.paid_item_id,
            c.c.state,
            c.c.due_at,
        )
        .join(a, a.c.assignment_id == c.c.assignment_id)
        .where(
            c.c.manager_id == actor_id,
            a.c.manager_id == actor_id,
            a.c.valid_to.is_(None),
            select(m.ManagerOrderModel.user_id)
            .where(
                m.ManagerOrderModel.user_id == actor_id,
                m.ManagerOrderModel.order_id == c.c.order_id,
            )
            .exists(),
        )
    )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.execute(
            query.order_by(c.c.due_at, c.c.assignment_id)
            .offset(page * PAGE_SIZE)
            .limit(PAGE_SIZE)
        )
    ).mappings()
    return tuple(dict(row) for row in rows), total


class SqlAlchemyPartnerViewRepository:
    async def read(
        self,
        actor_id,
        at,
        *,
        network_page,
        assignment_page,
        session,
        principal=None,
    ):
        db = _session(session)
        if db.get_bind().dialect.name != "postgresql":
            raise ValueError("partner_snapshot_postgres_required")
        # Must precede every SELECT. No writer lock, wallet insert or flush.
        await db.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        )
        actor = (
            (
                await db.execute(
                    select(
                        m.UserModel.user_id,
                        m.UserModel.status,
                        m.UserModel.referral_code,
                        m.UserModel.telegram_id,
                        m.UserModel.max_id,
                    )
                    .where(m.UserModel.user_id == actor_id)
                    .execution_options(autoflush=False)
                )
            )
            .mappings()
            .one_or_none()
        )
        require_current_principal(
            principal,
            actor_id,
            actor["user_id"] if actor else None,
            actor["telegram_id"] if actor else None,
            actor["max_id"] if actor else None,
        )
        if actor is None:
            return None
        network = _network(actor_id, at).subquery()
        total = await db.scalar(select(func.count()).select_from(network))
        count = await db.scalar(
            select(
                func.count(
                    func.distinct(func.trim(network.c.instagram_user_id))
                )
            ).where(
                network.c.confirmed.is_(True),
                func.trim(network.c.instagram_user_id) != "",
            )
        )
        rows = (
            (
                await db.execute(
                    select(network)
                    .order_by(network.c.created_at.desc(), network.c.user_id)
                    .offset(network_page * PAGE_SIZE)
                    .limit(PAGE_SIZE)
                )
            )
            .mappings()
            .all()
        )
        members = await _members(db, rows)
        financial = await _financial(db, actor_id)
        overrides = await _overrides(db, actor_id, at)
        assignments, assignment_total = await _assignments(
            db, actor_id, assignment_page
        )
        return PartnerReadFacts(
            actor_id,
            str(actor["status"]),
            actor["referral_code"],
            count,
            total,
            members,
            financial,
            overrides,
            assignments,
            assignment_total,
        )

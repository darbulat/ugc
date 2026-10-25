"""Atomic audited operational changes; no journal writes or provider calls."""

from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ugc_bot.application.override_ports import OverrideUser
from ugc_bot.infrastructure.db import models as m
from ugc_bot.infrastructure.db.order_intake_models import ACCOMPANIMENT_LEADS
from ugc_bot.infrastructure.db.partner_admin_models import (
    BINDING_CORRECTIONS,
    LEAD_REVIEWS,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session


class SqlAlchemyPartnerAdminRepository:
    async def lock_users(self, ids, *, session):
        rows = (
            await _session(session).scalars(
                select(m.UserModel)
                .where(m.UserModel.user_id.in_(ids))
                .order_by(m.UserModel.user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
        return {
            u.user_id: OverrideUser(
                u.user_id, str(u.status), u.admin, u.telegram_id, u.max_id
            )
            for u in rows
        }

    async def command(self, key, *, session):
        db = _session(session)
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "partner-admin:" + key},
        )
        for table in (LEAD_REVIEWS, BINDING_CORRECTIONS):
            row = (
                await db.execute(
                    select(table.c.payload_hash, table.c.result).where(
                        table.c.operation_key == key
                    )
                )
            ).one_or_none()
            if row is not None:
                return row.payload_hash, row.result
        return None

    async def lead_for_update(self, lead_id, *, session):
        db = _session(session)
        order = await db.scalar(
            select(ACCOMPANIMENT_LEADS.c.order_id).where(
                ACCOMPANIMENT_LEADS.c.lead_id == lead_id
            )
        )
        if order is None:
            return None
        await db.scalar(
            select(m.OrderModel.order_id)
            .where(m.OrderModel.order_id == order)
            .with_for_update()
        )
        row = (
            (
                await db.execute(
                    select(ACCOMPANIMENT_LEADS)
                    .where(ACCOMPANIMENT_LEADS.c.lead_id == lead_id)
                    .with_for_update()
                )
            )
            .mappings()
            .one()
        )
        previous = await db.scalar(
            select(LEAD_REVIEWS.c.version).where(
                LEAD_REVIEWS.c.lead_id == lead_id
            )
        )
        return dict(row, version=previous or 0)

    async def save_lead_review(self, command, result, digest, at, *, session):
        db = _session(session)
        await db.execute(
            insert(LEAD_REVIEWS).values(
                review_id=uuid5(
                    NAMESPACE_URL, "ugc:lead-review:" + command.operation_key
                ),
                lead_id=command.lead_id,
                order_id=result["order_id"],
                actor_id=command.actor_id,
                version=1,
                state=result["state"],
                manager_ids=result["manager_ids"],
                reason=command.reason,
                reviewed_at=at,
                operation_key=command.operation_key,
                payload_hash=digest,
                result=result,
            )
        )
        for uid in command.manager_ids:
            await db.execute(
                pg_insert(m.ManagerOrderModel)
                .values(
                    user_id=uid,
                    order_id=result["order_id"],
                    created_at=at,
                    updated_at=at,
                )
                .on_conflict_do_nothing(index_elements=["order_id", "user_id"])
            )

    async def binding_for_update(self, referred_id, *, session):
        return await _session(session).scalar(
            select(m.UserReferralBindingModel.referrer_user_id)
            .where(m.UserReferralBindingModel.referred_user_id == referred_id)
            .with_for_update()
        )

    async def save_binding_correction(
        self, command, result, digest, at, *, session
    ):
        db = _session(session)
        await db.execute(
            insert(BINDING_CORRECTIONS).values(
                correction_id=uuid5(
                    NAMESPACE_URL,
                    "ugc:referral-correction:" + command.operation_key,
                ),
                referred_id=command.referred_id,
                previous_referrer_id=command.expected_referrer_id,
                referrer_id=command.referrer_id,
                actor_id=command.actor_id,
                reason=command.reason,
                corrected_at=at,
                operation_key=command.operation_key,
                payload_hash=digest,
                result=result,
            )
        )
        await db.execute(
            update(m.UserReferralBindingModel)
            .where(
                m.UserReferralBindingModel.referred_user_id
                == command.referred_id,
                m.UserReferralBindingModel.referrer_user_id
                == command.expected_referrer_id,
            )
            .values(referrer_user_id=command.referrer_id)
        )

    async def queue_leads(self, page, status, *, session):
        leads, reviews = ACCOMPANIMENT_LEADS, LEAD_REVIEWS
        query = select(
            leads,
            reviews.c.version,
            reviews.c.state.label("review_state"),
            reviews.c.reason,
            reviews.c.actor_id,
            reviews.c.reviewed_at,
            reviews.c.manager_ids,
        ).outerjoin(reviews, reviews.c.lead_id == leads.c.lead_id)
        if status == "pending":
            query = query.where(reviews.c.lead_id.is_(None))
        elif status != "all":
            query = query.where(reviews.c.state == status)
        db = _session(session)
        total = await db.scalar(
            select(func.count()).select_from(query.subquery())
        )
        rows = (
            await db.execute(
                query.order_by(leads.c.requested_at, leads.c.lead_id)
                .offset(page * 20)
                .limit(20)
            )
        ).mappings()
        return {
            "entries": [dict(row, version=row["version"] or 0) for row in rows],
            "page": page,
            "total": total,
            "has_more": total > (page + 1) * 20,
        }

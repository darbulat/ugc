"""Sanitized operational explanations for the recipient's own obligations."""

import re
from datetime import timedelta

from sqlalchemy import select

from ugc_bot.application.partner_view_ports import (
    PartnerPendingContext,
    PartnerWaitingParty,
)
from ugc_bot.infrastructure.db import models as m
from ugc_bot.infrastructure.db.collaboration_models import CollaborationModel


def public_identity(name, telegram):
    handle = (telegram or "").strip().removeprefix("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", handle):
        return None, None
    return name, handle


def pending_context(row, at, people):
    state, due = row["state"], row["due_at"]
    payload = row["record_payload"]
    if isinstance(payload, dict):
        payload = payload.get("collaboration", payload)
    if not isinstance(payload, dict):
        payload = {}
    roles = []
    if state in ("assigned", "in_progress"):
        reason = "awaiting_confirmation"
        roles = ["client", "creator"]
        if at >= due + timedelta(days=14):
            reason, roles = "expiry_processing", []
    elif state == "success_claimed":
        reason = (
            "awaiting_counterparty"
            if payload.get("notice_delivered_at")
            else "confirmation_notice_pending"
        )
        claimant = payload.get("claimant_id")
        roles = [
            role
            for role in ("client", "creator")
            if str(row[role + "_id"]) != claimant
        ]
    elif state == "disputed":
        reason = "dispute_review"
    elif state == "unconfirmed_expired":
        reason = "expiry_processing"
    else:
        reason = "financial_processing"
    parties = []
    for role in roles:
        name, telegram = people.get(row[role + "_id"], (None, None))
        parties.append(PartnerWaitingParty(role, name, telegram))
    return PartnerPendingContext(reason, state, due, tuple(parties))


async def read_pending_contexts(db, actor_id, obligations, at):
    ids = [o.assignment_id for o in obligations if o.assignment_id is not None]
    if not ids:
        return {}
    rows = (
        (
            await db.execute(
                select(CollaborationModel.__table__).where(
                    CollaborationModel.assignment_id.in_(ids)
                )
            )
        )
        .mappings()
        .all()
    )
    people_ids = {
        row[key] for row in rows for key in ("client_id", "creator_id")
    }
    people = {
        row.user_id: public_identity(row.username, row.telegram)
        for row in (
            await db.execute(
                select(
                    m.UserModel.user_id,
                    m.UserModel.username,
                    m.UserModel.telegram,
                )
                .join(
                    m.UserReferralBindingModel,
                    m.UserReferralBindingModel.referred_user_id
                    == m.UserModel.user_id,
                )
                .where(
                    m.UserReferralBindingModel.referrer_user_id == actor_id,
                    m.UserModel.user_id.in_(people_ids),
                )
            )
        ).all()
    }
    return {
        row["assignment_id"]: pending_context(row, at, people) for row in rows
    }


async def network_work_counts(db, ids):
    from sqlalchemy import func

    c = CollaborationModel.__table__
    assignment = m.ItemAssignmentModel.__table__
    rows = (
        await db.execute(
            select(
                c.c.creator_id,
                func.count(func.distinct(c.c.order_id))
                .filter(
                    c.c.state.in_(
                        (
                            "assigned",
                            "in_progress",
                            "success_claimed",
                            "disputed",
                        )
                    ),
                    assignment.c.valid_to.is_(None),
                )
                .label("active_orders"),
                func.count()
                .filter(c.c.state.in_(("success_final", "available")))
                .label("completed_works"),
            )
            .join(
                assignment,
                assignment.c.assignment_id == c.c.assignment_id,
            )
            .where(c.c.creator_id.in_(ids))
            .group_by(c.c.creator_id)
        )
    ).mappings()
    return {
        row["creator_id"]: {
            "active_orders": row["active_orders"],
            "completed_works": row["completed_works"],
        }
        for row in rows
    }

"""Current user barriers and serialized append-only subscription commands."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import insert, select, text

from ugc_bot.application.subscription_ports import SubscriptionCampaignUse
from ugc_bot.infrastructure.db.campaign_models import PUBLISHERS
from ugc_bot.infrastructure.db.campaign_runtime_models import (
    JOBS,
    OUTCOMES,
    SUBMISSIONS,
)
from ugc_bot.infrastructure.db.models import ManagerOrderModel, UserModel
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.subscription_models import SUBSCRIPTIONS


class SqlAlchemySubscriptionRepository:
    async def context(
        self, actor_id: UUID, member_id: UUID, *, session: object
    ) -> dict:
        db = _session(session)
        users = (
            await db.execute(
                select(
                    UserModel.user_id,
                    UserModel.status,
                    UserModel.admin,
                    UserModel.telegram_id,
                    UserModel.max_id,
                )
                .where(
                    UserModel.user_id.in_(
                        sorted({actor_id, member_id}, key=str)
                    )
                )
                .order_by(UserModel.user_id)
                .with_for_update(key_share=True)
            )
        ).all()
        by_id = {u.user_id: u for u in users}
        actor, member = by_id.get(actor_id), by_id.get(member_id)
        manager = await db.scalar(
            select(ManagerOrderModel.user_id)
            .where(ManagerOrderModel.user_id == member_id)
            .limit(1)
            .with_for_update(read=True)
        )
        publisher = await db.scalar(
            select(PUBLISHERS.c.active)
            .where(PUBLISHERS.c.owner_id == member_id)
            .order_by(PUBLISHERS.c.version.desc())
            .limit(1)
        )
        return dict(
            actor_active=bool(actor and actor.status == "active"),
            admin=bool(actor and actor.admin),
            member_active=bool(member and member.status == "active"),
            manager=manager is not None or publisher is True,
            telegram_id=actor.telegram_id if actor else None,
            max_id=actor.max_id if actor else None,
        )

    async def lock(self, *, session: object) -> None:
        await _session(session).execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended('manager_subscriptions:v1',0))"
            )
        )

    async def events(self, *, session: object) -> list[dict]:
        rows = (
            (
                await _session(session).execute(
                    select(SUBSCRIPTIONS).order_by(SUBSCRIPTIONS.c.sequence)
                )
            )
            .mappings()
            .all()
        )
        return [
            dict(
                event_id=str(r["event_id"]),
                sequence=r["sequence"],
                actor_id=str(r["actor_id"]),
                member_id=str(r["member_id"]),
                operation_key=r["operation_key"],
                action=r["action"],
                payload_hash=r["payload_hash"],
                payload=r["payload"],
                result=r["result"],
                recorded_at=r["recorded_at"].isoformat(),
            )
            for r in rows
        ]

    async def pilot_reuse(
        self, first_paid: dict[UUID, datetime], *, session: object
    ) -> tuple[SubscriptionCampaignUse, ...]:
        if not first_paid:
            return ()
        uses: list[SubscriptionCampaignUse] = []
        for member, paid_at in sorted(
            first_paid.items(), key=lambda row: str(row[0])
        ):
            statement = (
                select(
                    SUBMISSIONS.c.owner_id,
                    SUBMISSIONS.c.campaign_id,
                    OUTCOMES.c.outcome_id,
                )
                .join(JOBS, JOBS.c.submission_id == SUBMISSIONS.c.submission_id)
                .join(OUTCOMES, OUTCOMES.c.job_id == JOBS.c.job_id)
                .where(
                    SUBMISSIONS.c.owner_id == member,
                    OUTCOMES.c.state == "accepted",
                    OUTCOMES.c.recorded_at >= paid_at,
                )
                .distinct(SUBMISSIONS.c.campaign_id)
                .order_by(
                    SUBMISSIONS.c.campaign_id,
                    OUTCOMES.c.recorded_at,
                    OUTCOMES.c.outcome_id,
                )
                .limit(2)
            )
            rows = (await _session(session).execute(statement)).all()
            uses.extend(
                SubscriptionCampaignUse(
                    row.owner_id, row.campaign_id, row.outcome_id
                )
                for row in rows
            )
        return tuple(uses)

    async def append(self, event: dict, *, session: object) -> None:
        values = dict(event)
        for key in ("event_id", "actor_id", "member_id"):
            values[key] = UUID(values[key])
        values["recorded_at"] = datetime.fromisoformat(values["recorded_at"])
        values["payment_reference"] = (
            event["payload"]["payment_reference"].strip()
            if event["action"] == "accept_payment"
            else None
        )
        values["tariff_version"] = (
            event["result"]["version"] if event["action"] == "publish" else None
        )
        await _session(session).execute(insert(SUBSCRIPTIONS).values(**values))

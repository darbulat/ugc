"""Current admins and immutable, globally recognized repayment facts."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import insert, select, text

from ugc_bot.application.override_ports import OverrideUser
from ugc_bot.infrastructure.db.debt_recovery_models import (
    APPLICATIONS,
    COMMANDS,
    OBSERVATIONS,
)
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.repositories.order_intake import canonical


class SqlAlchemyDebtRecoveryRepository:
    async def actor(self, actor_id, *, session):
        user = await _session(session).scalar(
            select(UserModel)
            .where(UserModel.user_id == actor_id)
            .execution_options(populate_existing=True)
        )
        return (
            OverrideUser(
                user.user_id,
                str(user.status),
                user.admin,
                user.telegram_id,
                user.max_id,
            )
            if user
            else None
        )

    async def lock_operation(self, actor_id, operation_key, *, session):
        await _session(session).execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {
                "key": (
                    f"repayment:{actor_id}:{len(operation_key)}:{operation_key}"
                )
            },
        )

    async def command(self, actor_id, operation_key, *, session):
        row = (
            (
                await _session(session).execute(
                    select(COMMANDS).where(
                        COMMANDS.c.actor_id == actor_id,
                        COMMANDS.c.operation_key == operation_key,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row else None

    async def observation(self, identity, *, session):
        row = (
            await _session(session).execute(
                select(OBSERVATIONS.c.document).where(
                    OBSERVATIONS.c.observation_id == identity
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        result = dict(row)
        for key in (
            "actor_id",
            "recipient_id",
            "case_id",
            "command_id",
            "observation_id",
        ):
            result[key] = UUID(result[key])
        for key in ("occurred_at", "recorded_at"):
            result[key] = datetime.fromisoformat(result[key])
        return result

    async def application(self, identity, *, session):
        row = (
            (
                await _session(session).execute(
                    select(APPLICATIONS)
                    .where(APPLICATIONS.c.observation_id == identity)
                    .order_by(APPLICATIONS.c.obligation_id)
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row else None

    async def append_observation(self, value, *, session):
        keys = (
            "observation_id",
            "command_id",
            "recipient_id",
            "case_id",
            "amount_minor",
            "currency",
            "proof_claimed",
            "recorded_at",
        )
        await _session(session).execute(
            insert(OBSERVATIONS).values(
                **{key: value[key] for key in keys}, document=canonical(value)
            )
        )

    async def append_application(self, value, *, session):
        await _session(session).execute(insert(APPLICATIONS).values(**value))

    async def save_command(self, value, *, session):
        await _session(session).execute(
            insert(COMMANDS).values(
                **(
                    value
                    | {
                        "payload": canonical(value["payload"]),
                        "result": canonical(value["result"]),
                    }
                )
            )
        )

    async def case_grounds(self, case_id, recipient_id, currency, *, session):
        rows = await _session(session).execute(
            text("""
SELECT DISTINCT b.business_key
FROM financial_obligations b JOIN financial_movements m ON m.obligation_id=b.id
WHERE m.case_id=:case_id AND m.movement_type='debt'
 AND b.recipient_id=:recipient_id AND b.currency=:currency
ORDER BY b.business_key
"""),
            dict(case_id=case_id, recipient_id=recipient_id, currency=currency),
        )
        return tuple(rows.scalars())

    async def cases(self, *, limit, offset, session):
        rows = (
            (
                await _session(session).execute(
                    text("""
SELECT min(b.business_key) business_key,b.recipient_id,b.currency,m.case_id,
 COALESCE(sum(CASE WHEN m.movement_type='debt' THEN m.amount_minor
                  ELSE -m.amount_minor END),0) debt_minor
FROM financial_movements m JOIN financial_obligations b ON b.id=m.obligation_id
WHERE m.movement_type IN ('debt','recovery')
GROUP BY b.recipient_id,b.currency,m.case_id
HAVING sum(CASE WHEN m.movement_type='debt' THEN m.amount_minor
                ELSE -m.amount_minor END)>0
ORDER BY m.case_id,b.recipient_id,b.currency LIMIT :limit OFFSET :offset
"""),
                    dict(limit=limit, offset=offset),
                )
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows]

    async def observations(self, *, limit, offset, session):
        rows = (
            (
                await _session(session).execute(
                    select(
                        OBSERVATIONS,
                        select(APPLICATIONS.c.application_id)
                        .where(
                            APPLICATIONS.c.observation_id
                            == OBSERVATIONS.c.observation_id
                        )
                        .order_by(APPLICATIONS.c.obligation_id)
                        .limit(1)
                        .scalar_subquery()
                        .label("application_id"),
                    )
                    .order_by(
                        OBSERVATIONS.c.recorded_at.desc(),
                        OBSERVATIONS.c.observation_id,
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
            .mappings()
            .all()
        )
        return [
            dict(
                observation_id=row["observation_id"],
                recipient_id=row["recipient_id"],
                case_id=row["case_id"],
                amount_minor=row["amount_minor"],
                currency=row["currency"],
                proof_claimed=row["proof_claimed"],
                blocker=row["document"]["blocker"],
                bank_reference=row["document"]["bank_reference"],
                evidence_reference=row["document"]["evidence_reference"],
                recorded_at=row["recorded_at"],
                application_id=row["application_id"],
            )
            for row in rows
        ]

"""User locks, policy coordination and immutable temporal override facts."""

from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.application.financial_ports import ApprovedRateOverride
from ugc_bot.application.override_ports import (
    OverridePolicy,
    OverrideReceipt,
    OverrideState,
    OverrideUser,
    Side,
    canonical,
    result_from_payload,
    select_approval,
)
from ugc_bot.infrastructure.db.financial_lifecycle_models import (
    RateOverrideModel,
)
from ugc_bot.infrastructure.db.models import (
    FinancialPolicyVersionModel,
    UserModel,
)
from ugc_bot.infrastructure.db.override_models import COMMANDS, EVENTS


def _session(session: object) -> AsyncSession:
    if not isinstance(session, AsyncSession) or not session.in_transaction():
        raise ValueError("caller_transaction_required")
    return session


class SqlAlchemyRateOverrideRepository:
    async def lock_users(self, user_ids, *, session):
        db = _session(session)
        users = UserModel.__table__
        result = {}
        for uid in sorted(set(user_ids), key=str):
            row = (
                (
                    await db.execute(
                        select(
                            users.c.user_id,
                            users.c.status,
                            users.c.admin,
                            users.c.telegram_id,
                            users.c.max_id,
                        )
                        .where(users.c.user_id == uid)
                        .with_for_update(key_share=True)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is not None:
                result[uid] = OverrideUser(
                    row["user_id"],
                    row["status"],
                    row["admin"],
                    row["telegram_id"],
                    row["max_id"],
                )
        return result

    async def lock_policy(self, policy_version, operation_key, *, session):
        db = _session(session)
        # Global command-key replay coordination comes after every User barrier.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "rate-override-command:" + operation_key},
        )
        p = FinancialPolicyVersionModel.__table__
        row = (
            (
                await db.execute(
                    select(
                        p.c.version,
                        p.c.approved_by,
                        p.c.approved_at,
                        p.c.effective_from,
                    )
                    .where(p.c.version == policy_version)
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        return OverridePolicy(**row) if row is not None else None

    async def get_command(self, operation_key, *, session):
        row = (
            (
                await _session(session).execute(
                    select(COMMANDS).where(
                        COMMANDS.c.operation_key == operation_key
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return OverrideReceipt(
            row["operation_key"],
            row["payload_hash"],
            row["actor_id"],
            row["action"],
            row["reason"],
            row["recorded_at"],
            result_from_payload(row["result"]),
        )

    @staticmethod
    def _states_query():
        rates = RateOverrideModel.__table__
        versions = (
            select(func.max(EVENTS.c.version))
            .where(EVENTS.c.override_id == rates.c.override_id)
            .scalar_subquery()
        )
        cutoff = (
            select(func.min(EVENTS.c.effective_at))
            .where(
                EVENTS.c.override_id == rates.c.override_id,
                EVENTS.c.event_type.in_(("revoked", "superseded")),
            )
            .scalar_subquery()
        )
        # One statement sees approval and revocation under one MVCC snapshot.
        return select(
            rates,
            func.coalesce(versions, 1).label("version"),
            cutoff.label("revoked_at"),
        )

    @staticmethod
    def _state(row):
        approval = ApprovedRateOverride(
            **{
                column.name: row[column.name]
                for column in RateOverrideModel.__table__.c
            }
        )
        return OverrideState(approval, row["version"], row["revoked_at"])

    async def get(self, override_id, *, session):
        row = (
            (
                await _session(session).execute(
                    self._states_query().where(
                        RateOverrideModel.override_id == override_id
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return self._state(row) if row is not None else None

    async def list_scope(self, recipient_id, side, policy_version, *, session):
        rates = RateOverrideModel.__table__
        rows = (
            (
                await _session(session).execute(
                    self._states_query()
                    .where(
                        rates.c.recipient_id == recipient_id,
                        rates.c.side == side,
                        rates.c.policy_version == policy_version,
                    )
                    .order_by(rates.c.override_id)
                )
            )
            .mappings()
            .all()
        )
        return tuple(self._state(row) for row in rows)

    async def select_effective_override(
        self,
        recipient_id: UUID,
        side: Side,
        policy_version: str,
        as_of: datetime,
        *,
        session: object,
    ) -> ApprovedRateOverride | None:
        if side not in ("client", "creator"):
            raise ValueError("invalid_override_side")
        return select_approval(
            await self.list_scope(
                recipient_id, side, policy_version, session=session
            ),
            as_of,
        )

    async def persist(self, receipt, approvals, events, *, session):
        db = _session(session)
        values = asdict(receipt) | {"result": canonical(asdict(receipt.result))}
        created = await db.scalar(
            insert(COMMANDS)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[COMMANDS.c.operation_key])
            .returning(COMMANDS.c.operation_key)
        )
        stored = await self.get_command(receipt.operation_key, session=db)
        if stored is None or stored.payload_hash != receipt.payload_hash:
            raise ValueError("idempotency_payload_conflict")
        if created is None:
            return
        for approval in approvals:
            await db.execute(
                insert(RateOverrideModel.__table__).values(**asdict(approval))
            )
        for event in events:
            await db.execute(insert(EVENTS).values(**asdict(event)))

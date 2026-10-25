"""Current actor/subject authority and append-only manual analytics SQL."""

from sqlalchemy import insert, select, text

from ugc_bot.application.native_principal_ports import require_current_principal
from ugc_bot.infrastructure.db.campaign_analytics_models import (
    ACTIONS,
    COMMANDS,
    EVENTS,
    PILOTS,
    SOURCES,
)
from ugc_bot.infrastructure.db.campaign_review_models import DRAFTS
from ugc_bot.infrastructure.db.models import OrderModel, UserModel
from ugc_bot.infrastructure.db.repositories.campaigns import mapping
from ugc_bot.infrastructure.db.repositories.financial_items import _session


class SqlAlchemyCampaignAnalyticsRepository:
    async def snapshot(self, *, session):
        await _session(session).execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        )

    async def owner(self, subject_type, subject_id, *, session):
        db = _session(session)
        if subject_type == "campaign":
            return await db.scalar(
                select(DRAFTS.c.owner_id).where(
                    DRAFTS.c.campaign_id == subject_id
                )
            )
        if subject_type == "order":
            return await db.scalar(
                select(OrderModel.advertiser_id).where(
                    OrderModel.order_id == subject_id
                )
            )
        raise ValueError("analytics_subject_required")

    async def authorize(
        self,
        actor_id,
        subject_type,
        subject_id,
        *,
        admin,
        write,
        principal,
        session,
    ):
        db = _session(session)
        owner = await self.owner(subject_type, subject_id, session=session)
        if owner is None:
            raise LookupError("analytics_subject_not_found")
        if write:
            for uid in sorted({actor_id, owner}, key=str):
                await db.execute(
                    select(UserModel.user_id)
                    .where(UserModel.user_id == uid)
                    .with_for_update(read=True)
                )
            await db.execute(
                text("SELECT pg_advisory_xact_lock(2119754201,170434823)")
            )
            if (
                await self.owner(subject_type, subject_id, session=session)
                != owner
            ):
                raise ValueError("analytics_subject_changed")
        row = await mapping(
            db,
            select(
                UserModel.user_id,
                UserModel.admin,
                UserModel.status,
                UserModel.telegram_id,
                UserModel.max_id,
            ).where(UserModel.user_id == actor_id),
        )
        if row is None:
            raise PermissionError("analytics_current_actor_required")
        try:
            require_current_principal(
                principal,
                actor_id,
                row["user_id"],
                row["telegram_id"],
                row["max_id"],
            )
        except ValueError:
            raise PermissionError("analytics_current_actor_required") from None
        if (
            row["status"] != "active"
            or (admin and not row["admin"])
            or (not admin and actor_id != owner)
        ):
            raise PermissionError("analytics_current_actor_required")
        return owner

    async def command(self, actor_id, key, *, session):
        return await mapping(
            _session(session),
            select(COMMANDS).where(
                COMMANDS.c.actor_id == actor_id, COMMANDS.c.operation_key == key
            ),
        )

    async def save_command(self, values, *, session):
        await _session(session).execute(insert(COMMANDS).values(**values))

    async def source(self, source_id, *, session):
        row = await mapping(
            _session(session),
            select(SOURCES).where(SOURCES.c.source_id == source_id),
        )
        if row is None:
            raise LookupError("analytics_source_not_found")
        return row

    async def sources(self, subject_type=None, subject_id=None, *, session):
        statement = select(SOURCES).order_by(
            SOURCES.c.recorded_at, SOURCES.c.source_id
        )
        if subject_type is not None:
            statement = statement.where(
                SOURCES.c.subject_type == subject_type,
                SOURCES.c.subject_id == subject_id,
            )
        return [
            dict(row)
            for row in (await _session(session).execute(statement)).mappings()
        ]

    async def actions(self, *, session):
        return [
            dict(row)
            for row in (
                await _session(session).execute(select(ACTIONS))
            ).mappings()
        ]

    async def events(self, subject_type, subject_id, *, session):
        statement = (
            select(EVENTS)
            .join(SOURCES, EVENTS.c.source_id == SOURCES.c.source_id)
            .where(
                SOURCES.c.subject_type == subject_type,
                SOURCES.c.subject_id == subject_id,
            )
            .order_by(EVENTS.c.recorded_at, EVENTS.c.event_id)
        )
        return [
            dict(row)
            for row in (await _session(session).execute(statement)).mappings()
        ]

    async def external(
        self, source_name, account_label, external_event_id, *, session
    ):
        return await mapping(
            _session(session),
            select(EVENTS).where(
                EVENTS.c.source_name == source_name,
                EVENTS.c.account_label == account_label,
                EVENTS.c.external_event_id == external_event_id,
            ),
        )

    async def append(self, table, values, *, session):
        tables = {
            "source": SOURCES,
            "event": EVENTS,
            "action": ACTIONS,
            "pilot": PILOTS,
        }
        await _session(session).execute(insert(tables[table]).values(**values))

    async def pilots(self, *, session):
        return [
            dict(row)
            for row in (
                await _session(session).execute(select(PILOTS))
            ).mappings()
        ]

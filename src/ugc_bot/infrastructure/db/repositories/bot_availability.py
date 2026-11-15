"""Persist blocking events reported by the messengers."""

from datetime import datetime
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import Table, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ugc_bot.application.ports import TransactionManager
from ugc_bot.domain.enums import AuditAction, MessengerType
from ugc_bot.infrastructure.db.models import AuditLogModel, UserModel
from ugc_bot.infrastructure.db.repositories._shared import _get_async_session

BOT_UNAVAILABLE_EVENT = "bot_unavailable"


async def record_bot_unavailable(
    transactions: TransactionManager,
    *,
    platform: MessengerType,
    external_id: str,
    occurred_at: datetime,
) -> None:
    if not external_id:
        return
    external_column = (
        UserModel.telegram_id
        if platform == MessengerType.TELEGRAM
        else UserModel.max_id
    )
    async with transactions.transaction() as session:
        db = _get_async_session(session)
        audit = cast(Table, AuditLogModel.__table__)
        event_id = uuid5(
            NAMESPACE_URL,
            f"ugc:bot-unavailable:{platform}:{external_id}:{occurred_at.isoformat()}",
        )
        values = select(
            literal(event_id, type_=audit.c.id.type),
            literal(BOT_UNAVAILABLE_EVENT),
            UserModel.user_id,
            literal(AuditAction.CREATE, type_=audit.c.action.type),
            literal(
                {"platform": platform.value}, type_=audit.c.new_values.type
            ),
            literal(occurred_at, type_=audit.c.changed_at.type),
        ).where(external_column == external_id)
        insert = (
            sqlite_insert
            if db.get_bind().dialect.name == "sqlite"
            else pg_insert
        )
        await db.execute(
            insert(audit)
            .from_select(
                [
                    "id",
                    "entity_type",
                    "entity_id",
                    "action",
                    "new_values",
                    "changed_at",
                ],
                values,
                include_defaults=False,
            )
            .on_conflict_do_nothing(index_elements=[audit.c.id])
        )

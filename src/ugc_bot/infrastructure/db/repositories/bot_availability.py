"""Persist blocking events reported by the messengers."""

from datetime import datetime, timezone
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import Table, case, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.sql import ColumnElement

from ugc_bot.application.ports import TransactionManager
from ugc_bot.domain.enums import AuditAction, MessengerType, UserStatus
from ugc_bot.infrastructure.db.models import AuditLogModel, UserModel
from ugc_bot.infrastructure.db.repositories._shared import _get_async_session

BOT_UNAVAILABLE_EVENT = "bot_unavailable"
BOT_AVAILABLE_EVENT = "bot_available"


def creator_directory_status() -> ColumnElement[UserStatus]:
    """Read Telegram reachability while retaining the stored account status."""
    audit = AuditLogModel
    external_id = audit.new_values["telegram_id"].as_string()
    latest = (
        select(audit.entity_type)
        .where(
            audit.entity_id == UserModel.user_id,
            audit.entity_type.in_((BOT_UNAVAILABLE_EVENT, BOT_AVAILABLE_EVENT)),
            audit.new_values["platform"].as_string() == MessengerType.TELEGRAM,
            or_(external_id.is_(None), external_id == UserModel.telegram_id),
        )
        .order_by(
            audit.changed_at.desc(),
            audit.new_values["update_id"].as_integer().desc().nulls_last(),
            audit.id.desc(),
        )
        .limit(1)
        .correlate(UserModel)
        .scalar_subquery()
    )
    return case(
        (
            (UserModel.status != UserStatus.DELETED)
            & UserModel.telegram_id.is_not(None)
            & (latest == BOT_UNAVAILABLE_EVENT),
            literal(UserStatus.BOT_BLOCKED, type_=UserModel.status.type),
        ),
        else_=UserModel.status,
    )


async def record_bot_availability(
    transactions: TransactionManager,
    *,
    platform: MessengerType,
    external_id: str,
    occurred_at: datetime,
    available: bool = False,
    update_id: int | None = None,
    expected_user_id: UUID | None = None,
) -> bool:
    if not external_id:
        return False
    external_column = (
        UserModel.telegram_id
        if platform == MessengerType.TELEGRAM
        else UserModel.max_id
    )
    async with transactions.transaction() as session:
        db = _get_async_session(session)
        audit = cast(Table, AuditLogModel.__table__)
        event_type = BOT_AVAILABLE_EVENT if available else BOT_UNAVAILABLE_EVENT
        event_key = (
            f"ugc:{event_type.replace('_', '-')}:{platform}:"
            f"{external_id}:{occurred_at.isoformat()}"
        )
        details: dict[str, str | int] = {"platform": platform.value}
        if platform == MessengerType.TELEGRAM:
            details["telegram_id"] = external_id
        if update_id is not None:
            event_key = f"{event_key}:{update_id}"
            details["update_id"] = update_id
        event_id = uuid5(NAMESPACE_URL, event_key)
        values = select(
            literal(event_id, type_=audit.c.id.type),
            literal(event_type),
            UserModel.user_id,
            literal(AuditAction.CREATE, type_=audit.c.action.type),
            literal(details, type_=audit.c.new_values.type),
            literal(occurred_at, type_=audit.c.changed_at.type),
        ).where(external_column == external_id)
        if expected_user_id is not None:
            values = values.where(UserModel.user_id == expected_user_id)
        insert = (
            sqlite_insert
            if db.get_bind().dialect.name == "sqlite"
            else pg_insert
        )
        result = await db.execute(
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
            .returning(audit.c.id)
        )
        return result.scalar_one_or_none() is not None


async def record_telegram_send_block(
    transactions: TransactionManager, external_id: str
) -> None:
    """Record Telegram's explicit rejection of a private message."""
    await record_bot_availability(
        transactions,
        platform=MessengerType.TELEGRAM,
        external_id=external_id,
        occurred_at=datetime.now(timezone.utc).replace(microsecond=0),
    )

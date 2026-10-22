"""Task18 caller-owned storage. No commits, balances, or bank confirmations."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, fields
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import RowMapping, Table, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.application.financial_ports import JournalMovement
from ugc_bot.domain.financial import utc
from ugc_bot.infrastructure.db import models as _models  # noqa: F401
from ugc_bot.infrastructure.db.base import Base


def _session(session: object) -> AsyncSession:
    if not isinstance(session, AsyncSession) or not session.in_transaction():
        raise ValueError("caller_transaction_required")
    return session


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return utc(value).isoformat(timespec="microseconds")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(v) for v in value]
    return value


def payload_hash(payload: Mapping[str, Any]) -> str:
    economic = {
        k: v
        for k, v in payload.items()
        if k not in {"id", "recorded_at", "payload_hash"}
    }
    encoded = json.dumps(
        _canonical(economic),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


class SqlAlchemyFinancialLedgerRepository:
    async def _insert(
        self,
        table: Table,
        key: str,
        payload: dict[str, Any],
        *,
        session: object,
    ) -> RowMapping:
        db = _session(session)
        payload = payload | {"payload_hash": payload_hash(payload)}
        payload.setdefault("id", uuid4())
        await db.execute(
            insert(table)
            .values(**payload)
            .on_conflict_do_nothing(index_elements=[key])
        )
        row = (
            (
                await db.execute(
                    select(table).where(table.c[key] == payload[key])
                )
            )
            .mappings()
            .one()
        )
        if row["payload_hash"] != payload["payload_hash"]:
            raise ValueError("idempotency_payload_conflict")
        return row

    async def append(
        self, movement: JournalMovement, *, session: object
    ) -> JournalMovement:
        table = Base.metadata.tables["financial_movements"]
        row = await self._insert(
            table, "operation_key", asdict(movement), session=session
        )
        return self._movement(row)

    @staticmethod
    def _movement(row: RowMapping) -> JournalMovement:
        return JournalMovement(
            **{field.name: row[field.name] for field in fields(JournalMovement)}
        )

    async def list_for_recipient(
        self, recipient_id: UUID, currency: str, *, session: object
    ) -> tuple[JournalMovement, ...]:
        if currency != "RUB":
            raise ValueError("unpublished_currency")
        movement = Base.metadata.tables["financial_movements"]
        basis = Base.metadata.tables["financial_obligations"]
        rows = (
            await _session(session).execute(
                select(movement)
                .join(basis, movement.c.obligation_id == basis.c.id)
                .where(
                    basis.c.recipient_id == recipient_id,
                    movement.c.currency == currency,
                )
                .order_by(movement.c.recorded_at, movement.c.id)
            )
        ).mappings()
        return tuple(self._movement(row) for row in rows)

    async def add_obligation(
        self, payload: Mapping[str, Any], *, session: object
    ) -> RowMapping:
        data = dict(payload)
        data["kind"] = {
            "client": "client_referral",
            "creator": "creator_referral",
        }.get(data["kind"], data["kind"])
        return await self._insert(
            Base.metadata.tables["financial_obligations"],
            "business_key",
            data,
            session=session,
        )

    async def add_rate_snapshot(
        self, payload: Mapping[str, Any], *, session: object
    ) -> RowMapping:
        return await self._insert(
            Base.metadata.tables["rate_snapshots"],
            "id",
            dict(payload),
            session=session,
        )

    async def add_audit_event(
        self, payload: Mapping[str, Any], *, session: object
    ) -> RowMapping:
        return await self._insert(
            Base.metadata.tables["financial_audit_events"],
            "operation_key",
            dict(payload),
            session=session,
        )

    async def lock_recipients(
        self, recipient_ids: tuple[UUID, ...], *, session: object
    ) -> None:
        db = _session(session)
        users = Base.metadata.tables["users"]
        for recipient in sorted(set(recipient_ids), key=str):
            row = await db.scalar(
                select(users.c.user_id)
                .where(users.c.user_id == recipient)
                .with_for_update(key_share=True)
            )
            if row is None:
                raise ValueError("recipient_not_found")

    async def lock_wallets(
        self, keys: tuple[tuple[UUID, str], ...], *, session: object
    ) -> None:
        db = _session(session)
        keys = tuple(sorted(set(keys), key=lambda key: (str(key[0]), key[1])))
        if any(currency != "RUB" for _, currency in keys):
            raise ValueError("unpublished_currency")
        await self.lock_recipients(tuple(user for user, _ in keys), session=db)
        table = Base.metadata.tables["financial_wallets"]
        for recipient, currency in keys:
            await db.execute(
                insert(table)
                .values(recipient_id=recipient, currency=currency)
                .on_conflict_do_nothing()
            )
            await db.execute(
                select(table)
                .where(
                    table.c.recipient_id == recipient,
                    table.c.currency == currency,
                )
                .with_for_update()
            )

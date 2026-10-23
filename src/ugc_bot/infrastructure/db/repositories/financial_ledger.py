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

from ugc_bot.application.financial_ports import (
    IssueBasis,
    IssuedObligation,
    JournalMovement,
    ObligationBasis,
    PotentialBasis,
)
from ugc_bot.domain.financial import first_anniversary, utc
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
    async def save_potential(
        self,
        basis: IssueBasis,
        reason: str,
        *,
        recorded_at: datetime,
        session: object,
    ) -> PotentialBasis:
        row = await self.add_audit_event(
            dict(
                id=uuid4(),
                operation_key="potential:" + basis.business_key,
                action="potential_basis",
                scope="paid_item:" + str(basis.paid_item_id),
                reason=reason,
                actor_id=basis.actor_id,
                actor_kind="user",
                system_actor=None,
                obligation_id=None,
                movement_id=None,
                effective_at=basis.snapshot_at,
                recorded_at=recorded_at,
                details=_canonical(asdict(basis)),
            ),
            session=session,
        )
        return PotentialBasis(basis, reason, row["recorded_at"], row["id"])

    async def lock_item(self, item_id: UUID, *, session: object) -> None:
        item = Base.metadata.tables["order_items"]
        row = await _session(session).scalar(
            select(item.c.paid_item_id)
            .where(item.c.paid_item_id == item_id)
            .with_for_update()
        )
        if row is None:
            raise ValueError("paid_item_not_found")

    async def get_issue(
        self, key: str, *, session: object
    ) -> IssuedObligation | None:
        db = _session(session)
        obligations = Base.metadata.tables["financial_obligations"]
        snapshots = Base.metadata.tables["rate_snapshots"]
        movements = Base.metadata.tables["financial_movements"]
        row = (
            (
                await db.execute(
                    select(obligations).where(obligations.c.business_key == key)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        rate = (
            (
                await db.execute(
                    select(snapshots).where(
                        snapshots.c.id == row["snapshot_id"]
                    )
                )
            )
            .mappings()
            .one()
        )
        journal = (
            (
                await db.execute(
                    select(movements).where(
                        movements.c.operation_key == "issue:" + key
                    )
                )
            )
            .mappings()
            .one()
        )
        movement = self._movement(journal)
        if movement.actor_id is None:
            raise ValueError("unsupported_system_issuance")
        basis = IssueBasis(
            business_key=key,
            kind=row["kind"],
            recipient_id=row["recipient_id"],
            paid_item_id=row["paid_item_id"],
            order_id=row["order_id"],
            assignment_id=row["assignment_id"],
            referred_user_id=rate["referred_user_id"],
            payment_id=rate["payment_id"],
            currency=row["currency"],
            base_minor=row["base_minor"],
            rate_bps=rate["rate_bps"],
            policy_version=row["policy_version"],
            snapshot_at=rate["effective_at"],
            registered_at=rate["registered_at"],
            verified_count=rate["verified_count"],
            event_id=movement.event_id,
            reason=movement.reason,
            actor_id=movement.actor_id,
            available_at=row["available_at"],
        )
        return IssuedObligation(row["id"], rate["id"], basis, movement)

    @staticmethod
    def _snapshot_age_rule(basis: IssueBasis) -> str:
        if basis.kind == "management":
            return "management"
        assert basis.registered_at is not None
        return (
            "first_year"
            if basis.snapshot_at < first_anniversary(basis.registered_at)
            else "after_anniversary"
        )

    async def save_issue(
        self, record: IssuedObligation, *, session: object
    ) -> IssuedObligation:
        basis = record.basis
        scope = dict(
            recipient_id=basis.recipient_id,
            paid_item_id=basis.paid_item_id,
            order_id=basis.order_id,
            assignment_id=basis.assignment_id,
            currency=basis.currency,
            policy_version=basis.policy_version,
        )
        await self.add_rate_snapshot(
            dict(
                scope,
                id=record.snapshot_id,
                referred_user_id=basis.referred_user_id,
                payment_id=basis.payment_id,
                side={
                    "client_referral": "client",
                    "creator_referral": "creator",
                    "management": "management",
                }[basis.kind],
                effective_at=basis.snapshot_at,
                registered_at=basis.registered_at,
                age_rule=self._snapshot_age_rule(basis),
                verified_count=basis.verified_count,
                rate_bps=basis.rate_bps,
            ),
            session=session,
        )
        await self.add_obligation(
            dict(
                scope,
                id=record.obligation_id,
                business_key=basis.business_key,
                kind=basis.kind,
                base_minor=basis.base_minor,
                amount_minor=record.movement.amount_minor,
                snapshot_id=record.snapshot_id,
                hold_until=basis.available_at,
                available_at=basis.available_at,
                recorded_at=record.movement.recorded_at,
            ),
            session=session,
        )
        return record

    async def apply_projection(
        self, movement: JournalMovement, *, session: object
    ) -> None:
        from sqlalchemy import update

        wallet = Base.metadata.tables["financial_wallets"]
        obligations = Base.metadata.tables["financial_obligations"]
        recipient = await _session(session).scalar(
            select(obligations.c.recipient_id).where(
                obligations.c.id == movement.obligation_id
            )
        )
        values: dict[str, Any] = {"version": wallet.c.version + 1}
        if movement.bucket_from:
            name = movement.bucket_from + "_minor"
            values[name] = wallet.c[name] - movement.amount_minor
        if movement.bucket_to:
            name = movement.bucket_to + "_minor"
            values[name] = wallet.c[name] + movement.amount_minor
        await _session(session).execute(
            update(wallet)
            .where(
                wallet.c.recipient_id == recipient,
                wallet.c.currency == movement.currency,
            )
            .values(**values)
        )

    async def list_obligation_bases(
        self, recipient_id: UUID, currency: str, *, session: object
    ) -> tuple[ObligationBasis, ...]:
        table = Base.metadata.tables["financial_obligations"]
        rows = (
            await _session(session).execute(
                select(table).where(
                    table.c.recipient_id == recipient_id,
                    table.c.currency == currency,
                )
            )
        ).mappings()
        return tuple(
            ObligationBasis(
                row["id"],
                row["recipient_id"],
                row["currency"],
                row["amount_minor"],
            )
            for row in rows
        )

    async def read_projection(
        self, recipient_id: UUID, currency: str, *, session: object
    ) -> dict[str, int]:
        wallet = Base.metadata.tables["financial_wallets"]
        row = (
            (
                await _session(session).execute(
                    select(wallet).where(
                        wallet.c.recipient_id == recipient_id,
                        wallet.c.currency == currency,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        buckets = (
            "pending",
            "hold",
            "available",
            "reserved",
            "paid",
            "cancelled",
            "blocked",
            "debt",
        )
        return {b: int(row[b + "_minor"]) if row else 0 for b in buckets}

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
        basis = Base.metadata.tables["financial_obligations"]
        recipient = await _session(session).scalar(
            select(basis.c.recipient_id).where(
                basis.c.id == movement.obligation_id
            )
        )
        if recipient is None:
            raise ValueError("obligation_not_found")
        # Allocate the durable sequence only after the shared writer barrier.
        # Sequence gaps (rollback/retry) are valid; caller clocks are not order.
        await self.lock_wallets(
            ((recipient, movement.currency),), session=session
        )
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
                .order_by(movement.c.append_order)
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

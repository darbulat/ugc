"""Storage guards reject unsupported commands without durable writes."""

import hashlib
import json
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.postgres_financial.test_financial_journal_service import (
    basis,
    item_seed,
    seed,
)
from ugc_bot.application.financial_ports import (
    IssuedObligation,
    JournalMovement,
)
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
    payload_hash,
)

__all__ = ["item_seed", "seed"]


async def durable_state(factory):
    names = (
        "orders",
        "payments",
        "order_items",
        "financial_obligations",
        "rate_snapshots",
        "financial_movements",
        "financial_wallets",
        "financial_audit_events",
    )
    async with factory.begin() as session:
        result = {}
        for name in names:
            table = Base.metadata.tables[name]
            rows = await session.execute(
                select(table).order_by(*table.primary_key.columns)
            )
            result[name] = tuple(dict(row) for row in rows.mappings())
        return result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "error"),
    [
        ("missing_item", "paid_item_not_found"),
        ("missing_recipient", "recipient_not_found"),
        ("wallet_currency", "unpublished_currency"),
        ("journal_currency", "unpublished_currency"),
        ("missing_obligation", "obligation_not_found"),
        ("no_transaction", "caller_transaction_required"),
    ],
)
async def test_repository_rejection_preserves_durable_state(
    financial_pg_engine, seed, operation, error
):
    repo = SqlAlchemyFinancialLedgerRepository()
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        before = await durable_state(factory)
        own_items = [
            row
            for row in before["order_items"]
            if row["paid_item_id"] == seed["item"]
        ]
        assert len(own_items) == 1
        with pytest.raises(ValueError, match=f"^{error}$"):
            if operation == "no_transaction":
                async with factory() as session:
                    assert not session.in_transaction()
                    try:
                        await repo.lock_wallets(
                            ((seed["user"], "RUB"),), session=session
                        )
                    finally:
                        assert not session.in_transaction()
            else:
                async with factory.begin() as session:
                    if operation == "missing_item":
                        await repo.lock_item(uuid4(), session=session)
                    elif operation == "missing_recipient":
                        await repo.lock_recipients((uuid4(),), session=session)
                    elif operation == "wallet_currency":
                        await repo.lock_wallets(
                            ((seed["user"], "USD"),), session=session
                        )
                    elif operation == "journal_currency":
                        await repo.list_for_recipient(
                            seed["user"], "USD", session=session
                        )
                    else:
                        await repo.append(
                            JournalMovement(
                                obligation_id=uuid4(),
                                operation_key="missing:" + str(uuid4()),
                                event_id="synthetic:missing-obligation",
                                movement_type="issuance",
                                amount_minor=5000,
                                currency="RUB",
                                effective_at=seed["now"],
                                recorded_at=seed["now"],
                                actor_id=seed["user"],
                                reason="rejected unknown obligation",
                                bucket_to="pending",
                            ),
                            session=session,
                        )
        assert await durable_state(factory) == before
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_system_issuance_is_not_reconstructed_as_user_issue(
    financial_pg_engine, seed
):
    repo = SqlAlchemyFinancialLedgerRepository()
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    command = basis(seed)
    obligation = uuid4()
    movement = JournalMovement(
        obligation_id=obligation,
        operation_key="issue:" + command.business_key,
        event_id=command.event_id,
        movement_type="issuance",
        amount_minor=5000,
        currency="RUB",
        effective_at=command.snapshot_at,
        recorded_at=seed["now"],
        actor_kind="system",
        actor_id=None,
        system_actor="synthetic_financial_system",
        reason=command.reason,
        bucket_to="pending",
    )
    try:
        async with factory.begin() as session:
            await repo.lock_wallets(((seed["user"], "RUB"),), session=session)
            await repo.save_issue(
                IssuedObligation(obligation, uuid4(), command, movement),
                session=session,
            )
            await repo.append(movement, session=session)
            await repo.apply_projection(movement, session=session)
        before = await durable_state(factory)
        assert (
            len(
                [
                    row
                    for row in before["financial_obligations"]
                    if row["id"] == obligation
                ]
            )
            == 1
        )
        assert (
            len(
                [
                    row
                    for row in before["financial_movements"]
                    if row["obligation_id"] == obligation
                ]
            )
            == 1
        )
        with pytest.raises(ValueError, match="^unsupported_system_issuance$"):
            async with factory.begin() as session:
                await repo.get_issue(command.business_key, session=session)
        assert await durable_state(factory) == before
        async with factory.begin() as session:
            assert await repo.list_for_recipient(
                seed["user"], "RUB", session=session
            ) == (movement,)
    finally:
        await engine.dispose()


def test_nested_economic_evidence_hash_keeps_order_and_identity():
    original = {
        "id": uuid4(),
        "details": {
            "receipts": [{"identity": "receipt:one", "scope": ("a", "b")}]
        },
    }
    expected = {
        "details": {
            "receipts": [{"identity": "receipt:one", "scope": ["a", "b"]}]
        }
    }
    encoded = json.dumps(
        expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert (
        payload_hash(original) == hashlib.sha256(encoded.encode()).hexdigest()
    )
    assert payload_hash(original) == payload_hash(expected | {"id": uuid4()})
    changed = {
        "details": {
            "receipts": [{"identity": "receipt:two", "scope": ["a", "b"]}]
        }
    }
    assert payload_hash(changed) != payload_hash(original)

"""Existing public ledger guards preserve committed private-PostgreSQL state."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.postgres_financial.test_financial_journal_service import (
    basis,
    item_seed,
    seed,
)
from ugc_bot.application.financial_ports import IssuedObligation, PotentialBasis
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
    PayloadConflict,
)
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)

__all__ = ["item_seed", "seed"]


def persisted_state(engine):
    """Every column of every actual table, including timestamps and versions.

    Read outside the command's transaction so rollback cannot hide a commit.
    Sequences are deliberately not included: rolled-back inserts may use IDs.
    """
    with engine.connect() as connection:
        names = inspect(connection).get_table_names()
        quote = connection.dialect.identifier_preparer.quote
        return {
            name: tuple(
                connection.scalars(
                    text(
                        f"SELECT row_to_json(t)::text FROM {quote(name)} AS t "
                        "ORDER BY 1"
                    )
                )
            )
            for name in names
        }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"rate_bps": 300}, "unapproved_referral_rate"),
        ({"registered_at": "future"}, "snapshot_before_registration"),
    ],
)
async def test_issue_rejected_assessment_preserves_all_tables(
    financial_pg_engine, seed, change, message
):
    repo = SqlAlchemyFinancialLedgerRepository()
    service = FinancialLedgerService(repo)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cmd = basis(seed)
    if change.get("registered_at") == "future":
        change = {"registered_at": cmd.snapshot_at + timedelta(seconds=1)}
    # The existing committed obligation is a nonempty preservation control;
    # the rejected attempt has a distinct business identity.
    try:
        async with factory.begin() as session:
            issued = await service.issue(
                cmd, recorded_at=seed["now"], session=session
            )
            assert isinstance(issued, IssuedObligation)
        before = persisted_state(financial_pg_engine)
        with pytest.raises(ValueError, match=f"^{message}$"):
            async with factory.begin() as session:
                await service.issue(
                    replace(
                        cmd,
                        business_key="rejected:" + cmd.business_key,
                        **change,
                    ),
                    recorded_at=seed["now"],
                    session=session,
                )
        assert persisted_state(financial_pg_engine) == before
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing", ["policy_version", "rate_bps", "rounded_zero"]
)
async def test_unresolved_policy_is_durable_nonmonetary_and_conflicts_rollback(
    financial_pg_engine, seed, missing
):
    repo = SqlAlchemyFinancialLedgerRepository()
    service = FinancialLedgerService(repo)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cmd = replace(
        basis(seed),
        **({"base_minor": 1} if missing == "rounded_zero" else {missing: None}),
    )
    try:
        async with factory.begin() as session:
            saved = await service.issue(
                cmd, recorded_at=seed["now"], session=session
            )
            assert isinstance(saved, PotentialBasis)
            assert saved.reason == (
                "rounded_commission_zero"
                if missing == "rounded_zero"
                else "snapshot_policy_unresolved"
            )
        before = persisted_state(financial_pg_engine)
        async with factory.begin() as session:
            assert (
                await service.issue(
                    cmd,
                    recorded_at=seed["now"] + timedelta(days=1),
                    session=session,
                )
                == saved
            )
            assert (
                await repo.get_issue(cmd.business_key, session=session) is None
            )
            assert (
                await repo.list_for_recipient(
                    cmd.recipient_id, "RUB", session=session
                )
                == ()
            )
            assert not any(
                (
                    await repo.read_projection(
                        cmd.recipient_id, "RUB", session=session
                    )
                ).values()
            )
        assert persisted_state(financial_pg_engine) == before
        with pytest.raises(PayloadConflict) as error:
            async with factory.begin() as session:
                await service.issue(
                    replace(cmd, reason="different assessment"),
                    recorded_at=seed["now"],
                    session=session,
                )
        assert error.value.operation_key == "potential:" + cmd.business_key
        assert error.value.audit_required
        assert persisted_state(financial_pg_engine) == before
        if missing == "rounded_zero":
            with pytest.raises(PayloadConflict):
                async with factory.begin() as session:
                    await service.issue(
                        replace(cmd, base_minor=50000),
                        recorded_at=seed["now"],
                        session=session,
                    )
            assert persisted_state(financial_pg_engine) == before
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["issue", "potential", "transfer"])
async def test_public_commands_require_caller_transaction(
    financial_pg_engine, seed, command
):
    repo = SqlAlchemyFinancialLedgerRepository()
    service = FinancialLedgerService(repo)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cmd = basis(seed)
    try:
        async with factory.begin() as session:
            issued = await service.issue(
                cmd, recorded_at=seed["now"], session=session
            )
            assert isinstance(issued, IssuedObligation)
        before = persisted_state(financial_pg_engine)
        async with factory() as session:
            assert not session.in_transaction()
            with pytest.raises(
                ValueError, match="^caller_transaction_required$"
            ):
                if command == "transfer":
                    await service.transfer(
                        cmd.business_key,
                        issued.movement,
                        now=seed["now"],
                        session=session,
                    )
                else:
                    await service.issue(
                        replace(cmd, policy_version=None)
                        if command == "potential"
                        else cmd,
                        recorded_at=seed["now"],
                        session=session,
                    )
            assert not session.in_transaction()
        assert persisted_state(financial_pg_engine) == before
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        ("missing", "obligation_not_found"),
        ("scope", "movement_scope_mismatch"),
        ("payload", "idempotency_payload_conflict"),
        ("transition", "unsupported_bucket_transition"),
        ("movement_type", "unsupported_bucket_transition"),
        ("case", "block_case_required"),
        ("immature", "hold_not_mature"),
        ("unscheduled", "hold_not_mature"),
        ("balance", "insufficient_bucket_balance"),
        ("journal", "reconciliation_mismatch_audit_required"),
    ],
)
async def test_transfer_rejection_preserves_full_persisted_history(
    financial_pg_engine, seed, scenario, message
):
    repo = SqlAlchemyFinancialLedgerRepository()
    service = FinancialLedgerService(repo)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cmd = basis(seed)
    if scenario == "unscheduled":
        cmd = replace(cmd, available_at=None)
    try:
        async with factory.begin() as session:
            issued = await service.issue(
                cmd, recorded_at=seed["now"], session=session
            )
            assert isinstance(issued, IssuedObligation)
            hold = replace(
                issued.movement,
                operation_key="hold:" + cmd.business_key,
                movement_type="transfer",
                bucket_from="pending",
                bucket_to="hold",
            )
            await service.transfer(
                cmd.business_key, hold, now=seed["now"], session=session
            )
            if scenario == "journal":
                # Legal append-only insertion of an extra issuance; no trigger
                # bypass or journal mutation. Match the projection deliberately.
                extra = replace(
                    issued.movement, operation_key="extra:" + cmd.business_key
                )
                await repo.append(extra, session=session)
                await repo.apply_projection(extra, session=session)
        movement = replace(
            hold,
            operation_key="release:" + cmd.business_key,
            bucket_from="hold",
            bucket_to="available",
        )
        key = cmd.business_key
        now = seed["now"] + timedelta(days=20)
        if scenario == "missing":
            key = "missing:" + key
        elif scenario == "scope":
            movement = replace(movement, obligation_id=uuid4())
        elif scenario == "payload":
            movement = replace(hold, amount_minor=hold.amount_minor - 1)
        elif scenario == "transition":
            movement = replace(movement, bucket_to="pending")
        elif scenario == "movement_type":
            movement = replace(
                issued.movement, operation_key=movement.operation_key
            )
        elif scenario == "case":
            movement = replace(movement, bucket_to="blocked")
        elif scenario == "immature":
            now = seed["now"]
        elif scenario == "balance":
            movement = replace(movement, amount_minor=hold.amount_minor + 1)
        before = persisted_state(financial_pg_engine)
        with pytest.raises(ValueError, match=f"^{message}$") as error:
            async with factory.begin() as session:
                await service.transfer(key, movement, now=now, session=session)
        if scenario == "payload":
            assert isinstance(error.value, PayloadConflict)
            assert error.value.operation_key == hold.operation_key
            assert error.value.audit_required
        assert persisted_state(financial_pg_engine) == before
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"available_at": "early"}, "availability_before_snapshot"),
        ({"business_key": " "}, "basis_provenance_required"),
        ({"event_id": " "}, "basis_provenance_required"),
        ({"reason": " "}, "basis_provenance_required"),
        ({"kind": "other"}, "invalid_referral_kind"),
        ({"kind": "creator_referral"}, "creator_assignment_required"),
        ({"currency": "USD"}, "unpublished_currency"),
        ({"base_minor": 0}, "positive_base_required"),
        ({"base_minor": True}, "positive_base_required"),
        ({"verified_count": -1}, "invalid_verified_count"),
        ({"verified_count": True}, "invalid_verified_count"),
        ({"policy_version": " "}, "invalid_policy_version"),
        ({"actor_id": UUID(int=0)}, "invalid_basis_reference"),
    ],
)
def test_basis_validation_rejects_before_command_construction(
    financial_pg_engine, seed, change, message
):
    cmd = basis(seed)
    if change.get("available_at") == "early":
        change = {"available_at": cmd.snapshot_at - timedelta(seconds=1)}
    before = persisted_state(financial_pg_engine)
    with pytest.raises(ValueError, match=f"^{message}$"):
        replace(cmd, **change)
    assert persisted_state(financial_pg_engine) == before

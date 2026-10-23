"""Existing replay guards via public APIs; no malformed persistence writes."""

import os
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.application.services.test_financial_ledger_service import command
from tests.helpers.financial_environment import isolated_financial_database
from tests.postgres_financial.test_financial_journal_service import (
    basis,
    item_seed,
    seed,
)
from ugc_bot.application.financial_ports import (
    IssuedObligation,
    JournalMovement,
    ObligationBasis,
)
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.application.services.financial_reconciliation_service import (
    BUCKETS,
    FinancialReconciliationService,
    replay_journal,
)
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)

__all__ = ["item_seed", "seed"]


@pytest.fixture
def issuance():
    cmd = command()
    return JournalMovement(
        obligation_id=uuid4(),
        operation_key="initial",
        event_id=cmd.event_id,
        movement_type="issuance",
        amount_minor=5000,
        currency="RUB",
        effective_at=cmd.snapshot_at,
        recorded_at=cmd.snapshot_at,
        actor_id=cmd.actor_id,
        reason=cmd.reason,
        bucket_to="pending",
    )


def test_operation_retry_ignores_recording_time_but_not_payload(issuance):
    retry = replace(
        issuance, recorded_at=issuance.recorded_at + timedelta(days=1)
    )
    clean = replay_journal((issuance, retry), currency="RUB")
    assert clean.errors == () and clean.balanced
    assert clean.gross == clean.unpaid == 5000
    conflict = replace(retry, amount_minor=4999)
    bad = replay_journal((issuance, conflict), currency="RUB")
    assert bad.errors == ("operation_payload_conflict:initial",)
    assert not bad.balanced
    assert bad.balances == clean.balances and bad.gross == clean.gross


def test_replay_currency_is_validated_even_without_entries():
    assert replay_journal((), currency="RUB").balanced
    with pytest.raises(ValueError, match="^unpublished_currency$"):
        replay_journal((), currency="USD")


@pytest.mark.parametrize(
    ("source", "target", "errors"),
    [
        ("pending", "cancelled", ()),
        ("paid", "cancelled", ("invalid_reversal_buckets",)),
        ("pending", "hold", ("invalid_reversal_buckets",)),
        (
            "pending",
            "reserved",
            ("invalid_reversal_buckets", "allocation_references_required"),
        ),
    ],
)
def test_reversal_buckets_and_missing_allocation_references(
    issuance, source, target, errors
):
    correction = replace(
        issuance,
        operation_key="reverse",
        movement_type="reversal",
        amount_minor=1000,
        bucket_from=source,
        bucket_to=target,
        source_entry_id=uuid4(),
    )
    result = replay_journal((issuance, correction), currency="RUB")
    assert result.errors == errors
    assert result.balanced is (not errors)
    assert result.reversed == (0 if errors else 1000)
    assert result.balances["pending"] == (5000 if errors else 4000)
    assert result.balances["cancelled"] == (0 if errors else 1000)


@pytest.mark.parametrize("kind", ["debt", "recovery"])
@pytest.mark.parametrize("side", ["bucket_from", "bucket_to"])
def test_correction_with_buckets_is_reported_without_changing_money(
    issuance, kind, side
):
    correction = replace(
        issuance,
        operation_key=kind,
        movement_type=kind,
        bucket_from="hold" if side == "bucket_from" else None,
        bucket_to="hold" if side == "bucket_to" else None,
        source_entry_id=uuid4(),
        case_id=uuid4(),
    )
    result = replay_journal((issuance, correction), currency="RUB")
    assert result.errors == (f"invalid_{kind}_buckets",)
    assert not result.balanced
    assert (
        result.balances == replay_journal((issuance,), currency="RUB").balances
    )
    assert (result.reversed, result.recovered, result.debt) == (0, 0, 0)


def test_paid_without_reserve_preserves_paid_but_blocks_readiness(issuance):
    request, allocation = uuid4(), uuid4()
    paid = replace(
        issuance,
        operation_key="paid",
        movement_type="transfer",
        bucket_from="pending",
        bucket_to="paid",
        request_id=request,
        allocation_id=allocation,
        execution_id=uuid4(),
    )
    result = replay_journal((issuance, paid), currency="RUB")
    assert result.errors == (
        "paid_without_reserve",
        f"allocation_without_reserve:{allocation}",
    )
    assert not result.balanced
    assert result.paid == result.gross == 5000 and result.unpaid == 0
    assert result.allocations == {(request, allocation): 0}
    assert result.allocation_paid == {(request, allocation): 5000}


def test_recovery_cannot_borrow_debt_from_another_case(issuance):
    request, allocation, case = uuid4(), uuid4(), uuid4()
    reserve = replace(
        issuance,
        operation_key="reserve",
        movement_type="transfer",
        bucket_from="pending",
        bucket_to="reserved",
        request_id=request,
        allocation_id=allocation,
    )
    paid = replace(
        reserve,
        operation_key="paid",
        bucket_from="reserved",
        bucket_to="paid",
        execution_id=uuid4(),
    )
    debt = replace(
        issuance,
        operation_key="debt",
        movement_type="debt",
        bucket_to=None,
        source_entry_id=uuid4(),
        case_id=case,
    )
    recovery = replace(debt, operation_key="recovery", movement_type="recovery")
    history = (issuance, reserve, paid, debt)
    clean = replay_journal((*history, recovery), currency="RUB")
    assert clean.errors == () and clean.balanced
    assert (clean.paid, clean.reversed, clean.recovered, clean.debt) == (
        5000,
        5000,
        5000,
        0,
    )
    wrong_case = replay_journal(
        (*history, replace(recovery, case_id=uuid4())), currency="RUB"
    )
    assert wrong_case.errors == ("recovery_exceeds_case_debt",)
    assert wrong_case.balances == clean.balances and not wrong_case.balanced
    excess = replay_journal(
        (*history, replace(recovery, amount_minor=5001)), currency="RUB"
    )
    assert excess.errors == (
        "recovery_exceeds_case_debt",
        f"negative_obligation_bucket:{issuance.obligation_id}",
    )
    assert excess.debt == -1 and not excess.balanced


class BasisReadContract:
    """Read-port DTO fixture, not an assertion about possible SQL rows."""

    def __init__(self, recipient, issuance, bases, session):
        self.recipient = recipient
        self.issuance = issuance
        self.bases = bases
        self.session = session
        self.calls = []

    async def lock_wallets(self, keys, *, session):
        assert keys == ((self.recipient, "RUB"),)
        assert session is self.session
        self.calls.append("lock")

    async def list_obligation_bases(self, recipient, currency, *, session):
        self._read("bases", recipient, currency, session)
        return self.bases

    async def list_for_recipient(self, recipient, currency, *, session):
        self._read("entries", recipient, currency, session)
        return (self.issuance,)

    async def read_projection(self, recipient, currency, *, session):
        self._read("projection", recipient, currency, session)
        return dict.fromkeys(BUCKETS, 0) | {"pending": 5000}

    def _read(self, name, recipient, currency, session):
        assert (recipient, currency) == (self.recipient, "RUB")
        assert session is self.session and self.calls[-1] != "projection"
        self.calls.append(name)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "damage", ["none", "duplicate", "recipient", "currency", "zero", "bool"]
)
async def test_basis_read_contract_gates_matching_projection(issuance, damage):
    recipient, session = uuid4(), object()
    authoritative = ObligationBasis(
        issuance.obligation_id, recipient, "RUB", 5000
    )
    bases = (authoritative,)
    if damage == "duplicate":
        bases = (authoritative, authoritative)
    elif damage == "recipient":
        bases = (replace(authoritative, recipient_id=uuid4()),)
    elif damage == "currency":
        bases = (replace(authoritative, currency="USD"),)
    elif damage == "zero":
        bases = (replace(authoritative, amount_minor=0),)
    elif damage == "bool":
        bases = (replace(authoritative, amount_minor=True),)
    repo = BasisReadContract(recipient, issuance, bases, session)
    service = FinancialReconciliationService(repo)
    report = await service.reconcile(recipient, "RUB", session=session)
    expected = ()
    if damage == "duplicate":
        expected = ("duplicate_obligation_basis",)
    elif damage != "none":
        expected = (f"invalid_obligation_basis:{issuance.obligation_id}",)
        if damage in ("zero", "bool"):
            expected += (f"issuance_amount:{issuance.obligation_id}",)
    assert report.replay.errors == expected
    assert report.differences == {}
    assert report.payout_ready is (damage == "none")
    assert report.audit_required is (damage != "none")
    assert repo.calls == ["lock", "bases", "entries", "projection"]
    if damage == "none":
        assert (
            await service.require_ready(recipient, "RUB", session=session)
            == report
        )
    else:
        with pytest.raises(
            ValueError, match="^reconciliation_mismatch_audit_required$"
        ):
            await service.require_ready(recipient, "RUB", session=session)
    assert repo.calls == ["lock", "bases", "entries", "projection"] * 2


@pytest.fixture(scope="module")
def financial_pg_engine():
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires owned isolated financial PostgreSQL database")
    with isolated_financial_database(url) as engine:
        yield engine


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.timeout(120)
async def test_persisted_missing_projection_requires_audit_without_repair(
    financial_pg_engine, seed
):
    repo = SqlAlchemyFinancialLedgerRepository()
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cmd = basis(seed)
    check = FinancialReconciliationService(repo)
    try:
        async with factory.begin() as session:
            issued = await FinancialLedgerService(repo).issue(
                cmd, recorded_at=seed["now"], session=session
            )
            assert isinstance(issued, IssuedObligation)
            clean = await check.require_ready(
                seed["user"], "RUB", session=session
            )
            assert clean.replay.errors == () and clean.differences == {}
            # Legal immutable append, intentionally omit its mutable projection.
            extra = replace(
                issued.movement,
                operation_key="hold:" + cmd.business_key,
                movement_type="transfer",
                bucket_from="pending",
                bucket_to="hold",
                amount_minor=1000,
            )
            await repo.append(extra, session=session)
        with pytest.raises(
            ValueError, match="^reconciliation_mismatch_audit_required$"
        ):
            async with factory.begin() as session:
                report = await check.reconcile(
                    seed["user"], "RUB", session=session
                )
                assert report.replay.errors == () and report.replay.balanced
                assert report.differences == {
                    "pending": (4000, 5000),
                    "hold": (1000, 0),
                }
                assert report.audit_required and not report.payout_ready
                await check.require_ready(seed["user"], "RUB", session=session)
        async with factory.begin() as session:
            assert await repo.list_for_recipient(
                seed["user"], "RUB", session=session
            ) == (issued.movement, extra)
            projection = await repo.read_projection(
                seed["user"], "RUB", session=session
            )
            assert projection["pending"] == 5000 and projection["hold"] == 0
            assert (
                await check.reconcile(seed["user"], "RUB", session=session)
                == report
            )
    finally:
        await engine.dispose()

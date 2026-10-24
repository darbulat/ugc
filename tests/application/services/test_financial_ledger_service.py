"""Vertical service tests; the fake is not a PostgreSQL substitute."""

import importlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from ugc_bot.application import financial_ports as ports


def api():
    assert hasattr(ports, "IssueBasis"), "typed issue command missing"
    return importlib.import_module(
        "ugc_bot.application.services.financial_ledger_service"
    )


def command():
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    return ports.IssueBasis(
        business_key="item:client",
        kind="client_referral",
        recipient_id=uuid4(),
        paid_item_id=uuid4(),
        order_id=uuid4(),
        assignment_id=None,
        referred_user_id=uuid4(),
        payment_id=uuid4(),
        currency="RUB",
        base_minor=50000,
        rate_bps=1000,
        policy_version="approved:test",
        snapshot_at=now,
        registered_at=now - timedelta(days=5),
        verified_count=0,
        event_id="capture:1",
        reason="trusted capture",
        actor_id=uuid4(),
        available_at=now + timedelta(days=15),
    )


@pytest.mark.asyncio
async def test_client_issue_does_not_fabricate_a_creator_grade():
    basis = replace(command(), verified_count=None)
    result = (
        await api()
        .FinancialLedgerService(MemoryLedger())
        .issue(basis, recorded_at=basis.snapshot_at, session=object())
    )
    assert isinstance(result, ports.IssuedObligation)
    assert result.basis.verified_count is None
    assert result.movement.amount_minor == 5000


class MemoryLedger:
    def __init__(self):
        self.potentials = {}
        self.records = {}
        self.bases = {}
        self.movements = {}
        self.active_grounds = {}
        self.wallet = {
            b: 0
            for b in (
                "pending",
                "hold",
                "available",
                "reserved",
                "paid",
                "cancelled",
                "blocked",
                "debt",
            )
        }

    async def save_potential(self, basis, reason, *, recorded_at, session):
        if basis.business_key in self.potentials:
            result = self.potentials[basis.business_key]
            if result.basis != basis or result.reason != reason:
                raise ValueError("idempotency_payload_conflict")
            return result
        result = ports.PotentialBasis(basis, reason, recorded_at, uuid4())
        self.potentials[basis.business_key] = result
        return result

    async def lock_recipients(self, recipient_ids, *, session):
        pass

    async def lock_wallets(self, keys, *, session):
        assert session is not None

    async def lock_item(self, item_id, *, session):
        pass

    async def get_issue(self, key, *, session):
        return self.records.get(key)

    async def get_active_ground(self, item_id, kind, *, session):
        return self.active_grounds.get((item_id, kind))

    async def list_item_grounds(self, item_id, kind, *, session):
        return tuple(
            ports.ActiveEconomicGround(
                record.obligation_id,
                record.basis.business_key,
                record.basis.recipient_id,
                record.basis.currency,
                item_id,
                kind,
            )
            for record in self.records.values()
            if record.basis.paid_item_id == item_id
            and record.basis.kind == kind
        )

    async def set_active_ground(self, record, *, session):
        b = record.basis
        self.active_grounds[(b.paid_item_id, b.kind)] = (
            ports.ActiveEconomicGround(
                record.obligation_id,
                b.business_key,
                b.recipient_id,
                b.currency,
                b.paid_item_id,
                b.kind,
            )
        )

    async def get_maturity(self, obligation_id, *, session):
        return None

    async def save_issue(self, record, *, session):
        self.records[record.basis.business_key] = record
        from ugc_bot.domain.financial import commission_minor

        self.bases[record.obligation_id] = ports.ObligationBasis(
            record.obligation_id,
            record.basis.recipient_id,
            record.basis.currency,
            record.basis.base_minor
            if record.basis.kind == "management"
            else commission_minor(
                record.basis.base_minor,
                record.basis.rate_bps,
                record.basis.currency,
            ),
        )
        return record

    async def append(self, movement, *, session):
        prior = self.movements.get(movement.operation_key)
        if prior:
            assert replace(prior, recorded_at=movement.recorded_at) == movement
            return prior
        self.movements[movement.operation_key] = movement
        return movement

    async def apply_projection(self, movement, *, session):
        if movement.bucket_from:
            self.wallet[movement.bucket_from] -= movement.amount_minor
        if movement.bucket_to:
            self.wallet[movement.bucket_to] += movement.amount_minor

    async def list_for_recipient(self, recipient_id, currency, *, session):
        return tuple(self.movements.values())

    async def list_obligation_bases(self, recipient_id, currency, *, session):
        return tuple(
            basis
            for basis in self.bases.values()
            if basis.recipient_id == recipient_id and basis.currency == currency
        )

    async def read_projection(self, recipient_id, currency, *, session):
        return dict(self.wallet)


@pytest.mark.asyncio
async def test_issue_is_idempotent_by_business_key():
    module = api()
    repo = MemoryLedger()
    service = module.FinancialLedgerService(repo)
    cmd = command()
    session = object()
    first = await service.issue(
        cmd, recorded_at=cmd.snapshot_at, session=session
    )
    retry = await service.issue(
        cmd, recorded_at=cmd.snapshot_at + timedelta(days=1), session=session
    )
    assert retry == first
    creator = replace(
        cmd,
        business_key="item:creator",
        kind="creator_referral",
        assignment_id=uuid4(),
    )
    second = await service.issue(
        creator, recorded_at=cmd.snapshot_at, session=session
    )
    assert first.obligation_id != second.obligation_id
    assert len(repo.movements) == 2
    assert repo.wallet["pending"] == 10000
    with pytest.raises(module.PayloadConflict) as caught:
        await service.issue(
            replace(cmd, base_minor=40000),
            recorded_at=cmd.snapshot_at,
            session=session,
        )
    assert caught.value.audit_required
    assert len(repo.movements) == 2


@pytest.mark.asyncio
async def test_bucket_transfer_preserves_liability():
    module = api()
    repo = MemoryLedger()
    service = module.FinancialLedgerService(repo)
    cmd = command()
    session = object()
    issued = await service.issue(
        cmd, recorded_at=cmd.snapshot_at, session=session
    )
    assert hasattr(service, "transfer"), "bucket transfer command missing"
    move = ports.JournalMovement(
        obligation_id=issued.obligation_id,
        operation_key="hold:1",
        event_id="success:1",
        movement_type="transfer",
        amount_minor=5000,
        currency="RUB",
        effective_at=cmd.snapshot_at,
        recorded_at=cmd.snapshot_at,
        actor_id=cmd.actor_id,
        reason="confirmed success",
        bucket_from="pending",
        bucket_to="hold",
    )
    first = await service.transfer(
        cmd.business_key, move, now=cmd.snapshot_at, session=session
    )
    assert repo.wallet["pending"] == 0 and repo.wallet["hold"] == 5000
    assert (
        await service.transfer(
            cmd.business_key,
            replace(move, recorded_at=cmd.available_at),
            now=cmd.available_at,
            session=session,
        )
        == first
    )
    release = replace(
        move,
        operation_key="release:1",
        bucket_from="hold",
        bucket_to="available",
    )
    with pytest.raises(ValueError, match="hold_not_mature"):
        await service.transfer(
            cmd.business_key, release, now=cmd.snapshot_at, session=session
        )
    await service.transfer(
        cmd.business_key, release, now=cmd.available_at, session=session
    )
    assert repo.wallet["available"] == 5000
    assert (
        sum(
            m.amount_minor
            for m in repo.movements.values()
            if m.movement_type == "issuance"
        )
        == 5000
    )
    block = replace(
        move,
        operation_key="block:1",
        bucket_from="available",
        bucket_to="blocked",
        case_id=uuid4(),
    )
    await service.transfer(
        cmd.business_key, block, now=cmd.available_at, session=session
    )
    with pytest.raises(ValueError, match="insufficient_bucket_balance"):
        await service.transfer(
            cmd.business_key,
            replace(block, operation_key="block:2"),
            now=cmd.available_at,
            session=session,
        )
    assert repo.wallet["blocked"] == 5000


@pytest.mark.asyncio
async def test_partial_dispute_blocks_release_of_remaining_hold():
    module = api()
    repo = MemoryLedger()
    service = module.FinancialLedgerService(repo)
    cmd = command()
    session = object()
    issued = await service.issue(
        cmd, recorded_at=cmd.snapshot_at, session=session
    )
    move = ports.JournalMovement(
        obligation_id=issued.obligation_id,
        operation_key="hold",
        event_id="success",
        movement_type="transfer",
        amount_minor=5000,
        currency="RUB",
        effective_at=cmd.snapshot_at,
        recorded_at=cmd.snapshot_at,
        actor_id=cmd.actor_id,
        reason="success",
        bucket_from="pending",
        bucket_to="hold",
    )
    await service.transfer(
        cmd.business_key, move, now=cmd.snapshot_at, session=session
    )
    await service.transfer(
        cmd.business_key,
        replace(
            move,
            operation_key="partial-block",
            amount_minor=1000,
            bucket_from="hold",
            bucket_to="blocked",
            case_id=uuid4(),
        ),
        now=cmd.available_at,
        session=session,
    )
    with pytest.raises(ValueError, match="obligation_blocked"):
        await service.transfer(
            cmd.business_key,
            replace(
                move,
                operation_key="release",
                amount_minor=4000,
                bucket_from="hold",
                bucket_to="available",
            ),
            now=cmd.available_at,
            session=session,
        )
    assert repo.wallet["available"] == 0


@pytest.mark.asyncio
async def test_potential_basis_is_durable_idempotent_and_not_zero_income():
    module = api()
    repo = MemoryLedger()
    service = module.FinancialLedgerService(repo)
    cmd = replace(
        command(), recipient_id=None, rate_bps=None, policy_version=None
    )
    session = object()
    first = await service.issue(
        cmd, recorded_at=cmd.snapshot_at, session=session
    )
    second = await service.issue(
        cmd, recorded_at=cmd.snapshot_at + timedelta(days=1), session=session
    )
    assert first == second
    assert len(repo.potentials) == 1
    assert not repo.movements and not repo.records
    assert all(value == 0 for value in repo.wallet.values())
    with pytest.raises(module.PayloadConflict):
        await service.issue(
            replace(cmd, base_minor=40000),
            recorded_at=cmd.snapshot_at,
            session=session,
        )

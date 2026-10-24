"""Trusted maturity/override facts and one live assignment ground."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from tests.application.services.test_financial_ledger_service import command
from ugc_bot.application.financial_ports import JournalMovement
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)


def setup():
    try:
        from ugc_bot.application.financial_ports import (
            ApprovedRateOverride,
            WorkMaturitySource,
        )
        from ugc_bot.infrastructure.memory_financial_ledger import (
            InMemoryFinancialLedgerRepository,
        )
    except ImportError:
        pytest.fail("Trusted lifecycle-ledger extension contracts are missing")
    repo = InMemoryFinancialLedgerRepository()
    return (
        repo,
        FinancialLedgerService(repo),
        ApprovedRateOverride,
        WorkMaturitySource,
    )


@pytest.mark.asyncio
async def test_unknown_creator_history_is_a_nonmonetary_potential():
    from ugc_bot.application.financial_ports import PotentialBasis

    repo, service, _, _ = setup()
    basis = replace(
        command(),
        kind="creator_referral",
        assignment_id=uuid4(),
        rate_bps=None,
        registered_at=None,
        verified_count=None,
    )
    async with repo.transaction() as session:
        result = await service.issue(
            basis, recorded_at=basis.snapshot_at, session=session
        )
    assert isinstance(result, PotentialBasis)
    assert result.reason == "snapshot_policy_unresolved"
    assert result.basis.registered_at is result.basis.verified_count is None
    assert not repo.records and not repo.movements and not repo.wallets


def test_known_creator_rate_still_requires_a_measured_count():
    with pytest.raises(ValueError, match="invalid_verified_count"):
        replace(
            command(),
            kind="creator_referral",
            assignment_id=uuid4(),
            verified_count=None,
        )


@pytest.mark.asyncio
async def test_approved_override_is_reloaded_and_preserved():
    repo, service, Override, _ = setup()
    original = command()
    approval = Override(
        override_id=uuid4(),
        recipient_id=original.recipient_id,
        side="client",
        rate_bps=2000,
        policy_version=original.policy_version,
        effective_from=original.snapshot_at - timedelta(days=1),
        effective_until=original.snapshot_at + timedelta(days=1),
        approved_by=uuid4(),
        approved_at=original.snapshot_at - timedelta(days=2),
        reason="approved individual agreement",
    )
    repo.overrides[approval.override_id] = approval
    basis = replace(
        original,
        rate_bps=2000,
        rate_source="override",
        override_id=approval.override_id,
    )
    async with repo.transaction() as session:
        issued = await service.issue(
            basis, recorded_at=basis.snapshot_at, session=session
        )
    assert issued.movement.amount_minor == 10000
    assert issued.basis.override_id == approval.override_id
    assert issued.basis.rate_source == "override"
    async with repo.transaction() as session:
        assert (
            await service.issue(
                basis,
                recorded_at=basis.snapshot_at + timedelta(days=5),
                session=session,
            )
            == issued
        )


@pytest.mark.asyncio
async def test_declaring_override_cannot_bypass_server_approval():
    repo, service, _, _ = setup()
    basis = replace(
        command(), rate_bps=2000, rate_source="override", override_id=uuid4()
    )
    with pytest.raises(ValueError, match="approved_override_required"):
        async with repo.transaction() as session:
            await service.issue(
                basis, recorded_at=basis.snapshot_at, session=session
            )
    assert not repo.records


@pytest.mark.asyncio
async def test_live_ground_blocks_another_assignment_and_partner():
    repo, service, _, _ = setup()
    first = replace(command(), kind="creator_referral", assignment_id=uuid4())
    async with repo.transaction() as session:
        await service.issue(
            first, recorded_at=first.snapshot_at, session=session
        )
    second = replace(
        first,
        business_key="replacement",
        assignment_id=uuid4(),
        recipient_id=uuid4(),
    )
    with pytest.raises(ValueError, match="active_economic_ground_exists"):
        async with repo.transaction() as session:
            await service.issue(
                second, recorded_at=second.snapshot_at, session=session
            )
    assert len(repo.records) == 1


@pytest.mark.asyncio
async def test_missing_active_pointer_does_not_hide_a_live_journal_ground():
    repo, service, _, _ = setup()
    first = replace(command(), kind="creator_referral", assignment_id=uuid4())
    async with repo.transaction() as session:
        await service.issue(
            first, recorded_at=first.snapshot_at, session=session
        )
    repo.active_grounds.clear()
    second = replace(first, business_key="replacement", assignment_id=uuid4())
    with pytest.raises(ValueError, match="active_economic_ground_exists"):
        async with repo.transaction() as session:
            await service.issue(
                second, recorded_at=second.snapshot_at, session=session
            )


@pytest.mark.asyncio
async def test_cancelled_same_partner_replacement_preserves_history():
    repo, service, _, _ = setup()
    first = replace(command(), kind="creator_referral", assignment_id=uuid4())
    async with repo.transaction() as session:
        old = await service.issue(
            first, recorded_at=first.snapshot_at, session=session
        )
        reversal = JournalMovement(
            obligation_id=old.obligation_id,
            operation_key="cancel-old",
            event_id="replacement-review",
            movement_type="reversal",
            amount_minor=5000,
            currency="RUB",
            effective_at=first.snapshot_at,
            recorded_at=first.snapshot_at,
            actor_id=first.actor_id,
            reason="approved replacement before completed work",
            bucket_from="pending",
            bucket_to="cancelled",
            source_entry_id=await repo.get_entry_ref(
                old.movement.operation_key, session=session
            ),
        )
        await repo.append(reversal, session=session)
        await repo.apply_projection(reversal, session=session)
    second = replace(first, business_key="replacement", assignment_id=uuid4())
    async with repo.transaction() as session:
        new = await service.issue(
            second, recorded_at=second.snapshot_at, session=session
        )
    assert new.obligation_id != old.obligation_id
    assert repo.records[first.business_key] == old
    assert len(repo.records) == 2
    async with repo.transaction() as session:
        wallet = await repo.read_projection(
            first.recipient_id, "RUB", session=session
        )
    assert wallet["pending"] == 5000
    assert wallet["cancelled"] == 5000


@pytest.mark.asyncio
async def test_unknown_future_success_uses_separate_immutable_maturity_fact():
    repo, service, _, Source = setup()
    basis = replace(
        command(),
        kind="creator_referral",
        assignment_id=uuid4(),
        available_at=None,
    )
    source = Source(
        source_id=uuid4(),
        source_event_id=uuid4(),
        assignment_id=basis.assignment_id,
        paid_item_id=basis.paid_item_id,
        order_id=basis.order_id,
        policy_version=basis.policy_version,
        creator_id=basis.referred_user_id,
        manager_id=None,
        state="success_final",
        assignment_ended_at=None,
        success_final_at=basis.snapshot_at + timedelta(days=3),
        release_at=basis.snapshot_at + timedelta(days=17),
    )
    repo.maturity_sources[source.source_id] = source
    async with repo.transaction() as session:
        issued = await service.issue(
            basis, recorded_at=basis.snapshot_at, session=session
        )
        fact = await service.record_maturity(
            basis.business_key,
            source.source_id,
            producer="financial_lifecycle",
            recorded_at=source.success_final_at,
            session=session,
        )
        assert fact.release_at == basis.snapshot_at + timedelta(days=17)
        hold = JournalMovement(
            obligation_id=issued.obligation_id,
            operation_key="hold",
            event_id="success",
            movement_type="transfer",
            amount_minor=5000,
            currency="RUB",
            effective_at=source.success_final_at,
            recorded_at=source.success_final_at,
            actor_id=basis.actor_id,
            reason="confirmed work",
            bucket_from="pending",
            bucket_to="hold",
        )
        await service.transfer(
            basis.business_key,
            hold,
            now=source.success_final_at,
            session=session,
        )
    release = replace(
        hold, operation_key="release", bucket_from="hold", bucket_to="available"
    )
    with pytest.raises(ValueError, match="hold_not_mature"):
        async with repo.transaction() as session:
            await service.transfer(
                basis.business_key,
                release,
                now=source.release_at - timedelta(microseconds=1),
                session=session,
            )
    async with repo.transaction() as session:
        await service.transfer(
            basis.business_key, release, now=source.release_at, session=session
        )
        assert (
            await repo.get_issue(basis.business_key, session=session)
        ).basis.available_at is None
        assert (
            await service.record_maturity(
                basis.business_key,
                source.source_id,
                producer="financial_lifecycle",
                recorded_at=source.release_at,
                session=session,
            )
            == fact
        )


@pytest.mark.asyncio
async def test_dispute_after_maturity_blocks_stale_release():
    repo, service, _, Source = setup()
    basis = replace(
        command(),
        kind="creator_referral",
        assignment_id=uuid4(),
        available_at=None,
    )
    source = Source(
        source_id=uuid4(),
        source_event_id=uuid4(),
        assignment_id=basis.assignment_id,
        paid_item_id=basis.paid_item_id,
        order_id=basis.order_id,
        policy_version=basis.policy_version,
        creator_id=basis.referred_user_id,
        manager_id=None,
        state="success_final",
        assignment_ended_at=None,
        success_final_at=basis.snapshot_at,
        release_at=basis.snapshot_at + timedelta(days=14),
    )
    repo.maturity_sources[source.source_id] = source
    async with repo.transaction() as session:
        issued = await service.issue(
            basis, recorded_at=basis.snapshot_at, session=session
        )
        await service.record_maturity(
            basis.business_key,
            source.source_id,
            producer="financial_lifecycle",
            recorded_at=basis.snapshot_at,
            session=session,
        )
        hold = JournalMovement(
            obligation_id=issued.obligation_id,
            operation_key="hold",
            event_id="success",
            movement_type="transfer",
            amount_minor=5000,
            currency="RUB",
            effective_at=basis.snapshot_at,
            recorded_at=basis.snapshot_at,
            actor_id=basis.actor_id,
            reason="success",
            bucket_from="pending",
            bucket_to="hold",
        )
        await service.transfer(
            basis.business_key, hold, now=basis.snapshot_at, session=session
        )
    repo.maturity_sources[source.source_id] = replace(source, state="disputed")
    with pytest.raises(ValueError, match="maturity_source_not_eligible"):
        async with repo.transaction() as session:
            await service.transfer(
                basis.business_key,
                replace(
                    hold,
                    operation_key="release",
                    bucket_from="hold",
                    bucket_to="available",
                ),
                now=source.release_at,
                session=session,
            )


def source_for(basis, Source, **changes):
    return Source(
        **(
            dict(
                source_id=uuid4(),
                source_event_id=uuid4(),
                assignment_id=basis.assignment_id,
                paid_item_id=basis.paid_item_id,
                order_id=basis.order_id,
                policy_version=basis.policy_version,
                creator_id=basis.referred_user_id,
                manager_id=None,
                state="success_final",
                assignment_ended_at=None,
                success_final_at=basis.snapshot_at,
                release_at=basis.snapshot_at + timedelta(days=14),
            )
            | changes
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    ["recipient_id", "policy_version", "side", "rate_bps", "effective_until"],
)
async def test_override_approval_must_match_the_exact_capture_scope(field):
    repo, service, Override, _ = setup()
    cmd = command()
    approval = Override(
        override_id=uuid4(),
        recipient_id=cmd.recipient_id,
        side="client",
        rate_bps=2000,
        policy_version=cmd.policy_version,
        effective_from=cmd.snapshot_at - timedelta(days=1),
        effective_until=cmd.snapshot_at + timedelta(days=1),
        approved_by=uuid4(),
        approved_at=cmd.snapshot_at - timedelta(days=2),
        reason="individual agreement",
    )
    changes = dict(
        recipient_id=uuid4(),
        policy_version="other",
        side="creator",
        rate_bps=2500,
        effective_until=cmd.snapshot_at,
    )
    repo.overrides[approval.override_id] = replace(
        approval, **{field: changes[field]}
    )
    cmd = replace(
        cmd,
        rate_source="override",
        override_id=approval.override_id,
        rate_bps=2000,
    )
    with pytest.raises(ValueError, match="approved_override_required"):
        async with repo.transaction() as session:
            await service.issue(
                cmd, recorded_at=cmd.snapshot_at, session=session
            )
    assert not repo.records


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"override_id": "forged"}, "override_identity_required"),
        ({"side": "management"}, "invalid_override_rate"),
        ({"rate_bps": True}, "invalid_override_rate"),
        (
            {"effective_until": command().snapshot_at - timedelta(days=5)},
            "invalid_override_period",
        ),
        ({"approved_at": command().snapshot_at}, "invalid_override_period"),
        ({"reason": " "}, "override_provenance_required"),
    ],
)
def test_invalid_approval_facts_cannot_be_constructed(changes, error):
    _, _, Override, _ = setup()
    cmd = command()
    values = dict(
        override_id=uuid4(),
        recipient_id=cmd.recipient_id,
        side="client",
        rate_bps=2000,
        policy_version=cmd.policy_version,
        effective_from=cmd.snapshot_at - timedelta(days=1),
        effective_until=cmd.snapshot_at + timedelta(days=1),
        approved_by=uuid4(),
        approved_at=cmd.snapshot_at - timedelta(days=2),
        reason="individual agreement",
    )
    with pytest.raises(ValueError, match=error):
        Override(**(values | changes))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"state": "disputed"},
        {"assignment_id": uuid4()},
        {"paid_item_id": uuid4()},
        {"order_id": uuid4()},
        {"policy_version": "other"},
        {"creator_id": uuid4()},
        {"assignment_ended_at": command().snapshot_at},
    ],
)
async def test_maturity_requires_current_matching_success_scope(changes):
    repo, service, _, Source = setup()
    cmd = replace(
        command(),
        kind="creator_referral",
        assignment_id=uuid4(),
        available_at=None,
    )
    source = source_for(cmd, Source, **changes)
    repo.maturity_sources[source.source_id] = source
    async with repo.transaction() as session:
        await service.issue(cmd, recorded_at=cmd.snapshot_at, session=session)
    with pytest.raises(ValueError, match="maturity_source_not_eligible"):
        async with repo.transaction() as session:
            await service.record_maturity(
                cmd.business_key,
                source.source_id,
                producer="financial_lifecycle",
                recorded_at=cmd.snapshot_at,
                session=session,
            )
    assert not repo.maturities


@pytest.mark.asyncio
async def test_rolled_back_issuance_and_maturity_leave_no_money_or_binding():
    repo, service, _, Source = setup()
    cmd = replace(
        command(),
        kind="creator_referral",
        assignment_id=uuid4(),
        available_at=None,
    )
    source = source_for(cmd, Source)
    repo.maturity_sources[source.source_id] = source
    with pytest.raises(RuntimeError, match="late_failure"):
        async with repo.transaction() as session:
            await service.issue(
                cmd, recorded_at=cmd.snapshot_at, session=session
            )
            await service.record_maturity(
                cmd.business_key,
                source.source_id,
                producer="financial_lifecycle",
                recorded_at=cmd.snapshot_at,
                session=session,
            )
            raise RuntimeError("late_failure")
    assert not any(
        (
            repo.records,
            repo.movements,
            repo.entry_ids,
            repo.wallets,
            repo.active_grounds,
            repo.maturities,
        )
    )
    with pytest.raises(ValueError, match="caller_transaction_required"):
        await repo.get_issue(cmd.business_key, session=session)


@pytest.mark.asyncio
async def test_maturity_requires_success_and_provenance():
    repo, service, _, Source = setup()
    cmd = replace(
        command(),
        kind="creator_referral",
        assignment_id=uuid4(),
        available_at=None,
    )
    source = source_for(cmd, Source)
    repo.maturity_sources[source.source_id] = source
    async with repo.transaction() as session:
        await service.issue(cmd, recorded_at=cmd.snapshot_at, session=session)
        for ref, producer, error in [
            ("forged", "worker", "maturity_provenance_required"),
            (source.source_id, " ", "maturity_provenance_required"),
            (uuid4(), "worker", "maturity_source_not_eligible"),
        ]:
            with pytest.raises(ValueError, match=error):
                await service.record_maturity(
                    cmd.business_key,
                    ref,
                    producer=producer,
                    recorded_at=cmd.snapshot_at,
                    session=session,
                )
        with pytest.raises(ValueError, match="maturity_before_success"):
            await service.record_maturity(
                cmd.business_key,
                source.source_id,
                producer="worker",
                recorded_at=cmd.snapshot_at - timedelta(microseconds=1),
                session=session,
            )
        await service.record_maturity(
            cmd.business_key,
            source.source_id,
            producer="worker",
            recorded_at=cmd.snapshot_at,
            session=session,
        )
        with pytest.raises(ValueError, match="idempotency_payload_conflict"):
            await service.record_maturity(
                cmd.business_key,
                source.source_id,
                producer="other-worker",
                recorded_at=cmd.snapshot_at,
                session=session,
            )


@pytest.mark.asyncio
async def test_memory_maturity_repository_cannot_rewrite_immutable_binding():
    repo, service, _, Source = setup()
    cmd = replace(
        command(),
        kind="creator_referral",
        assignment_id=uuid4(),
        available_at=None,
    )
    source = source_for(cmd, Source)
    repo.maturity_sources[source.source_id] = source
    async with repo.transaction() as session:
        await service.issue(cmd, recorded_at=cmd.snapshot_at, session=session)
        fact = await service.record_maturity(
            cmd.business_key,
            source.source_id,
            producer="worker",
            recorded_at=cmd.snapshot_at,
            session=session,
        )
        with pytest.raises(ValueError, match="idempotency_payload_conflict"):
            await repo.save_maturity(
                replace(fact, source_id=uuid4()), session=session
            )
        assert (
            await repo.get_maturity(fact.obligation_id, session=session) == fact
        )


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"rate_source": "forged"}, "invalid_rate_provenance"),
        ({"rate_source": "override"}, "override_reference_required"),
        ({"override_id": uuid4()}, "override_reference_required"),
        (
            {
                "kind": "management",
                "assignment_id": uuid4(),
                "registered_at": None,
                "rate_bps": None,
                "verified_count": None,
                "rate_source": "override",
                "override_id": uuid4(),
            },
            "management_override_not_applicable",
        ),
    ],
)
def test_basis_provenance_cannot_be_an_unchecked_flag(changes, error):
    with pytest.raises(ValueError, match=error):
        replace(command(), **changes)


def test_work_schedule_requires_the_full_fourteen_day_delay():
    _, _, _, Source = setup()
    cmd = replace(command(), kind="creator_referral", assignment_id=uuid4())
    with pytest.raises(ValueError, match="invalid_work_maturity_schedule"):
        source_for(cmd, Source, release_at=cmd.snapshot_at + timedelta(days=13))


@pytest.mark.asyncio
async def test_maturity_rejects_missing_or_changed_source():
    repo, service, _, Source = setup()
    cmd = replace(
        command(),
        kind="creator_referral",
        assignment_id=uuid4(),
        available_at=None,
    )
    source = source_for(cmd, Source)
    repo.maturity_sources[source.source_id] = source
    async with repo.transaction() as session:
        with pytest.raises(ValueError, match="obligation_not_found"):
            await service.record_maturity(
                "missing",
                source.source_id,
                producer="worker",
                recorded_at=cmd.snapshot_at,
                session=session,
            )
        issued = await service.issue(
            cmd, recorded_at=cmd.snapshot_at, session=session
        )
        fact = await service.record_maturity(
            cmd.business_key,
            source.source_id,
            producer="worker",
            recorded_at=cmd.snapshot_at,
            session=session,
        )
        assert await repo.save_maturity(fact, session=session) == fact
        hold = replace(
            issued.movement,
            operation_key="hold",
            movement_type="transfer",
            bucket_from="pending",
            bucket_to="hold",
        )
        await service.transfer(
            cmd.business_key, hold, now=cmd.snapshot_at, session=session
        )
    release = replace(
        hold, operation_key="release", bucket_from="hold", bucket_to="available"
    )
    for changed, error in [
        (None, "maturity_source_not_eligible"),
        (
            replace(
                source,
                success_final_at=source.success_final_at + timedelta(days=1),
                release_at=source.release_at + timedelta(days=1),
            ),
            "maturity_source_changed",
        ),
    ]:
        if changed is None:
            repo.maturity_sources.clear()
        else:
            repo.maturity_sources[source.source_id] = changed
        with pytest.raises(ValueError, match=error):
            async with repo.transaction() as session:
                await service.transfer(
                    cmd.business_key,
                    release,
                    now=source.release_at + timedelta(days=2),
                    session=session,
                )


@pytest.mark.asyncio
async def test_memory_journal_idempotency_scope_and_projection_guards():
    repo, service, _, _ = setup()
    cmd = replace(command(), kind="creator_referral", assignment_id=uuid4())
    async with repo.transaction() as session:
        issued = await service.issue(
            cmd, recorded_at=cmd.snapshot_at, session=session
        )
        assert (
            await repo.get_active_ground(
                cmd.paid_item_id, cmd.kind, session=session
            )
        ).obligation_id == issued.obligation_id
        await repo.lock_recipients((cmd.recipient_id,), session=session)
        with pytest.raises(ValueError, match="unpublished_currency"):
            await repo.lock_wallets(
                ((cmd.recipient_id, "USD"),), session=session
            )
        with pytest.raises(ValueError, match="economic_basis_already_exists"):
            await repo.save_issue(
                replace(issued, obligation_id=uuid4()), session=session
            )
        assert (
            await repo.append(issued.movement, session=session)
            == issued.movement
        )
        with pytest.raises(ValueError, match="idempotency_payload_conflict"):
            await repo.append(
                replace(issued.movement, reason="different"), session=session
            )
        correction = JournalMovement(
            obligation_id=issued.obligation_id,
            operation_key="bad-correction",
            event_id="review",
            movement_type="reversal",
            amount_minor=5000,
            currency="RUB",
            effective_at=cmd.snapshot_at,
            recorded_at=cmd.snapshot_at,
            actor_id=cmd.actor_id,
            reason="review",
            bucket_from="pending",
            bucket_to="cancelled",
            source_entry_id=uuid4(),
        )
        with pytest.raises(
            ValueError, match="correction_source_scope_mismatch"
        ):
            await repo.append(correction, session=session)
    with pytest.raises(ValueError, match="negative_wallet_projection"):
        async with repo.transaction() as session:
            overdraw = replace(
                issued.movement,
                operation_key="overdraw",
                movement_type="transfer",
                bucket_from="pending",
                bucket_to="hold",
                amount_minor=5001,
            )
            await repo.append(overdraw, session=session)
            await repo.apply_projection(overdraw, session=session)
    assert set(repo.movements) == {issued.movement.operation_key}
    async with repo.transaction() as session:
        assert (
            await repo.read_projection(cmd.recipient_id, "RUB", session=session)
        )["pending"] == 5000


@pytest.mark.asyncio
async def test_potential_replay_preserves_original_unknown_fact():
    repo, service, _, _ = setup()
    cmd = replace(command(), rate_bps=None, registered_at=None)
    async with repo.transaction() as session:
        original = await service.issue(
            cmd, recorded_at=cmd.snapshot_at, session=session
        )
        assert (
            await service.issue(
                cmd,
                recorded_at=cmd.snapshot_at + timedelta(days=1),
                session=session,
            )
            == original
        )
        with pytest.raises(ValueError, match="idempotency_payload_conflict"):
            await service.issue(
                replace(cmd, reason="changed historical fact"),
                recorded_at=cmd.snapshot_at,
                session=session,
            )


@pytest.mark.asyncio
async def test_recovered_debt_does_not_erase_paid_history_for_replacement():
    repo, service, _, _ = setup()
    cmd = replace(command(), kind="creator_referral", assignment_id=uuid4())
    request_id, allocation_id, execution_id, case_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    async with repo.transaction() as session:
        issued = await service.issue(
            cmd, recorded_at=cmd.snapshot_at, session=session
        )
        for source, target in [
            ("pending", "hold"),
            ("hold", "available"),
            ("available", "reserved"),
            ("reserved", "paid"),
        ]:
            move = replace(
                issued.movement,
                operation_key="move:" + target,
                movement_type="transfer",
                bucket_from=source,
                bucket_to=target,
                request_id=request_id,
                allocation_id=allocation_id,
                execution_id=execution_id,
            )
            await repo.append(move, session=session)
            await repo.apply_projection(move, session=session)
        paid_ref = await repo.get_entry_ref("move:paid", session=session)
        for kind in ("debt", "recovery"):
            correction = replace(
                issued.movement,
                operation_key=kind,
                movement_type=kind,
                bucket_from=None,
                bucket_to=None,
                source_entry_id=paid_ref,
                case_id=case_id,
            )
            await repo.append(correction, session=session)
            await repo.apply_projection(correction, session=session)
        wallet = await repo.read_projection(
            cmd.recipient_id, "RUB", session=session
        )
        assert wallet["paid"] == wallet["cancelled"] == 5000
        assert wallet["debt"] == 0
    with pytest.raises(ValueError, match="active_economic_ground_exists"):
        async with repo.transaction() as session:
            await service.issue(
                replace(
                    cmd,
                    business_key="replacement-after-recovery",
                    assignment_id=uuid4(),
                ),
                recorded_at=cmd.snapshot_at,
                session=session,
            )


@pytest.mark.asyncio
async def test_system_issuance_and_potential_keep_named_server_provenance():
    repo, service, _, _ = setup()
    basis = replace(
        command(),
        actor_id=None,
        actor_kind="system",
        system_actor="work_entitlement",
    )
    async with repo.transaction() as session:
        issued = await service.issue(
            basis, recorded_at=basis.snapshot_at, session=session
        )
        assert issued.movement.actor_id is None
        assert issued.movement.actor_kind == "system"
        assert issued.movement.system_actor == "work_entitlement"
        unknown = replace(
            basis,
            business_key="unknown",
            recipient_id=None,
            rate_bps=None,
            registered_at=None,
        )
        potential = await service.issue(
            unknown, recorded_at=basis.snapshot_at, session=session
        )
        assert potential.basis.actor_kind == "system"
        assert potential.basis.system_actor == "work_entitlement"
    with pytest.raises(ValueError, match="basis_actor_provenance_required"):
        replace(basis, system_actor=None)
    with pytest.raises(ValueError, match="basis_actor_provenance_required"):
        replace(basis, actor_id=uuid4())

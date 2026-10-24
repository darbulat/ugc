"""Authenticated temporal override commands preserve historical captures."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

START = datetime(2026, 10, 23, tzinfo=timezone.utc)


class Clock:
    at = START

    def now(self):
        return self.at


def setup():
    from ugc_bot.application.override_ports import OverridePolicy, OverrideUser
    from ugc_bot.application.services.rate_override_service import (
        RateOverrideService,
    )
    from ugc_bot.infrastructure.memory_rate_overrides import (
        InMemoryRateOverrideRepository,
    )

    admin, other, recipient = uuid4(), uuid4(), uuid4()
    repo = InMemoryRateOverrideRepository(
        users={
            admin: OverrideUser(admin, "active", True),
            other: OverrideUser(other, "active", True),
            recipient: OverrideUser(recipient, "active", False),
        },
        policies={
            "approved:test": OverridePolicy(
                "approved:test",
                admin,
                START - timedelta(days=2),
                START - timedelta(days=1),
            )
        },
    )
    clock = Clock()
    return (
        repo,
        RateOverrideService(repo, clock),
        clock,
        admin,
        other,
        recipient,
    )


def create(admin, recipient, **changes):
    from ugc_bot.application.override_ports import CreateRateOverride

    return CreateRateOverride(
        **(
            dict(
                operation_key="create:one",
                actor_id=admin,
                recipient_id=recipient,
                side="client",
                policy_version="approved:test",
                rate_bps=2000,
                effective_from=START + timedelta(days=1),
                effective_until=START + timedelta(days=30),
                reason="explicit individual agreement",
            )
            | changes
        )
    )


@pytest.mark.asyncio
async def test_create_replay_and_selector_use_server_approval_provenance():
    repo, service, clock, admin, _, recipient = setup()
    cmd = create(admin, recipient)
    async with repo.transaction() as session:
        result = await service.execute(cmd, session=session)
        assert result.override.version == 1
        assert result.override.approval.approved_by == admin
        assert result.override.approval.approved_at == START
        clock.at += timedelta(days=2)
        assert await service.execute(cmd, session=session) == result
        assert (
            await service.select_effective(
                recipient_id=recipient,
                side="client",
                policy_version="approved:test",
                as_of=START,
                session=session,
            )
            is None
        )
        assert (
            await service.select_effective(
                recipient_id=recipient,
                side="client",
                policy_version="approved:test",
                as_of=cmd.effective_from,
                session=session,
            )
            == result.override.approval
        )
    assert len(repo.approvals) == len(repo.commands) == len(repo.events) == 1


@pytest.mark.asyncio
async def test_overlap_is_rejected_but_explicit_supersession_is_atomic():
    from ugc_bot.application.override_ports import SupersedeRateOverride

    repo, service, _, admin, other, recipient = setup()
    cmd = create(admin, recipient)
    async with repo.transaction() as session:
        first = await service.execute(cmd, session=session)
    second = create(other, recipient, operation_key="create:overlap")
    with pytest.raises(ValueError, match="override_period_overlaps"):
        async with repo.transaction() as session:
            await service.execute(second, session=session)
    supersede = SupersedeRateOverride(
        operation_key="supersede:one",
        actor_id=other,
        recipient_id=recipient,
        side="client",
        policy_version="approved:test",
        override_id=first.override.approval.override_id,
        expected_version=1,
        rate_bps=2500,
        effective_from=START + timedelta(days=5),
        effective_until=START + timedelta(days=40),
        reason="new explicit agreement",
    )
    async with repo.transaction() as session:
        result = await service.execute(supersede, session=session)
        assert result.override.version == 2
        assert result.replacement.version == 1
        before = await service.select_effective(
            recipient_id=recipient,
            side="client",
            policy_version="approved:test",
            as_of=START + timedelta(days=4),
            session=session,
        )
        after = await service.select_effective(
            recipient_id=recipient,
            side="client",
            policy_version="approved:test",
            as_of=supersede.effective_from,
            session=session,
        )
        assert before == first.override.approval
        assert after == result.replacement.approval
    assert (
        repo.approvals[first.override.approval.override_id]
        == first.override.approval
    )
    assert (
        len(repo.approvals) == 2
        and len(repo.commands) == 2
        and len(repo.events) == 3
    )


@pytest.mark.asyncio
async def test_nonadmin_and_changed_current_role_cannot_replay_authority():
    repo, service, _, admin, _, recipient = setup()
    with pytest.raises(ValueError, match="active_admin_required"):
        async with repo.transaction() as session:
            await service.execute(create(recipient, recipient), session=session)
    cmd = create(admin, recipient)
    async with repo.transaction() as session:
        await service.execute(cmd, session=session)
    repo.users[admin] = replace(repo.users[admin], is_admin=False)
    with pytest.raises(ValueError, match="active_admin_required"):
        async with repo.transaction() as session:
            await service.execute(cmd, session=session)


@pytest.mark.asyncio
async def test_revoke_keeps_old_capture_and_rejects_stale_version():
    from ugc_bot.application.override_ports import RevokeRateOverride

    repo, service, _, admin, _, recipient = setup()
    async with repo.transaction() as session:
        created = await service.execute(
            create(admin, recipient), session=session
        )
    cmd = RevokeRateOverride(
        operation_key="revoke:one",
        actor_id=admin,
        recipient_id=recipient,
        side="client",
        policy_version="approved:test",
        override_id=created.override.approval.override_id,
        expected_version=1,
        effective_at=START + timedelta(days=10),
        reason="future agreement ended",
    )
    async with repo.transaction() as session:
        result = await service.execute(cmd, session=session)
        assert result.override.version == 2
        assert (
            await service.lookup(
                created.override.approval.override_id,
                as_of=START + timedelta(days=9),
                session=session,
            )
            == created.override.approval
        )
        assert (
            await service.lookup(
                created.override.approval.override_id,
                as_of=cmd.effective_at,
                session=session,
            )
            is None
        )
        with pytest.raises(ValueError, match="override_version_conflict"):
            await service.execute(
                replace(cmd, operation_key="stale"), session=session
            )


@pytest.mark.asyncio
async def test_command_conflict_and_supersede_rollback_preserve_history():
    from ugc_bot.application.override_ports import SupersedeRateOverride

    repo, service, _, admin, _, recipient = setup()
    cmd = create(admin, recipient)
    async with repo.transaction() as session:
        first = await service.execute(cmd, session=session)
        with pytest.raises(ValueError, match="idempotency_payload_conflict"):
            await service.execute(replace(cmd, rate_bps=2500), session=session)
    replacement = SupersedeRateOverride(
        operation_key="replace:rollback",
        actor_id=admin,
        recipient_id=recipient,
        side="client",
        policy_version="approved:test",
        override_id=first.override.approval.override_id,
        expected_version=1,
        rate_bps=2500,
        effective_from=START + timedelta(days=4),
        effective_until=START + timedelta(days=40),
        reason="approved change",
    )
    with pytest.raises(RuntimeError, match="late_failure"):
        async with repo.transaction() as session:
            await service.execute(replacement, session=session)
            raise RuntimeError("late_failure")
    async with repo.transaction() as session:
        assert (
            await service.get_for_admin(
                first.override.approval.override_id,
                actor_id=admin,
                session=session,
            )
        ).version == 1
    assert len(repo.approvals) == len(repo.commands) == len(repo.events) == 1


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"actor_id": "forged"}, "override_identity_required"),
        ({"recipient_id": None}, "override_identity_required"),
        ({"side": "management"}, "invalid_override_side"),
        ({"rate_bps": 0}, "invalid_override_rate"),
        ({"rate_bps": 10001}, "invalid_override_rate"),
        ({"rate_bps": True}, "invalid_override_rate"),
        ({"reason": " "}, "override_provenance_required"),
        ({"operation_key": "x" * 257}, "override_provenance_required"),
        ({"policy_version": None}, "override_provenance_required"),
        ({"effective_until": START}, "invalid_override_period"),
        (
            {"effective_from": START.replace(tzinfo=None)},
            "aware_timestamp_required",
        ),
    ],
)
def test_command_requires_explicit_typed_scope_and_period(changes, error):
    _, _, _, admin, _, recipient = setup()
    with pytest.raises(ValueError, match=error):
        create(admin, recipient, **changes)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", ["pause", "bot_blocked", "blocked", "deleted", "new"]
)
async def test_only_current_active_admin_status_is_authorized(status):
    repo, service, _, admin, _, recipient = setup()
    repo.users[admin] = replace(repo.users[admin], status=status)
    with pytest.raises(ValueError, match="active_admin_required"):
        async with repo.transaction() as session:
            await service.execute(create(admin, recipient), session=session)
    assert not repo.commands and not repo.approvals


@pytest.mark.asyncio
async def test_server_clock_and_policy_activation_prevent_backdating():
    repo, service, clock, admin, _, recipient = setup()
    clock.at = START + timedelta(days=2)
    with pytest.raises(ValueError, match="override_backdating_forbidden"):
        async with repo.transaction() as session:
            await service.execute(create(admin, recipient), session=session)
    repo.policies["approved:test"] = replace(
        repo.policies["approved:test"], effective_from=START + timedelta(days=5)
    )
    with pytest.raises(ValueError, match="override_backdating_forbidden"):
        async with repo.transaction() as session:
            await service.execute(
                create(admin, recipient, effective_from=clock.at),
                session=session,
            )
    async with repo.transaction() as session:
        result = await service.execute(
            create(admin, recipient, effective_from=START + timedelta(days=5)),
            session=session,
        )
        assert result.override.approval.approved_at == clock.at


@pytest.mark.asyncio
async def test_unknown_policy_recipient_and_command_do_not_create_facts():
    repo, service, _, admin, _, recipient = setup()
    for cmd, error in [
        (
            create(admin, recipient, recipient_id=uuid4()),
            "override_recipient_not_found",
        ),
        (
            create(admin, recipient, policy_version="unknown"),
            "approved_policy_required",
        ),
    ]:
        with pytest.raises(ValueError, match=error):
            async with repo.transaction() as session:
                await service.execute(cmd, session=session)
    async with repo.transaction() as session:
        with pytest.raises(ValueError, match="typed_override_command_required"):
            await service.execute({"is_admin": True}, session=session)
        assert (
            await service.get_for_admin(
                uuid4(), actor_id=admin, session=session
            )
            is None
        )
        assert (
            await service.lookup(uuid4(), as_of=START, session=session) is None
        )
    assert not repo.commands
    with pytest.raises(ValueError, match="caller_transaction_required"):
        await repo.get(uuid4(), session=session)


@pytest.mark.asyncio
async def test_revoke_versions_scope_and_future_cancellation_are_exact():
    from ugc_bot.application.override_ports import RevokeRateOverride

    repo, service, _, admin, other, recipient = setup()
    async with repo.transaction() as session:
        first = await service.execute(create(admin, recipient), session=session)
    cmd = RevokeRateOverride(
        operation_key="revoke",
        actor_id=admin,
        recipient_id=recipient,
        side="client",
        policy_version="approved:test",
        override_id=first.override.approval.override_id,
        expected_version=1,
        effective_at=START,
        reason="cancel future activation",
    )
    with pytest.raises(ValueError, match="override_identity_required"):
        replace(cmd, override_id=None)
    with pytest.raises(ValueError, match="override_expected_version_required"):
        replace(cmd, expected_version=True)
    async with repo.transaction() as session:
        for changes, error in [
            ({"override_id": uuid4()}, "override_not_found"),
            ({"recipient_id": other}, "override_scope_mismatch"),
            (
                {"effective_at": START + timedelta(days=30)},
                "override_change_outside_period",
            ),
        ]:
            with pytest.raises(ValueError, match=error):
                await service.execute(replace(cmd, **changes), session=session)
        ended = await service.execute(cmd, session=session)
        assert ended.override.revoked_at == START
        assert (
            await service.select_effective(
                recipient_id=recipient,
                side="client",
                policy_version="approved:test",
                as_of=START + timedelta(days=2),
                session=session,
            )
            is None
        )
        with pytest.raises(ValueError, match="override_already_revoked"):
            await service.execute(
                replace(cmd, operation_key="again", expected_version=2),
                session=session,
            )


@pytest.mark.asyncio
async def test_supersede_cannot_overlap_an_unrelated_future_agreement():
    from ugc_bot.application.override_ports import SupersedeRateOverride

    repo, service, _, admin, _, recipient = setup()
    async with repo.transaction() as session:
        first = await service.execute(
            create(admin, recipient, effective_until=START + timedelta(days=5)),
            session=session,
        )
        second = await service.execute(
            create(
                admin,
                recipient,
                operation_key="later",
                effective_from=START + timedelta(days=5),
            ),
            session=session,
        )
        assert (
            await repo.select_effective_override(
                recipient,
                "client",
                "approved:test",
                START + timedelta(days=5),
                session=session,
            )
            == second.override.approval
        )
    cmd = SupersedeRateOverride(
        operation_key="supersede",
        actor_id=admin,
        recipient_id=recipient,
        side="client",
        policy_version="approved:test",
        override_id=first.override.approval.override_id,
        expected_version=1,
        rate_bps=2500,
        effective_from=START + timedelta(days=4),
        effective_until=START + timedelta(days=6),
        reason="overlaps the next separate agreement",
    )
    with pytest.raises(ValueError, match="override_period_overlaps"):
        async with repo.transaction() as session:
            await service.execute(cmd, session=session)
    async with repo.transaction() as session:
        assert (
            await repo.get(first.override.approval.override_id, session=session)
        ).version == 1


@pytest.mark.asyncio
async def test_operation_key_conflict_includes_policy_and_recipient():
    repo, service, _, admin, _, recipient = setup()
    cmd = create(admin, recipient)
    async with repo.transaction() as session:
        await service.execute(cmd, session=session)
        for changed in (
            replace(cmd, policy_version="unknown"),
            replace(cmd, recipient_id=uuid4()),
        ):
            with pytest.raises(
                ValueError, match="idempotency_payload_conflict"
            ):
                await service.execute(changed, session=session)
    assert len(repo.commands) == 1


@pytest.mark.asyncio
async def test_selector_fails_ambiguity_and_invalid_side_without_proof_flags():
    repo, service, _, admin, _, recipient = setup()
    with pytest.raises(TypeError):
        create(admin, recipient, is_admin=True)
    async with repo.transaction() as session:
        result = await service.execute(
            create(admin, recipient), session=session
        )
        duplicate = replace(result.override.approval, override_id=uuid4())
        repo.approvals[duplicate.override_id] = duplicate
        with pytest.raises(ValueError, match="override_approval_ambiguous"):
            await service.select_effective(
                recipient_id=recipient,
                side="client",
                policy_version="approved:test",
                as_of=START + timedelta(days=2),
                session=session,
            )
        with pytest.raises(ValueError, match="invalid_override_side"):
            await service.select_effective(
                recipient_id=recipient,
                side="management",
                policy_version="approved:test",
                as_of=START,
                session=session,
            )


@pytest.mark.asyncio
async def test_admin_scope_read_has_explicit_current_authorization():
    repo, service, _, admin, _, recipient = setup()
    async with repo.transaction() as session:
        created = await service.execute(
            create(admin, recipient), session=session
        )
        assert await service.list_for_admin(
            recipient,
            "client",
            "approved:test",
            actor_id=admin,
            session=session,
        ) == (created.override,)
        for actor, target, side, error in [
            (recipient, recipient, "client", "active_admin_required"),
            (admin, uuid4(), "client", "override_recipient_not_found"),
            (admin, recipient, "management", "invalid_override_side"),
        ]:
            with pytest.raises(ValueError, match=error):
                await service.list_for_admin(
                    target,
                    side,
                    "approved:test",
                    actor_id=actor,
                    session=session,
                )

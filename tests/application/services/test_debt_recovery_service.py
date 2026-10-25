from types import SimpleNamespace as NS
from uuid import UUID, uuid4

import pytest

from tests.application.services.test_lifecycle_ledger_extensions import setup
from tests.application.services.test_obligation_compensation import original
from ugc_bot.application.debt_recovery_ports import (
    ApplyDebtRecovery,
    RecordDebtRepayment,
)
from ugc_bot.application.physical_proof_ports import (
    PhysicalProofConflict,
    PhysicalProofIdentity,
)
from ugc_bot.application.services.financial_reconciliation_service import (
    FinancialReconciliationService,
)
from ugc_bot.application.services.obligation_compensation_service import (
    ObligationCompensationService,
)


class Repository:
    def __init__(self, admin):
        self.admin = admin
        self.commands = {}
        self.observations = {}
        self.applications = {}

    async def actor(self, actor_id, *, session):
        return NS(
            user_id=actor_id,
            is_admin=actor_id == self.admin,
            status="active",
            telegram_id="123",
            max_id=None,
        )

    async def lock_operation(self, *args, session):
        pass

    async def command(self, actor, key, *, session):
        return self.commands.get((actor, key))

    async def observation(self, identity, *, session):
        return self.observations.get(identity)

    async def application(self, identity, *, session):
        return next(
            (
                row
                for (observation, _), row in self.applications.items()
                if observation == identity
            ),
            None,
        )

    async def case_grounds(self, case_id, recipient_id, currency, *, session):
        ids = {
            entry.obligation_id
            for entry in await self.ledger.list_for_recipient(
                recipient_id, currency, session=session
            )
            if entry.case_id == case_id and entry.movement_type == "debt"
        }
        return tuple(
            sorted(
                key
                for key, issue in self.ledger.records.items()
                if issue.obligation_id in ids
            )
        )

    async def append_observation(self, value, *, session):
        self.observations[value["observation_id"]] = value

    async def append_application(self, value, *, session):
        self.applications[value["observation_id"], value["obligation_id"]] = (
            value
        )

    async def save_command(self, value, *, session):
        self.commands[value["actor_id"], value["operation_key"]] = value


class Proofs:
    def __init__(self):
        self.claims = {}

    def resolve_manual_identity(self, label, ref, *, direction):
        return PhysicalProofIdentity(
            source="synthetic-bank",
            account=label,
            direction=direction,
            reference=ref,
        )

    async def claim(self, identity, owner, *, session):
        if identity.key in self.claims and self.claims[identity.key] != owner:
            raise PhysicalProofConflict()
        self.claims[identity.key] = owner
        return owner

    async def owners(self, identity, *, session):
        return (
            (self.claims[identity.key],) if identity.key in self.claims else ()
        )

    async def lock(self, identity, *, session):
        pass


async def fixture():
    from ugc_bot.application.services.debt_recovery_service import (
        DebtRecoveryService,
    )

    repo, ledger, _, _ = setup()
    issue = await original(repo, ledger, "paid")
    case = uuid4()
    admin = issue.basis.actor_id
    clock = NS(now=lambda: issue.basis.available_at)
    async with repo.transaction() as session:
        await ObligationCompensationService(ledger).cancel(
            issue,
            target_minor=3000,
            already_cancelled_minor=0,
            case_id=case,
            refund_id=uuid4(),
            actor_id=admin,
            now=clock.now(),
            session=session,
        )
    authority = Repository(admin)
    authority.ledger = repo
    proofs = Proofs()
    service = DebtRecoveryService(authority, ledger, proofs, clock)
    observation = RecordDebtRepayment(
        actor_id=admin,
        operation_key="incoming",
        recipient_id=issue.basis.recipient_id,
        case_id=case,
        amount_minor=2000,
        currency="RUB",
        bank_account_label="test-account",
        bank_reference="real-synthetic-incoming",
        occurred_at=clock.now(),
        reason="Test actual repayment",
        evidence_reference="synthetic statement",
        evidence_hash="a" * 64,
    )
    return repo, ledger, issue, case, authority, service, observation


@pytest.mark.asyncio
async def test_actual_incoming_recovers_case_preserving_paid():
    repo, ledger, issue, case, authority, service, observation = await fixture()
    async with repo.transaction() as session:
        receipt = await service.observe(observation, session=session)
        assert receipt["applied"] is False
        assert await service.observe(observation, session=session) == receipt
        apply = ApplyDebtRecovery(
            actor_id=observation.actor_id,
            operation_key="apply",
            observation_id=UUID(receipt["observation_id"]),
            business_key=issue.basis.business_key,
            case_id=case,
            expected_debt_minor=3000,
            reason="Verify statement",
            evidence_reference="reviewed statement",
            evidence_hash="b" * 64,
        )
        result = await service.apply(apply, session=session)
        assert result["recovered_minor"] == 2000
        assert await service.apply(apply, session=session) == result
        report = await FinancialReconciliationService(repo).require_ready(
            issue.basis.recipient_id, "RUB", session=session
        )
        assert report.replay.balances["debt"] == 1000
        assert report.replay.balances["paid"] == 5000
        assert report.replay.balances["available"] == 0


@pytest.mark.asyncio
async def test_overpayment_is_retained_without_recovery():
    from dataclasses import replace

    repo, ledger, issue, case, authority, service, observation = await fixture()
    async with repo.transaction() as session:
        receipt = await service.observe(
            replace(observation, amount_minor=4000), session=session
        )
        apply = ApplyDebtRecovery(
            actor_id=observation.actor_id,
            operation_key="apply",
            observation_id=UUID(receipt["observation_id"]),
            business_key=issue.basis.business_key,
            case_id=case,
            expected_debt_minor=3000,
            reason="Review surplus",
            evidence_reference="statement",
            evidence_hash="b" * 64,
        )
        with pytest.raises(ValueError, match="exceeds"):
            await service.apply(apply, session=session)
        assert authority.observations
        assert (
            await FinancialReconciliationService(repo).require_ready(
                issue.basis.recipient_id, "RUB", session=session
            )
        ).replay.balances["debt"] == 3000


@pytest.mark.asyncio
async def test_repayment_rejects_changed_request_session_and_future_fact():
    from dataclasses import replace
    from datetime import timedelta

    from ugc_bot.application.native_principal_ports import (
        AuthenticatedMessengerPrincipal,
    )

    repo, _, _, _, _, service, observation = await fixture()
    async with repo.transaction() as session:
        with pytest.raises(ValueError, match="financial_principal_changed"):
            await service.observe(
                observation,
                session=session,
                principal=AuthenticatedMessengerPrincipal(
                    observation.actor_id, "telegram", "foreign-account"
                ),
            )
        with pytest.raises(ValueError, match="future_observation"):
            await service.observe(
                replace(
                    observation,
                    occurred_at=observation.occurred_at + timedelta(seconds=1),
                ),
                session=session,
            )
        await service.observe(observation, session=session)
        with pytest.raises(ValueError, match="idempotency"):
            await service.observe(
                replace(observation, reason="Different decision"),
                session=session,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    ["source", "scope", "version", "proof_changed", "proof_owner", "time"],
)
async def test_recovery_requires_exact_retained_source_and_current_debt(
    invalid,
):
    from dataclasses import replace
    from datetime import timedelta

    repo, ledger, issue, case, authority, service, observation = await fixture()
    async with repo.transaction() as session:
        receipt = await service.observe(observation, session=session)
        command = ApplyDebtRecovery(
            actor_id=observation.actor_id,
            operation_key="apply",
            observation_id=UUID(receipt["observation_id"]),
            business_key=issue.basis.business_key,
            case_id=case,
            expected_debt_minor=3000,
            reason="Reviewed",
            evidence_reference="statement",
            evidence_hash="c" * 64,
        )
        if invalid == "source":
            command = replace(command, observation_id=uuid4())
        elif invalid == "scope":
            command = replace(command, case_id=uuid4())
        elif invalid == "version":
            command = replace(command, expected_debt_minor=2999)
        elif invalid == "proof_changed":
            authority.observations[command.observation_id]["identity"][
                "account"
            ] = "different"
        elif invalid == "proof_owner":
            service.physical_proofs.claims.clear()
        else:
            service.clock = NS(
                now=lambda: observation.occurred_at - timedelta(seconds=1)
            )
        with pytest.raises(ValueError, match="repayment_"):
            await service.apply(command, session=session)
        assert not authority.applications
        report = await FinancialReconciliationService(repo).require_ready(
            issue.basis.recipient_id, "RUB", session=session
        )
        assert report.replay.debt == 3000


@pytest.mark.asyncio
async def test_recovery_retry_reuses_original_application():
    from dataclasses import replace

    repo, _, issue, case, _, service, observation = await fixture()
    async with repo.transaction() as session:
        receipt = await service.observe(observation, session=session)
        command = ApplyDebtRecovery(
            actor_id=observation.actor_id,
            operation_key="first",
            observation_id=UUID(receipt["observation_id"]),
            business_key=issue.basis.business_key,
            case_id=case,
            expected_debt_minor=3000,
            reason="Review",
            evidence_reference="statement",
            evidence_hash="a" * 64,
        )
        first = await service.apply(command, session=session)
        assert (
            await service.apply(
                replace(command, operation_key="explicit retry"),
                session=session,
            )
            == first
        )


async def second_paid_ground(repo, ledger, first):
    """A second independently issued and paid ground for the same recipient."""
    from dataclasses import replace

    transfers = [
        entry
        for entry in repo.movements.values()
        if entry.obligation_id == first.obligation_id
        and entry.movement_type == "transfer"
    ]
    basis = replace(
        first.basis,
        business_key="item:second-client",
        paid_item_id=uuid4(),
        event_id="capture:second",
    )
    request_id, allocation_id, execution_id = uuid4(), uuid4(), uuid4()
    async with repo.transaction() as session:
        second = await ledger.issue(
            basis, recorded_at=basis.snapshot_at, session=session
        )
        for entry in transfers:
            movement = replace(
                entry,
                obligation_id=second.obligation_id,
                operation_key="second:" + entry.operation_key,
                request_id=request_id if entry.request_id else None,
                allocation_id=allocation_id if entry.allocation_id else None,
                execution_id=execution_id if entry.execution_id else None,
            )
            await repo.append(movement, session=session)
            await repo.apply_projection(movement, session=session)
    return second


@pytest.mark.asyncio
async def test_one_incoming_repays_case_grounds_preserving_paid():
    from dataclasses import replace

    repo, ledger, first, case, authority, service, observation = await fixture()
    second = await second_paid_ground(repo, ledger, first)
    async with repo.transaction() as session:
        await ObligationCompensationService(ledger).cancel(
            second,
            target_minor=3000,
            already_cancelled_minor=0,
            case_id=case,
            refund_id=uuid4(),
            actor_id=observation.actor_id,
            now=service.clock.now(),
            session=session,
        )
        receipt = await service.observe(
            replace(observation, amount_minor=5000), session=session
        )
        command = ApplyDebtRecovery(
            actor_id=observation.actor_id,
            operation_key="apply-batch",
            observation_id=UUID(receipt["observation_id"]),
            business_key=first.basis.business_key,
            case_id=case,
            expected_debt_minor=6000,
            reason="One reviewed incoming transfer",
            evidence_reference="synthetic statement",
            evidence_hash="d" * 64,
        )
        result = await service.apply(command, session=session)
        assert result["recovered_minor"] == 5000
        assert result["remaining_debt_minor"] == 1000
        assert len(result["applications"]) == 2
        allocations = result["applications"]
        assert [row["obligation_id"] for row in allocations] == sorted(
            (str(first.obligation_id), str(second.obligation_id))
        )
        assert [row["recovered_minor"] for row in allocations] == [3000, 2000]
        assert await service.apply(command, session=session) == result
        report = await FinancialReconciliationService(repo).require_ready(
            first.basis.recipient_id,
            "RUB",
            session=session,
        )
        assert report.replay.balances["paid"] == 10000
        assert report.replay.balances["debt"] == 1000
        assert report.replay.balances["available"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "amount, portions",
    [(1, [1]), (3000, [3000]), (3001, [3000, 1]), (6000, [3000, 3000])],
)
async def test_case_allocation_boundaries_and_later_repayment(amount, portions):
    from dataclasses import replace

    repo, ledger, first, case, authority, service, observation = await fixture()
    second = await second_paid_ground(repo, ledger, first)
    async with repo.transaction() as session:
        await ObligationCompensationService(ledger).cancel(
            second,
            target_minor=3000,
            already_cancelled_minor=0,
            case_id=case,
            refund_id=uuid4(),
            actor_id=observation.actor_id,
            now=service.clock.now(),
            session=session,
        )
        receipt = await service.observe(
            replace(observation, amount_minor=amount), session=session
        )
        command = ApplyDebtRecovery(
            actor_id=observation.actor_id,
            operation_key="boundary",
            observation_id=UUID(receipt["observation_id"]),
            business_key=first.basis.business_key,
            case_id=case,
            expected_debt_minor=6000,
            reason="Reviewed boundary",
            evidence_reference="synthetic statement",
            evidence_hash="e" * 64,
        )
        result = await service.apply(command, session=session)
        assert [
            entry["recovered_minor"] for entry in result["applications"]
        ] == portions
        assert result["remaining_debt_minor"] == 6000 - amount
        if amount == 6000:
            return
        later = await service.observe(
            replace(
                observation,
                operation_key="later incoming",
                bank_reference="later physical transfer",
                amount_minor=6000 - amount,
            ),
            session=session,
        )
        final = await service.apply(
            replace(
                command,
                operation_key="later review",
                observation_id=UUID(later["observation_id"]),
                expected_debt_minor=6000 - amount,
            ),
            session=session,
        )
        assert final["remaining_debt_minor"] == 0
        assert (
            sum(entry["recovered_minor"] for entry in final["applications"])
            == 6000 - amount
        )
        assert (
            await FinancialReconciliationService(repo).require_ready(
                first.basis.recipient_id,
                "RUB",
                session=session,
            )
        ).replay.balances["paid"] == 10000


@pytest.mark.asyncio
async def test_recovery_excludes_other_case_and_nonmember_anchor():
    from dataclasses import replace

    repo, ledger, first, case, authority, service, observation = await fixture()
    second = await second_paid_ground(repo, ledger, first)
    async with repo.transaction() as session:
        await ObligationCompensationService(ledger).cancel(
            second,
            target_minor=3000,
            already_cancelled_minor=0,
            case_id=uuid4(),
            refund_id=uuid4(),
            actor_id=observation.actor_id,
            now=service.clock.now(),
            session=session,
        )
        receipt = await service.observe(observation, session=session)
        command = ApplyDebtRecovery(
            actor_id=observation.actor_id,
            operation_key="foreign anchor",
            observation_id=UUID(receipt["observation_id"]),
            business_key=second.basis.business_key,
            case_id=case,
            expected_debt_minor=6000,
            reason="Reviewed bank source",
            evidence_reference="synthetic statement",
            evidence_hash="f" * 64,
        )
        with pytest.raises(ValueError, match="scope_mismatch"):
            await service.apply(command, session=session)
        with pytest.raises(ValueError, match="debt_version_conflict"):
            await service.apply(
                replace(command, business_key=first.basis.business_key),
                session=session,
            )
        result = await service.apply(
            replace(
                command,
                business_key=first.basis.business_key,
                expected_debt_minor=3000,
            ),
            session=session,
        )
        assert result["remaining_debt_minor"] == 1000
        assert (
            await FinancialReconciliationService(repo).require_ready(
                first.basis.recipient_id,
                "RUB",
                session=session,
            )
        ).replay.balances["debt"] == 4000


def recovery_command(issue, observation, receipt, **changes):
    return ApplyDebtRecovery(
        **(
            dict(
                actor_id=observation.actor_id,
                operation_key="review edge",
                observation_id=UUID(receipt["observation_id"]),
                business_key=issue.basis.business_key,
                case_id=observation.case_id,
                expected_debt_minor=3000,
                reason="Reviewed statement",
                evidence_reference="synthetic statement",
                evidence_hash="a" * 64,
            )
            | changes
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    ["scope_changed", "ground_missing", "case_changed", "source_missing"],
)
async def test_unstable_case_or_missing_original_never_writes_recovery(
    invalid, monkeypatch
):
    repo, ledger, issue, case, authority, service, observation = await fixture()
    async with repo.transaction() as session:
        receipt = await service.observe(observation, session=session)
        command = recovery_command(issue, observation, receipt)
        if invalid == "scope_changed":
            original_get = repo.get_issue
            calls = 0

            async def changing(key, *, session):
                nonlocal calls
                calls += 1
                return (
                    await original_get(key, session=session)
                    if calls == 1
                    else None
                )

            monkeypatch.setattr(repo, "get_issue", changing)
        elif invalid == "ground_missing":

            async def missing(*args, session):
                return (issue.basis.business_key, "missing original")

            monkeypatch.setattr(authority, "case_grounds", missing)
        elif invalid == "case_changed":
            calls = 0

            async def changed(*args, session):
                nonlocal calls
                calls += 1
                return (issue.basis.business_key,) if calls == 1 else ()

            monkeypatch.setattr(authority, "case_grounds", changed)
        else:
            original_ref = repo.get_entry_ref

            async def no_original(key, *, session):
                if key == issue.movement.operation_key:
                    return None
                return await original_ref(key, session=session)

            monkeypatch.setattr(repo, "get_entry_ref", no_original)
        with pytest.raises(ValueError, match="repayment_"):
            await service.apply(command, session=session)
        assert not authority.applications
        assert not any(
            entry.movement_type == "recovery"
            for entry in repo.movements.values()
        )


@pytest.mark.asyncio
async def test_existing_bank_receipt_cannot_be_rebound_to_another_case_member():
    from dataclasses import replace

    repo, ledger, first, case, authority, service, observation = await fixture()
    second = await second_paid_ground(repo, ledger, first)
    async with repo.transaction() as session:
        await ObligationCompensationService(ledger).cancel(
            second,
            target_minor=3000,
            already_cancelled_minor=0,
            case_id=case,
            refund_id=uuid4(),
            actor_id=observation.actor_id,
            now=service.clock.now(),
            session=session,
        )
        receipt = await service.observe(observation, session=session)
        command = recovery_command(
            first, observation, receipt, expected_debt_minor=6000
        )
        await service.apply(command, session=session)
        with pytest.raises(ValueError, match="already_applied"):
            await service.apply(
                replace(
                    command,
                    operation_key="new review",
                    business_key=second.basis.business_key,
                ),
                session=session,
            )


@pytest.mark.asyncio
async def test_current_admin_and_recipient_required_before_bank_claim(
    monkeypatch,
):
    from dataclasses import replace

    from ugc_bot.application.physical_proof_ports import (
        PhysicalProofUnavailable,
    )

    repo, _, issue, _, authority, service, observation = await fixture()
    async with repo.transaction() as session:
        with pytest.raises(PermissionError, match="active_admin"):
            await service.observe(
                replace(observation, actor_id=uuid4()), session=session
            )
        authority_actor = authority.actor

        async def missing(actor_id, *, session):
            return (
                None
                if actor_id == issue.basis.recipient_id
                else await authority_actor(actor_id, session=session)
            )

        monkeypatch.setattr(authority, "actor", missing)
        with pytest.raises(ValueError, match="recipient_not_found"):
            await service.observe(observation, session=session)
        monkeypatch.setattr(authority, "actor", authority_actor)

        def unavailable(*args, direction):
            raise PhysicalProofUnavailable()

        monkeypatch.setattr(
            service.physical_proofs, "resolve_manual_identity", unavailable
        )
        result = await service.observe(observation, session=session)
        assert result["proof_claimed"] is False and result["applied"] is False
        assert (
            authority.observations[UUID(result["observation_id"])]["identity"]
            is None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "values",
    [
        dict(page=True),
        dict(page=-1),
        dict(page=100001),
        dict(limit=True),
        dict(limit=0),
        dict(limit=101),
    ],
)
async def test_debt_context_pagination_rejects_invalid_boundaries(values):
    repo, _, _, _, _, service, observation = await fixture()
    async with repo.transaction() as session:
        with pytest.raises(ValueError, match="invalid_page"):
            await service.context(
                observation.actor_id, session=session, **values
            )


def test_repayment_unpublished_currency_is_rejected():
    from datetime import datetime, timezone

    with pytest.raises(ValueError, match="unpublished_currency"):
        RecordDebtRepayment(
            actor_id=uuid4(),
            operation_key="currency",
            recipient_id=uuid4(),
            case_id=uuid4(),
            amount_minor=1,
            currency="USD",
            bank_account_label="synthetic",
            bank_reference="synthetic",
            occurred_at=datetime.now(timezone.utc),
            reason="Synthetic",
            evidence_reference="Synthetic",
            evidence_hash="a" * 64,
        )

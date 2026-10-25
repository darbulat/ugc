"""A positive grant is a distinct approved expense; prices stay frozen."""

from dataclasses import fields, replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.application.services.test_work_entitlement_service import START
from ugc_bot.application.financial_ports import IssueBasis
from ugc_bot.application.manual_grant_ports import ManualGrantSource
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.infrastructure.memory_financial_ledger import (
    InMemoryFinancialLedgerRepository,
)


def grant_and_basis():
    source = ManualGrantSource(
        grant_id=uuid4(),
        actor_id=uuid4(),
        recipient_id=uuid4(),
        paid_item_id=uuid4(),
        order_id=uuid4(),
        client_id=uuid4(),
        payment_id=uuid4(),
        capture_id=uuid4(),
        policy_version="approved:test",
        amount_minor=12345,
        currency="RUB",
        approved_at=START,
        release_at=START + timedelta(days=14),
        reason="Reviewed missed income compensation",
    )
    basis = IssueBasis(
        business_key="manual-grant:" + str(source.grant_id),
        kind="manual_adjustment",
        recipient_id=source.recipient_id,
        paid_item_id=source.paid_item_id,
        order_id=source.order_id,
        assignment_id=None,
        referred_user_id=source.client_id,
        payment_id=source.payment_id,
        currency="RUB",
        base_minor=source.amount_minor,
        rate_bps=None,
        policy_version=source.policy_version,
        snapshot_at=source.approved_at,
        registered_at=None,
        verified_count=None,
        event_id=str(source.grant_id),
        reason=source.reason,
        actor_id=source.actor_id,
        actor_kind="admin",
        available_at=source.release_at,
    )
    return source, basis


@pytest.mark.asyncio
async def test_manual_issue_requires_actual_source_without_referral_rate():
    source, basis = grant_and_basis()
    ledger = InMemoryFinancialLedgerRepository()
    service = FinancialLedgerService(ledger)
    async with ledger.transaction() as session:
        with pytest.raises(ValueError, match="manual_grant_approval_required"):
            await service.issue(basis, recorded_at=START, session=session)
        ledger.manual_grant_sources[source.grant_id] = source
        original = await service.issue(
            basis, recorded_at=START, session=session
        )
        assert (
            await service.issue(basis, recorded_at=START, session=session)
            == original
        )
    assert original.movement.amount_minor == 12345
    assert original.basis.rate_bps is original.basis.verified_count is None
    assert original.basis.kind == "manual_adjustment"


def service_scenario():
    from tests.application.services.test_work_entitlement_service import setup
    from ugc_bot.application.services.manual_grant_service import (
        ManualGrantService,
    )

    _, ledger, _, clock, _, _, _ = setup()
    capture = setup()[0].snapshot.capture
    admin_id, recipient = uuid4(), uuid4()

    class Repo:
        commands, grants = {}, {}
        actors = {
            admin_id: SimpleNamespace(
                user_id=admin_id,
                admin=True,
                status="active",
                telegram_id="admin-tg",
                max_id=None,
            ),
            recipient: SimpleNamespace(
                user_id=recipient,
                admin=False,
                status="active",
                telegram_id="recipient-tg",
                max_id=None,
            ),
        }
        changed = False

        async def load_capture(self, item_id, *, session):
            return (
                replace(capture, source_hash="changed")
                if self.changed
                else capture
            )

        async def lock_funding(self, source, *, session):
            pass

        async def actor(self, identity, *, session):
            return self.actors.get(identity)

        async def require_work_clear(self, item, *, session):
            pass

        async def command(self, actor, key, *, session):
            return self.commands.get(key)

        async def save_command(
            self, actor, key, digest, result, now, *, session
        ):
            self.commands[key] = {"payload_hash": digest, "result": result}

        async def append_grant(self, fact, *, session):
            source = ManualGrantSource(
                **{f.name: fact[f.name] for f in fields(ManualGrantSource)}
            )
            self.grants[source.grant_id] = source
            ledger.manual_grant_sources[source.grant_id] = source

        async def source(self, grant_id, *, session):
            return self.grants.get(grant_id)

        async def list_ready(self, now, limit, *, after=None, session):
            return tuple(
                sorted(
                    (v.release_at, k)
                    for k, v in self.grants.items()
                    if v.release_at <= now
                    and (after is None or (v.release_at, k) > after)
                )
            )[:limit]

    class Guard:
        blocked = False

        async def require_forward_clear(self, *args, **kwargs):
            if self.blocked:
                raise ValueError("correction_unresolved")

    repo, guard = Repo(), Guard()
    service = ManualGrantService(
        repo,
        FinancialLedgerService(ledger),
        guard,
        clock,
        {admin_id},
        enabled=True,
    )
    from ugc_bot.application.manual_grant_ports import ApproveManualGrant

    command = ApproveManualGrant(
        actor_id=admin_id,
        operation_key="reviewed-positive-adjustment",
        paid_item_id=capture.items[0].paid_item_id,
        recipient_id=recipient,
        amount_minor=12345,
        currency="RUB",
        reason="Reviewed missed payout outside canonical reward",
        evidence_reference="private:grant-proof",
        evidence_hash="a" * 64,
    )
    return service, repo, ledger, clock, guard, command


@pytest.mark.asyncio
async def test_positive_grant_replays_and_matures_after_14_days():
    from uuid import UUID

    service, repo, ledger, clock, _, command = service_scenario()
    async with ledger.transaction() as session:
        result = await service.approve(command, session=session)
        assert await service.approve(command, session=session) == result
        wallet = await ledger.read_projection(
            command.recipient_id, "RUB", session=session
        )
        assert wallet["hold"] == 12345 and wallet["available"] == 0
        assert not (
            await service.mature(UUID(result["grant_id"]), session=session)
        )["mature"]
        with pytest.raises(ValueError, match="idempotency_payload_conflict"):
            await service.approve(
                replace(command, amount_minor=1), session=session
            )
    service.superadmins = frozenset()
    async with ledger.transaction() as session:
        with pytest.raises(
            PermissionError, match="financial_superadmin_required"
        ):
            await service.approve(command, session=session)
    clock.at += timedelta(days=14)
    async with ledger.transaction() as session:
        assert (
            await service.mature(UUID(result["grant_id"]), session=session)
        )["mature"]
        await service.mature(UUID(result["grant_id"]), session=session)
        wallet = await ledger.read_projection(
            command.recipient_id, "RUB", session=session
        )
        assert wallet["hold"] == 0 and wallet["available"] == 12345
    assert len(repo.grants) == len(ledger.records) == 1


@pytest.mark.asyncio
async def test_grants_require_current_admin_native_identity_and_clear_item():
    from ugc_bot.application.native_principal_ports import (
        AuthenticatedMessengerPrincipal,
    )

    service, repo, ledger, _, guard, command = service_scenario()
    async with ledger.transaction() as session:
        with pytest.raises(ValueError, match="financial_principal_changed"):
            await service.approve(
                command,
                session=session,
                principal=AuthenticatedMessengerPrincipal(
                    command.actor_id, "telegram", "old-tg-id"
                ),
            )
        repo.actors[command.actor_id].admin = False
        with pytest.raises(
            PermissionError, match="financial_superadmin_required"
        ):
            await service.approve(command, session=session)
        repo.actors[command.actor_id].admin = True
        guard.blocked = True
        with pytest.raises(ValueError, match="correction_unresolved"):
            await service.approve(command, session=session)
    assert not repo.grants and not ledger.records


@pytest.mark.parametrize(
    "raw", ("not-uuid", "[1]", "[null]", "00000000-0000-0000-0000-000000000000")
)
def test_superadmin_configuration_rejects_ambiguous_authority(raw):
    from pydantic import ValidationError

    from ugc_bot.config import FinancialConfig

    with pytest.raises(ValidationError):
        FinancialConfig.model_validate({"FINANCIAL_SUPERADMIN_USER_IDS": raw})


def test_superadmin_configuration_defaults_closed_and_accepts_explicit_ids():
    from ugc_bot.config import FinancialConfig

    actor = uuid4()
    assert not FinancialConfig.model_validate({}).superadmin_user_ids()
    assert FinancialConfig.model_validate(
        {"FINANCIAL_SUPERADMIN_USER_IDS": str(actor)}
    ).superadmin_user_ids() == {actor}
    assert FinancialConfig.model_validate(
        {"FINANCIAL_SUPERADMIN_USER_IDS": '["' + str(actor) + '"]'}
    ).superadmin_user_ids() == {actor}


@pytest.mark.asyncio
async def test_receipt_replays_after_source_block_but_new_grant_refuses():
    service, repo, ledger, _, guard, command = service_scenario()
    async with ledger.transaction() as session:
        receipt = await service.approve(command, session=session)
    guard.blocked = True
    repo.actors[command.recipient_id].status = "disabled"
    async with ledger.transaction() as session:
        assert await service.approve(command, session=session) == receipt
        with pytest.raises(
            ValueError, match="manual_grant_recipient_unavailable"
        ):
            await service.approve(
                replace(command, operation_key="fresh-unavailable-target"),
                session=session,
            )

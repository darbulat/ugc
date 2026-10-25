"""Manual closure requires resolved sources and current signed authority."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from tests.application.services.test_client_entitlement_service import scenario
from ugc_bot.application.collaboration_ports import CollaborationActor
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.selection_maturity_ports import (
    SelectionPosition,
    SelectionSnapshot,
)
from ugc_bot.application.services.selection_maturity_service import (
    SelectionMaturityService,
)
from ugc_bot.domain.refund_rules import RefundRules


async def fixture(mode="manual", resolved=True):
    issuer, capture_source, ledger, _, _, event = await scenario()
    async with ledger.transaction() as session:
        await issuer.handle(event, session=session)
    capture = capture_source.capture
    rules = RefundRules(
        int(capture.policy.selection_refund_window.total_seconds()),
        "item_delivered",
        mode,
        (),
        "retain_earned",
    )
    at = capture.captured_at + timedelta(hours=1)
    position = SelectionPosition(
        capture.items[0].paid_item_id,
        delivered_at=at if resolved else None,
        delivery_id=uuid4() if resolved else None,
    )
    snapshot = SelectionSnapshot(
        capture.order_id,
        capture.client_id,
        capture.payment_id,
        replace(capture.policy, refund_rules=rules),
        capture.captured_at,
        (position,),
    )

    class Repo:
        source = snapshot
        actor = CollaborationActor(
            capture.client_id, "active", is_client=True, telegram_id="123"
        )
        closed = None
        calls = 0
        changed = None

        async def load(self, order_id, *, session):
            self.calls += 1
            return (
                self.changed
                if self.calls % 2 == 0 and self.changed
                else self.source
            )

        async def lock_order(self, *args, session):
            pass

        async def get_closure(self, *args, session):
            return self.closed

        async def save_closure(self, value, *, session):
            self.closed = value
            return value

        async def save_schedule(self, value, *, session):
            issue = next(iter(ledger.records.values()))
            ledger.selection_maturity_sources[issue.obligation_id] = value
            return value

        async def require_clear(self, *args, session):
            pass

        async def load_actor(self, *args, session):
            return self.actor

    repo = Repo()
    clock = NS(now=lambda: at)
    return (
        SelectionMaturityService(repo, issuer.ledger, clock),
        repo,
        ledger,
        snapshot,
    )


@pytest.mark.asyncio
async def test_manual_closure_waits_for_explicit_evidence_and_is_immutable():
    service, repo, ledger, source = await fixture()
    async with ledger.transaction() as session:
        assert (await service.refresh(source.order_id, session=session))[
            "state"
        ] == "awaiting_manual_closure"
        with pytest.raises(ValueError, match="evidence_required"):
            await service.refresh(
                source.order_id, actor_id=source.client_id, session=session
            )
        result = await service.refresh(
            source.order_id,
            actor_id=source.client_id,
            reason="Actual resolved order",
            evidence="All source records reviewed",
            session=session,
        )
        assert result["state"] == "closed"
        assert repo.closed.actor_id == source.client_id
        assert (
            await service.refresh(
                source.order_id, actor_id=source.client_id, session=session
            )
            == result
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid", ["missing", "foreign", "inactive", "session"]
)
async def test_manual_closure_cannot_use_foreign_or_changed_identity(invalid):
    service, repo, ledger, source = await fixture()
    principal = None
    if invalid == "missing":
        repo.actor = None
    elif invalid == "foreign":
        repo.actor = CollaborationActor(uuid4(), "active", is_client=True)
    elif invalid == "inactive":
        repo.actor = replace(repo.actor, status="deleted")
    else:
        principal = AuthenticatedMessengerPrincipal(
            source.client_id, "telegram", "wrong-native"
        )
    async with ledger.transaction() as session:
        with pytest.raises(
            (ValueError, PermissionError), match="forbidden|principal_changed"
        ):
            await service.refresh(
                source.order_id,
                actor_id=source.client_id,
                reason="review",
                evidence="proof",
                principal=principal,
                session=session,
            )
        assert repo.closed is None


@pytest.mark.asyncio
async def test_unresolved_order_cannot_be_closed_manually():
    service, repo, ledger, source = await fixture(resolved=False)
    async with ledger.transaction() as session:
        result = await service.refresh(
            source.order_id,
            actor_id=source.client_id,
            reason="review",
            evidence="proof",
            session=session,
        )
        assert result["state"] == "partially_fulfilled" and repo.closed is None


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["changed", "future", "rules"])
async def test_selection_closure_checks_live_source_and_stored_rules(invalid):
    service, repo, ledger, source = await fixture()
    if invalid == "changed":
        repo.changed = replace(source, payment_id=uuid4())
    elif invalid == "future":
        service.clock = NS(
            now=lambda: source.captured_at - timedelta(seconds=1)
        )
    else:
        repo.source = replace(
            source, policy=replace(source.policy, refund_rules=None)
        )
    async with ledger.transaction() as session:
        with pytest.raises(
            ValueError, match="scope_changed|in_future|rules_required"
        ):
            await service.refresh(source.order_id, session=session)
        assert repo.closed is None

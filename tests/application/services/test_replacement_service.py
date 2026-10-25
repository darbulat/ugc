"""Reserve promotion uses original paid capacity and real current authority."""

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.replacement_ports import (
    ReplacementCandidate,
    ReplacementDecision,
    ReplacementRequest,
    ReplacementScope,
)
from ugc_bot.application.services.replacement_service import ReplacementService

NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)
ADMIN, CLIENT, OLD, NEW, ITEM, ORDER, ASSIGNMENT, INTEREST, PAYMENT, EVENT = (
    UUID(int=i) for i in range(1, 11)
)
ADMIN_PROOF = AuthenticatedMessengerPrincipal(ADMIN, "telegram", "native-admin")
CLIENT_PROOF = AuthenticatedMessengerPrincipal(
    CLIENT, "telegram", "native-client"
)


class Repository:
    def __init__(self):
        self.scope = ReplacementScope(
            ITEM,
            ORDER,
            CLIENT,
            PAYMENT,
            EVENT,
            "policy",
            NOW,
            "capture-hash",
            30,
            "delivered",
            True,
            ASSIGNMENT,
            1,
            OLD,
            None,
            NOW,
            (ASSIGNMENT,),
            (OLD,),
            (),
            False,
            0,
            False,
        )
        self.candidate_row = ReplacementCandidate(
            INTEREST,
            ORDER,
            NEW,
            PAYMENT,
            EVENT,
            "policy",
            NOW,
            "ig-new",
            "https://instagram.com/new",
            True,
            False,
        )
        self.actor = {
            ADMIN: SimpleNamespace(
                user_id=ADMIN,
                status="active",
                is_admin=True,
                is_client=False,
                telegram_id="native-admin",
                max_id=None,
            ),
            CLIENT: SimpleNamespace(
                user_id=CLIENT,
                status="active",
                is_admin=False,
                is_client=True,
                telegram_id="native-client",
                max_id=None,
            ),
        }
        self.receipts, self.requests, self.decisions, self.calls = (
            {},
            {},
            {},
            [],
        )
        self.allocations, self.contacts = {}, []

    async def load_scope(self, item, *, session):
        return self.scope

    async def lock_scope(self, source, *, session):
        pass

    async def load_actor(self, actor, *, session):
        return self.actor.get(actor)

    async def candidate(self, identity, *, session):
        return self.candidate_row if identity == INTEREST else None

    async def get_command(self, actor, operation, *, session):
        return self.receipts.get((actor, operation))

    async def save_command(self, actor, operation, digest, result, *, session):
        self.receipts[actor, operation] = (digest, result)

    async def append_request(self, fact, *, session):
        self.requests[fact["request_id"]] = fact

    async def request(self, identity, *, session):
        return self.requests.get(identity)

    async def decision(self, identity, *, session):
        return self.decisions.get(identity)

    async def append_decision(self, fact, *, session):
        self.calls.append("authority")
        self.decisions[fact["request_id"]] = fact

    async def replace_assignment(
        self, source, candidate, manager, actor, reason, at, *, session
    ):
        self.calls.append("assignment")
        new_id = UUID(int=100)
        self.scope = replace(
            source,
            assignment_id=new_id,
            assignment_version=2,
            creator_id=NEW,
            replacement_count=source.replacement_count + 1,
        )
        return new_id

    async def append_allocation(self, fact, *, session):
        self.calls.append("allocation")
        self.allocations[fact["replacement_id"]] = fact

    async def require_clear(self, item, *, session):
        pass

    async def allocation(self, identity, *, session):
        return self.allocations.get(identity)

    async def contact(self, source, *, session):
        return {"creator_id": str(source.creator_id)}

    async def append_contact(self, fact, *, session):
        self.contacts.append(fact)

    async def view(self, scope, *, admin, session):
        return dict(candidates=[], history=[])

    async def queue(self, page, *, session):
        return dict(entries=[], page=page, has_more=False)


class Ledger:
    def __init__(self):
        self.repository = self
        self.grounds = []

    async def list_item_grounds(self, item, kind, *, session):
        return [g for g in self.grounds if g.kind == kind]

    async def lock_recipients(self, users, *, session):
        self.locked = users

    async def lock_wallets(self, keys, *, session):
        pass

    async def lock_item(self, item, *, session):
        pass

    async def get_issue(self, key, *, session):
        return SimpleNamespace(
            obligation_id=UUID(int=300),
            basis=SimpleNamespace(
                paid_item_id=ITEM,
                order_id=ORDER,
                assignment_id=ASSIGNMENT,
                payment_id=PAYMENT,
                kind="creator_referral",
                recipient_id=CLIENT,
                currency="RUB",
            ),
            movement=SimpleNamespace(amount_minor=5000),
        )

    async def list_for_recipient(self, recipient, currency, *, session):
        return ()


class Compensation:
    def __init__(self, repo):
        self.repo = repo

    async def cancel(self, original, **kwargs):
        assert self.repo.decisions, (
            "immutable authority must precede cancellation"
        )
        self.repo.calls.append("cancel")
        return (UUID(int=301),)


def setup():
    repo, ledger = Repository(), Ledger()
    app = ReplacementService(
        repo,
        ledger,
        Compensation(repo),
        SimpleNamespace(now=lambda: NOW),
        enabled=True,
    )
    return repo, ledger, app


async def request(app, actor=CLIENT, proof=CLIENT_PROOF):
    return await app.request(
        ReplacementRequest(
            "request-1",
            actor,
            ITEM,
            1,
            INTEREST,
            "lost_contact",
            "Автор не отвечает",
            "support:case-1",
        ),
        principal=proof,
        session=object(),
    )


def approve(request_id, **kwargs):
    return ReplacementDecision(
        "approve-1",
        ADMIN,
        UUID(request_id),
        1,
        "approve",
        "Основания проверены",
        "support:review-1",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_replacement_cancels_original_before_new_assignment_and_replays():
    repo, ledger, app = setup()
    ledger.grounds.append(
        SimpleNamespace(
            kind="creator_referral",
            business_key="old",
            recipient_id=CLIENT,
            currency="RUB",
            obligation_id=UUID(int=300),
        )
    )
    pending = await request(app)
    result = await app.decide(
        approve(pending["request_id"]), principal=ADMIN_PROOF, session=object()
    )
    assert repo.calls == ["authority", "cancel", "assignment", "allocation"]
    assert result["original_paid_pool"] == 30 and result["reserve_limit"] == 6
    assert (
        result["assignment_version"] == 2
        and result["billable_positions_added"] == 0
    )
    assert (
        await app.decide(
            approve(pending["request_id"]),
            principal=ADMIN_PROOF,
            session=object(),
        )
        == result
    )
    repo.actor[ADMIN].is_admin = False
    with pytest.raises(PermissionError, match="active_admin_required"):
        await app.decide(
            approve(pending["request_id"]),
            principal=ADMIN_PROOF,
            session=object(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("pool,used", [(30, 6), (4, 0)])
async def test_above_original_floor_twenty_percent_needs_explicit_review(
    pool, used
):
    repo, _, app = setup()
    repo.scope = replace(
        repo.scope, original_paid_pool=pool, replacement_count=used
    )
    pending = await request(app)
    with pytest.raises(
        ValueError, match="replacement_reserve_exception_required"
    ):
        await app.decide(
            approve(pending["request_id"]),
            principal=ADMIN_PROOF,
            session=object(),
        )
    assert repo.calls == []
    result = await app.decide(
        approve(
            pending["request_id"],
            exception_reason="Согласована дополнительная замена",
            exception_evidence="agreement:extra-1",
        ),
        principal=ADMIN_PROOF,
        session=object(),
    )
    assert result["reserve_exception"] is True


@pytest.mark.asyncio
async def test_success_or_changed_assignment_cannot_be_replaced():
    repo, _, app = setup()
    pending = await request(app)
    repo.scope = replace(repo.scope, completed_work=True)
    with pytest.raises(
        ValueError, match="replacement_after_completed_work_forbidden"
    ):
        await app.decide(
            approve(pending["request_id"]),
            principal=ADMIN_PROOF,
            session=object(),
        )
    repo.scope = replace(repo.scope, completed_work=False, assignment_version=2)
    with pytest.raises(
        ValueError, match="replacement_assignment_version_conflict"
    ):
        await app.decide(
            approve(pending["request_id"]),
            principal=ADMIN_PROOF,
            session=object(),
        )
    assert repo.calls == []


@pytest.mark.asyncio
async def test_client_cannot_approve_or_use_an_unconfirmed_reserve_candidate():
    repo, _, app = setup()
    repo.candidate_row = replace(repo.candidate_row, verified=False)
    with pytest.raises(
        ValueError, match="replacement_confirmed_reserve_required"
    ):
        await request(app)
    repo.candidate_row = replace(repo.candidate_row, verified=True)
    pending = await request(app)
    with pytest.raises(PermissionError, match="active_admin_required"):
        await app.decide(
            replace(approve(pending["request_id"]), actor_id=CLIENT),
            principal=CLIENT_PROOF,
            session=object(),
        )

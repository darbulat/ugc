"""Read hints preserve scope, raw presence and selected allocation semantics."""

import importlib
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)
ACTOR, ITEM, OBLIGATION = uuid4(), uuid4(), UUID(int=1)


def modules():
    try:
        return (
            importlib.import_module("ugc_bot.application.payout_view_ports"),
            importlib.import_module(
                "ugc_bot.application.services.payout_view_service"
            ),
        )
    except ModuleNotFoundError:
        pytest.fail("dedicated payout read contracts/service are missing")


class Reader:
    def __init__(self, facts):
        self.facts = facts
        self.calls = []

    async def actor(self, principal):
        self.calls.append(("actor", principal))
        return self.facts["actor"]

    async def financial(self, recipient_id):
        return self.facts["financial"]

    async def command_blockers(self, kind):
        return self.facts.get("command_errors", {}).get(kind, ())

    async def requirements(self, at):
        return self.facts["requirements"]

    async def requisites(self, recipient_id, page, cursor):
        return tuple(self.facts.get("requisites", ()))[: page.limit + 1]

    async def requisite(self, recipient_id, requisites_id):
        return next(
            (
                r
                for r in self.facts.get("requisites", ())
                if r.row["requisites_id"] == requisites_id
            ),
            None,
        )

    async def item_blockers(self, item_ids):
        self.calls.append(("items", tuple(item_ids)))
        return tuple(
            self.facts.get("item_errors", {}).get(i, "")
            for i in item_ids
            if self.facts.get("item_errors", {}).get(i)
        )

    async def request(self, request_id, recipient_id):
        value = self.facts.get("request")
        return (
            value
            if value
            and value.row["request_id"] == request_id
            and (
                recipient_id is None
                or value.row["recipient_id"] == recipient_id
            )
            else None
        )

    async def requests(self, recipient_id, page, cursor, *, queue):
        return tuple(self.facts.get("requests", ()))[: page.limit + 1]

    async def history(self, request_id, kind, page, cursor):
        return tuple(self.facts.get("history", ()))[: page.limit + 1]

    async def requirements_page(self, page, cursor):
        return tuple(self.facts.get("requirement_rows", ()))[: page.limit + 1]


class Repository:
    def __init__(self, facts):
        self.reader = Reader(facts)
        self.snapshots = 0

    @asynccontextmanager
    async def snapshot(self):
        self.snapshots += 1
        yield self.reader


def setup(*, admin=False):
    p, s = modules()
    from ugc_bot.application.financial_ports import (
        JournalMovement,
        ObligationBasis,
    )
    from ugc_bot.application.services.financial_reconciliation_service import (
        BUCKETS,
    )

    moves = tuple(
        JournalMovement(
            obligation_id=OBLIGATION,
            operation_key=str(i),
            event_id="synthetic",
            movement_type="issuance" if i == 0 else "transfer",
            amount_minor=100,
            currency="RUB",
            effective_at=NOW,
            recorded_at=NOW,
            actor_id=ACTOR,
            reason="Synthetic pure read basis",
            bucket_from="pending" if i == 1 else "hold" if i == 2 else None,
            bucket_to="hold"
            if i == 1
            else "available"
            if i == 2
            else "pending",
        )
        for i in range(3)
    )
    wallet = dict.fromkeys(BUCKETS, 0) | {"available": 100}
    facts = dict(
        actor=p.ReadActor(ACTOR, "telegram", "123", "active", admin),
        financial=p.FinancialRead(
            (
                p.ReadObligation(
                    ObligationBasis(OBLIGATION, ACTOR, "RUB", 100), ITEM
                ),
            ),
            moves,
            wallet,
            (),
            (),
            "active",
        ),
        requirements=p.RequirementsRead(None, None, ()),
    )
    repo = Repository(facts)
    service = s.PayoutViewService(
        repo,
        SimpleNamespace(now=lambda: NOW),
        SimpleNamespace(
            core_enabled=True,
            payouts_enabled=True,
            manual_bank_account_id="synthetic-origin",
            manual_bank_source_id="synthetic-bank-source",
        ),
        None,
    )
    principal = p.PayoutReadPrincipal(ACTOR, "telegram", "123")
    return p, s, service, repo, principal


@pytest.mark.asyncio
async def test_context_distinguishes_display_from_unspecified_reserve():
    _, _, service, repo, principal = setup()
    result = await service.context(principal)
    assert result["financial"]["state"] == "ready"
    assert result["financial"]["balances"]["available_minor"] == "100"
    assert "reserve" not in result["capabilities"]
    assert result["capabilities"]["read_own_requests"]
    assert not result["capabilities"]["begin_request"]
    assert repo.snapshots == 1 and repo.reader.calls[0][0] == "actor"
    assert not [c for c in repo.reader.calls if c[0] == "items"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "missing_wallet",
        "partial_source",
        "bad_projection",
        "missing_issue",
        "old_bank_history",
    ],
)
async def test_incomplete_money_never_becomes_spendable_zero(case):
    _, _, service, repo, principal = setup()
    old = repo.reader.facts["financial"]
    change = {
        "missing_wallet": dict(wallet=None),
        "partial_source": dict(source_blockers=("payout_source_unavailable",)),
        "bad_projection": dict(wallet=old.wallet | {"available": 99}),
        "missing_issue": dict(movements=old.movements[1:]),
        "old_bank_history": dict(
            readiness_blockers=("payout_history_authority_review_required",)
        ),
    }[case]
    repo.reader.facts["financial"] = replace(old, **change)
    result = await service.context(principal)
    assert not result["capabilities"]["begin_request"]
    if case != "old_bank_history":
        assert (
            result["financial"]["state"] == "unavailable"
            and result["financial"]["balances"] is None
        )
    else:
        assert result["financial"]["balances"]["available_minor"] == "100"
        assert (
            "payout_history_authority_review_required"
            in result["recipient_blockers"]
        )


@pytest.mark.asyncio
async def test_known_empty_requires_complete_sources_and_no_history():
    p, _, service, repo, principal = setup()
    repo.reader.facts["financial"] = p.FinancialRead(
        (), (), None, (), (), "active"
    )
    result = await service.context(principal)
    assert result["financial"]["state"] == "known_empty"
    assert result["financial"]["balances"]["available_minor"] == "0"
    assert not result["capabilities"]["begin_request"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        dict(actor_id=uuid4()),
        dict(external_id="different"),
        dict(platform="max"),
        dict(status="blocked"),
    ],
)
async def test_snapshot_revalidates_exact_native_mapping_and_current_status(
    change,
):
    _, _, service, repo, principal = setup()
    repo.reader.facts["actor"] = replace(repo.reader.facts["actor"], **change)
    with pytest.raises(PermissionError):
        await service.context(principal)


def readable(repo):
    p, _ = modules()
    requirement_id, document_id, requisites_id = uuid4(), uuid4(), uuid4()
    current = dict(
        requirements_id=requirement_id,
        version=1,
        effective_from=NOW,
        terms_reference="synthetic",
        required_fields=["recipient_name", "bank_account", "legal_status"],
        enabled=True,
        readable=True,
        document=dict(
            document_id=document_id,
            sha256="a" * 64,
            content_text="Synthetic actual source",
            source_locale="en",
        ),
        field_definitions=[],
    )
    repo.reader.facts["requirements"] = p.RequirementsRead(current, current, ())
    sealed = dict(
        requisites_id=requisites_id,
        recipient_id=ACTOR,
        requirements_id=requirement_id,
        requirements_version=1,
        recorded_at=NOW,
        masked_label="••••1234",
    )
    repo.reader.facts["requisites"] = (
        p.RequisiteRead(sealed, {"document": current["document"]}, True),
    )
    return requisites_id


@pytest.mark.asyncio
async def test_preview_uses_exact_prefix_and_only_selected_item_guards():
    p, _, service, repo, principal = setup()
    requisite = readable(repo)
    service.crypto = SimpleNamespace(
        open=lambda *args: {"private": "must-not-escape"}
    )
    old = repo.reader.facts["financial"]
    second_id, second_item = UUID(int=2), uuid4()
    second = replace(
        old.obligations[0],
        basis=replace(old.obligations[0].basis, obligation_id=second_id),
        paid_item_id=second_item,
    )
    moves = old.movements + tuple(
        replace(
            m,
            obligation_id=second_id,
            operation_key="second:" + m.operation_key,
        )
        for m in old.movements
    )
    repo.reader.facts["financial"] = replace(
        old,
        obligations=old.obligations + (second,),
        movements=moves,
        wallet=old.wallet | {"available": 200},
    )
    repo.reader.facts["item_errors"] = {second_item: "work_disputed"}
    clear = await service.reserve_preview(principal, requisite, 50)
    assert clear["can_reserve"] and clear["amount_minor"] == "50"
    assert repo.reader.calls[-1] == ("items", (ITEM,))
    affected = await service.reserve_preview(principal, requisite, 150)
    assert (
        not affected["can_reserve"] and "work_disputed" in affected["blockers"]
    )
    assert str(second_item) not in str(affected)
    repo.reader.facts["item_errors"] = {ITEM: "work_disputed"}
    blocked = await service.reserve_preview(principal, requisite, 50)
    assert not blocked["can_reserve"]


@pytest.mark.asyncio
async def test_masked_context_is_bounded_and_cursor_is_actor_route_bound():
    p, _, service, repo, principal = setup()
    readable(repo)
    service.crypto = SimpleNamespace(open=lambda *args: {"private": "discard"})
    base = repo.reader.facts["requisites"][0]
    repo.reader.facts["requisites"] = tuple(
        replace(base, row=base.row | {"requisites_id": UUID(int=i + 100)})
        for i in range(4)
    )
    first = await service.context(principal, page=p.Page(limit=2))
    assert (
        len(first["masked_requisites"]["entries"]) == 2
        and first["masked_requisites"]["has_more"]
    )
    token = first["masked_requisites"]["next_cursor"]
    assert p.cursor_decode(token, principal, "masked").identity == UUID(int=101)
    foreign = p.cursor_encode(
        p.Cursor(NOW, UUID(int=101)),
        replace(principal, actor_id=uuid4()),
        "masked",
    )
    with pytest.raises(ValueError, match="payout_cursor_invalid"):
        await service.context(principal, page=p.Page(limit=2, cursor=foreign))


def request_facts(repo, state="approved", *, broken=False, retained=True):
    p, _ = modules()
    requisite = readable(repo)
    request_id, execution_id = uuid4(), uuid4()
    row = dict(
        request_id=request_id,
        recipient_id=ACTOR,
        requisites_id=requisite,
        requirements_id=repo.reader.facts["requirements"].current[
            "requirements_id"
        ],
        amount_minor=100,
        currency="RUB",
        requested_at=NOW - timedelta(hours=72),
        deadline_at=NOW,
    )
    authority = dict(
        request_id=request_id,
        version=3,
        state=state,
        execution_id=execution_id
        if state in ("executing", "unknown", "paid")
        else None,
        block_reason="",
    )
    intent = dict(
        execution_id=execution_id,
        request_id=request_id,
        fence=uuid4(),
        bank_account="protected-origin",
        prepared_at=NOW - timedelta(hours=1),
        amount_minor=100,
        currency="RUB",
        version=2,
        version_provenance="retained_event",
    )
    fact = p.RequestRead(
        row,
        authority,
        not broken,
        repo.reader.facts["requisites"][0],
        (p.ReadAllocation(OBLIGATION, ITEM, 100),),
        intent if authority["execution_id"] else None,
        (intent,) if retained else (),
        False,
        False,
        (),
        retained,
    )
    repo.reader.facts["request"] = fact
    return fact


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state,allowed",
    [
        ("reserved", {"review", "reject", "escalate"}),
        ("approved", {"review", "reject", "start", "escalate"}),
        ("blocked", {"review", "reject", "escalate"}),
        ("executing", {"escalate"}),
        ("unknown", {"escalate"}),
        ("paid", set()),
        ("rejected", set()),
    ],
)
async def test_action_matrix_uses_proven_state_and_original_deadline(
    state, allowed
):
    _, _, service, repo, principal = setup(admin=True)
    fact = request_facts(repo, state)
    service.crypto = SimpleNamespace(open=lambda *args: {"private": "discard"})
    result = await service.detail(principal, fact.row["request_id"])
    assert set(result["allowed_actions"]) == allowed | {
        "reveal_requisites",
        "record_observation",
    }
    assert result["overdue"] and result["version"] == 3
    assert result["amount_minor"] == "100"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "paused",
        "no_key",
        "no_origin",
        "broken",
        "debt",
        "changed_terms",
        "escalated",
    ],
)
async def test_separate_observation_and_release_prerequisites(case):
    _, _, service, repo, principal = setup(admin=True)
    fact = request_facts(repo)
    service.crypto = SimpleNamespace(open=lambda *args: {"private": "discard"})
    if case == "paused":
        service.config.payouts_enabled = False
    if case == "no_key":
        service.crypto = None
    if case == "no_origin":
        service.config.manual_bank_account_id = ""
    if case == "broken":
        repo.reader.facts["request"] = replace(fact, consistent=False)
    if case == "debt":
        f = repo.reader.facts["financial"]
        repo.reader.facts["financial"] = replace(
            f, readiness_blockers=("payout_debt_manual_review_required",)
        )
    if case == "changed_terms":
        f = repo.reader.facts["requirements"]
        repo.reader.facts["requirements"] = replace(
            f, current=f.current | {"requirements_id": uuid4()}
        )
    if case == "escalated":
        repo.reader.facts["request"] = replace(fact, escalated=True)
    result = await service.detail(principal, fact.row["request_id"])
    actions = set(result["allowed_actions"])
    assert "record_observation" in actions
    if case in ("paused", "broken"):
        assert not actions & {"review", "reject", "start", "escalate"}
    if case in ("debt", "changed_terms"):
        assert "reject" in actions and not actions & {"review", "start"}
    if case in ("no_key", "no_origin"):
        assert {"review", "reject"} <= actions and "start" not in actions
    if case == "escalated":
        assert "escalate" not in actions
    if case == "broken":
        assert result["state"] == "unavailable" and result["version"] is None
        assert result["current_execution"] is None
        assert (
            result["observation"]["retained_intents"]["entries"][0][
                "version_provenance"
            ]
            == "retained_event"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [None, 123, "", "   ", "x" * 257])
async def test_invalid_source_denies_only_start_readiness(source):
    _, _, service, repo, principal = setup(admin=True)
    fact = request_facts(repo)
    service.crypto = SimpleNamespace(open=lambda *args: {})
    service.config.manual_bank_source_id = source
    result = await service.detail(principal, fact.row["request_id"])
    assert {"review", "reject", "record_observation"} <= set(
        result["allowed_actions"]
    )
    assert "start" not in result["allowed_actions"]
    assert result["action_blockers"]["start"] == [
        "payout_bank_source_configuration_required"
    ]


@pytest.mark.asyncio
async def test_owner_detail_never_contains_admin_execution_or_evidence():
    _, _, service, repo, principal = setup()
    fact = request_facts(repo, "executing")
    result = await service.detail(principal, fact.row["request_id"])
    assert result["allowed_actions"] == []
    assert all(
        v not in str(result)
        for v in (
            "protected-origin",
            "fence",
            "observation",
            "current_execution",
            "fingerprint",
            "ciphertext",
        )
    )


@pytest.mark.asyncio
async def test_balanced_debt_blocks_context_and_preview_without_forfeiting():
    _, _, service, repo, principal = setup()
    requisite = readable(repo)
    service.crypto = SimpleNamespace(open=lambda *args: {})
    f = repo.reader.facts["financial"]
    oid, item = UUID(int=2), uuid4()
    second = replace(
        f.obligations[0],
        basis=replace(f.obligations[0].basis, obligation_id=oid),
        paid_item_id=item,
    )
    extra = tuple(
        replace(m, obligation_id=oid, operation_key="extra:" + m.operation_key)
        for m in f.movements
    )
    request, allocation, execution, case = uuid4(), uuid4(), uuid4(), uuid4()
    reserved = replace(
        f.movements[-1],
        operation_key="reserved",
        bucket_from="available",
        bucket_to="reserved",
        request_id=request,
        allocation_id=allocation,
    )
    paid = replace(
        reserved,
        operation_key="paid",
        bucket_from="reserved",
        bucket_to="paid",
        execution_id=execution,
    )
    debt = replace(
        paid,
        operation_key="debt",
        movement_type="debt",
        amount_minor=30,
        bucket_from=None,
        bucket_to=None,
        request_id=None,
        allocation_id=None,
        execution_id=None,
        case_id=case,
        source_entry_id=uuid4(),
    )
    repo.reader.facts["financial"] = replace(
        f,
        obligations=f.obligations + (second,),
        movements=f.movements + extra + (reserved, paid, debt),
        wallet=f.wallet
        | {"available": 100, "paid": 100, "debt": 30, "cancelled": 30},
    )
    context = await service.context(principal)
    preview = await service.reserve_preview(principal, requisite, 50)
    assert context["financial"]["state"] == "ready"
    assert context["financial"]["balances"]["debt_minor"] == "30"
    assert not context["capabilities"]["begin_request"]
    assert (
        not preview["can_reserve"]
        and "payout_debt_manual_review_required" in preview["blockers"]
    )
    repo.reader.facts["actor"] = replace(repo.reader.facts["actor"], admin=True)
    fact = request_facts(repo)
    detail = await service.detail(principal, fact.row["request_id"])
    assert (
        "payout_debt_manual_review_required"
        in detail["action_blockers"]["review"]
    )
    assert "reject" in detail["allowed_actions"]
    assert "escalate" in detail["allowed_actions"]


@pytest.mark.asyncio
async def test_nested_public_document_and_history_are_explicit_allowlists():
    p, _, service, repo, principal = setup(admin=True)
    fact = request_facts(repo)
    f = repo.reader.facts["requirements"]
    repo.reader.facts["requirements"] = replace(
        f,
        current=f.current
        | {
            "document": f.current["document"]
            | {"fingerprint": "SYNTHETIC_PRIVATE_FINGERPRINT"},
            "field_definitions": [
                {
                    "key": "name",
                    "labels": {"en": "Name"},
                    "help": {},
                    "allowed_values": None,
                    "private": "SYNTHETIC_PRIVATE_FIELD",
                }
            ],
        },
    )
    result = await service.context(principal)
    assert "SYNTHETIC_PRIVATE" not in str(result)
    repo.reader.facts["history"] = (
        dict(
            event_id=uuid4(),
            request_id=fact.row["request_id"],
            version=3,
            action="review",
            state="approved",
            actor_id=ACTOR,
            reason="Synthetic operator reason",
            recorded_at=NOW,
            details={
                "projection": dict(
                    request_id=str(fact.row["request_id"]),
                    version=3,
                    state="approved",
                    execution_id=None,
                    block_reason="",
                ),
                "evidence_reference": "synthetic:actual-review",
                "private": "SYNTHETIC_PRIVATE_EVENT",
            },
        ),
    )
    history = await service.history_page(
        principal, fact.row["request_id"], "events"
    )
    assert (
        history["entries"][0]["evidence_reference"] == "synthetic:actual-review"
    )
    assert history["entries"][0]["resulting_state"]["version"] == 3
    assert "SYNTHETIC_PRIVATE_EVENT" not in str(history)


@pytest.mark.asyncio
async def test_observation_requires_sources_and_uses_a_real_version():
    _, _, service, repo, principal = setup(admin=True)
    fact = request_facts(repo, "executing", broken=True)
    service.config.payouts_enabled = False
    repo.reader.facts["request"] = replace(
        fact,
        observation_ready=False,
        observation_blockers=("payout_observation_source_unavailable",),
    )
    result = await service.detail(principal, fact.row["request_id"])
    assert "record_observation" not in result["allowed_actions"]
    assert result["action_blockers"]["record_observation"] == [
        "payout_observation_source_unavailable"
    ]
    repo.reader.facts["request"] = replace(
        fact,
        retained_intents=tuple(
            dict(v)
            | {
                "version": None,
                "version_provenance": "retained_version_required",
            }
            for v in fact.retained_intents
        ),
    )
    result = await service.detail(principal, fact.row["request_id"])
    retained = result["observation"]["retained_intents"]["entries"][0]
    assert "record_observation" in result["allowed_actions"]
    assert (
        retained["expected_version"] is None
        and retained["version_provenance"] == "retained_version_required"
    )


@pytest.mark.asyncio
async def test_bounded_pages_reauthorize_and_hide_private_executions():
    p, _, service, repo, principal = setup(admin=True)
    base = request_facts(repo, "executing")
    repo.reader.facts["requests"] = tuple(
        replace(base, row=base.row | {"request_id": UUID(int=i + 100)})
        for i in range(4)
    )
    own = await service.own_page(principal, page=p.Page(limit=2))
    assert len(own["entries"]) == 2 and own["has_more"]
    assert "fence" not in str(own) and "protected-origin" not in str(own)
    queue = await service.queue_page(principal, page=p.Page(limit=2))
    assert queue["has_more"] and len(queue["entries"]) == 2
    repo.reader.facts["actor"] = replace(
        repo.reader.facts["actor"], admin=False
    )
    with pytest.raises(PermissionError):
        await service.queue_page(
            principal, page=p.Page(limit=2, cursor=queue["next_cursor"])
        )
    with pytest.raises(PermissionError):
        await service.requirements_page(principal)
    with pytest.raises(PermissionError):
        await service.history_page(principal, base.row["request_id"], "intents")


def test_cursors_are_strict_navigation_scoped_to_actor_route_and_request():
    p, _, _, _, principal = setup()
    scope = uuid4()
    token = p.cursor_encode(
        p.Cursor(NOW, UUID(int=100)), principal, "history:intents", scope
    )
    assert (
        p.cursor_decode(token, principal, "history:intents", scope).position
        == NOW
    )
    for actor, route, request in (
        (replace(principal, actor_id=uuid4()), "history:intents", scope),
        (principal, "history:outcomes", scope),
        (principal, "history:intents", uuid4()),
    ):
        with pytest.raises(ValueError, match="payout_cursor_invalid"):
            p.cursor_decode(token, actor, route, request)
    for value in (
        "not-json",
        "***",
        "e30",
        p.cursor_encode(
            p.Cursor(0, UUID(int=100)), principal, "history:events", scope
        ),
    ):
        with pytest.raises(ValueError, match="payout_cursor_invalid"):
            p.cursor_decode(value, principal, "history:events", scope)
    for limit in (0, 101, True, 1.5):
        with pytest.raises(ValueError):
            p.Page(limit=limit)


def test_cursor_duplicate_keys_are_not_ambiguous_navigation():
    import base64

    _, _, _, _, principal = setup()
    p, _ = modules()
    raw = (
        f'{{"v":1,"actor":"{principal.actor_id}",'
        '"route":"own","scope":null,"position":['
        '"2026-10-24T00:00:00+00:00",'
        '"00000000-0000-0000-0000-000000000001"],"v":1}'
    )
    token = base64.urlsafe_b64encode(raw.encode()).decode()
    with pytest.raises(ValueError, match="payout_cursor_invalid"):
        p.cursor_decode(token, principal, "own")


@pytest.mark.parametrize(
    "position", ["9999-12-31T23:59:59-23:59", "0001-01-01T00:00:00+23:59"]
)
def test_cursor_utc_overflow_is_stable_invalid_navigation(position):
    import base64
    import json

    p, _, _, _, principal = setup()
    token = base64.urlsafe_b64encode(
        json.dumps(
            dict(
                v=1,
                actor=str(principal.actor_id),
                route="own",
                scope=None,
                position=[position, "00000000-0000-0000-0000-000000000001"],
            )
        ).encode()
    ).decode()
    with pytest.raises(ValueError, match="payout_cursor_invalid"):
        p.cursor_decode(token, principal, "own")


@pytest.mark.asyncio
async def test_missing_resource_or_requirements_cannot_invent_actions():
    p, _, service, repo, principal = setup(admin=True)
    with pytest.raises(p.PayoutReadNotFound):
        await service.detail(principal, uuid4())
    with pytest.raises(p.PayoutReadNotFound):
        await service.history_page(principal, uuid4(), "events")
    with pytest.raises(ValueError, match="payout_cursor_invalid"):
        await service.history_page(principal, uuid4(), "invented")
    fact = request_facts(repo)
    repo.reader.facts["requirements"] = p.RequirementsRead(None, None, ())
    detail = await service.detail(principal, fact.row["request_id"])
    assert (
        "published_payout_requirements_required"
        in detail["action_blockers"]["review"]
    )
    assert "reject" in detail["allowed_actions"]
    preview = await service.reserve_preview(principal, uuid4(), 1)
    assert (
        not preview["can_reserve"]
        and "payout_requisites_unavailable" in preview["blockers"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "amount,currency", [(0, "RUB"), (-1, "RUB"), (True, "RUB"), (1, "USD")]
)
async def test_preview_rejects_invalid_domain_amount_before_snapshot(
    amount, currency
):
    _, _, service, repo, principal = setup()
    with pytest.raises(ValueError, match="payout_amount_invalid"):
        await service.reserve_preview(
            principal, uuid4(), amount, currency=currency
        )
    assert repo.snapshots == 0


@pytest.mark.asyncio
async def test_malformed_stored_mask_is_unavailable_and_never_echoed():
    _, _, service, repo, principal = setup()
    readable(repo)
    service.crypto = SimpleNamespace(open=lambda *args: {"private": "discard"})
    old = repo.reader.facts["requisites"][0]
    repo.reader.facts["requisites"] = (
        replace(
            old, row=old.row | {"masked_label": "SYNTHETIC_PRIVATE_UNMASKED"}
        ),
    )
    context = await service.context(principal)
    row = context["masked_requisites"]["entries"][0]
    assert row["masked_label"] is None and not row["usable"]
    assert row["unusable_reasons"] == ["payout_source_integrity_required"]
    assert "SYNTHETIC_PRIVATE_UNMASKED" not in str(context)


def test_nil_actor_and_cursor_identity_are_rejected():
    p, _, _, _, principal = setup()
    with pytest.raises(ValueError, match="payout_read_identity_invalid"):
        p.PayoutReadPrincipal(UUID(int=0), "telegram", "123")
    token = p.cursor_encode(p.Cursor(NOW, UUID(int=0)), principal, "own")
    with pytest.raises(ValueError, match="payout_cursor_invalid"):
        p.cursor_decode(token, principal, "own")

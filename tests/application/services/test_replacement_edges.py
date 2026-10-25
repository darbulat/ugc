"""Current proof, complete scope and original financial grounds are required."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest

from tests.application.services.test_replacement_service import (
    ADMIN,
    ADMIN_PROOF,
    CLIENT,
    CLIENT_PROOF,
    INTEREST,
    ITEM,
    NOW,
    OLD,
    approve,
    request,
    setup,
)
from ugc_bot.application.replacement_ports import (
    ReplacementContact,
    ReplacementRequest,
)


@pytest.mark.asyncio
async def test_context_queue_contact_and_replay_use_current_authority():
    repo, _, app = setup()
    view = await app.view(
        CLIENT, ITEM, principal=CLIENT_PROOF, session=object()
    )
    assert view["capabilities"] == {"request": True, "review": False}
    assert (await app.queue(ADMIN, principal=ADMIN_PROOF, session=object()))[
        "entries"
    ] == []
    pending = await request(app)
    result = await app.decide(
        approve(pending["request_id"]), principal=ADMIN_PROOF, session=object()
    )
    command = ReplacementContact(
        "contact",
        CLIENT,
        UUID(result["replacement_id"]),
        "Получить контакт",
        "miniapp:explicit",
    )
    contact = await app.contact(
        command, principal=CLIENT_PROOF, session=object()
    )
    assert (
        await app.contact(command, principal=CLIENT_PROOF, session=object())
        == contact
    )
    assert len(repo.contacts) == 1 and contact["billable_positions_added"] == 0
    repo.scope = replace(repo.scope, assignment_id=UUID(int=999))
    assert (
        await app.contact(command, principal=CLIENT_PROOF, session=object())
        == contact
    )
    with pytest.raises(ValueError, match="replacement_assignment_obsolete"):
        await app.contact(
            replace(command, operation_key="fresh-disclosure"),
            principal=CLIENT_PROOF,
            session=object(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        dict(used=True),
        dict(order_id=UUID(int=999)),
        dict(payment_id=UUID(int=999)),
        dict(capture_event_id=UUID(int=999)),
        dict(policy_version="foreign"),
        dict(creator_id=CLIENT),
        dict(creator_id=OLD),
        dict(confirmed_at=NOW.replace(year=2025)),
        dict(confirmed_at=NOW.replace(year=2027)),
    ],
)
async def test_requires_same_capture_confirmed_reserve_interest(change):
    repo, _, app = setup()
    repo.candidate_row = replace(repo.candidate_row, **change)
    with pytest.raises(
        ValueError, match="replacement_confirmed_reserve_required"
    ):
        await request(app)
    assert repo.requests == {}


@pytest.mark.asyncio
async def test_absent_candidate_and_old_native_proof_fail_closed():
    repo, _, app = setup()
    command = ReplacementRequest(
        "request",
        CLIENT,
        ITEM,
        1,
        UUID(int=999),
        "refusal",
        "Отказ",
        "support:1",
    )
    with pytest.raises(
        ValueError, match="replacement_confirmed_reserve_required"
    ):
        await app.request(command, principal=CLIENT_PROOF, session=object())
    repo.actor[CLIENT].telegram_id = "new-native-owner"
    with pytest.raises(ValueError, match="financial_principal_changed"):
        await request(app)


@pytest.mark.asyncio
async def test_disabled_writes_preserve_read_context():
    repo, _, app = setup()
    app.enabled = False
    with pytest.raises(ValueError, match="financial_core_paused"):
        await request(app)
    assert repo.requests == {}
    assert (
        await app.view(CLIENT, ITEM, principal=CLIENT_PROOF, session=object())
    )["writes_paused"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,error",
    [
        (dict(selection_state="refunded"), "replacement_position_unavailable"),
        (dict(order_active=False), "replacement_position_unavailable"),
        (
            dict(assignment_from=NOW.replace(year=2027)),
            "replacement_fact_in_future",
        ),
    ],
)
async def test_unavailable_or_future_positions_refused(change, error):
    repo, _, app = setup()
    repo.scope = replace(repo.scope, **change)
    with pytest.raises(ValueError, match=error):
        await request(app)


@pytest.mark.asyncio
async def test_current_role_required_for_reads_and_admin_queue():
    repo, _, app = setup()
    repo.actor[CLIENT].is_client = False
    with pytest.raises(PermissionError, match="replacement_forbidden"):
        await app.view(CLIENT, ITEM, principal=CLIENT_PROOF, session=object())
    with pytest.raises(PermissionError, match="active_admin_required"):
        await app.queue(CLIENT, principal=CLIENT_PROOF, session=object())
    with pytest.raises(ValueError, match="replacement_queue_invalid"):
        await app.queue(
            ADMIN, page=True, principal=ADMIN_PROOF, session=object()
        )


@pytest.mark.asyncio
async def test_duplicate_request_is_exact_and_changed_payload_conflicts():
    repo, _, app = setup()
    first = await request(app)
    assert await request(app) == first
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        await app.request(
            ReplacementRequest(
                "request-1",
                CLIENT,
                ITEM,
                1,
                INTEREST,
                "refusal",
                "Другая причина",
                "support:1",
            ),
            principal=CLIENT_PROOF,
            session=object(),
        )
    assert len(repo.requests) == 1


@pytest.mark.asyncio
async def test_rejection_is_terminal_without_assignment_or_compensation():
    repo, _, app = setup()
    pending = await request(app)
    command = replace(approve(pending["request_id"]), action="reject")
    result = await app.decide(command, principal=ADMIN_PROOF, session=object())
    assert result["state"] == "rejected" and repo.calls == ["authority"]
    with pytest.raises(
        ValueError, match="replacement_request_already_reviewed"
    ):
        await app.decide(
            replace(command, operation_key="different"),
            principal=ADMIN_PROOF,
            session=object(),
        )


@pytest.mark.asyncio
async def test_missing_changed_or_corrupt_source_cannot_be_reviewed():
    repo, _, app = setup()
    with pytest.raises(ValueError, match="replacement_request_not_found"):
        await app.decide(
            approve(str(UUID(int=888))), principal=ADMIN_PROOF, session=object()
        )
    pending = await request(app)
    row = repo.requests[UUID(pending["request_id"])]
    row["version"] = 2
    with pytest.raises(
        ValueError, match="replacement_request_version_conflict"
    ):
        await app.decide(
            approve(pending["request_id"]),
            principal=ADMIN_PROOF,
            session=object(),
        )
    row["version"], row["capture_hash"] = 1, "foreign"
    with pytest.raises(ValueError, match="replacement_source_changed"):
        await app.decide(
            approve(pending["request_id"]),
            principal=ADMIN_PROOF,
            session=object(),
        )
    assert repo.calls == []


@pytest.mark.asyncio
async def test_review_time_and_manager_membership_are_current():
    repo, _, app = setup()
    pending = await request(app)
    repo.requests[UUID(pending["request_id"])]["requested_at"] = NOW.replace(
        year=2027
    )
    with pytest.raises(ValueError, match="replacement_fact_in_future"):
        await app.decide(
            approve(pending["request_id"]),
            principal=ADMIN_PROOF,
            session=object(),
        )
    repo.requests[UUID(pending["request_id"])]["requested_at"] = NOW
    with pytest.raises(ValueError, match="replacement_active_manager_required"):
        await app.decide(
            approve(pending["request_id"], manager_id=ADMIN),
            principal=ADMIN_PROOF,
            session=object(),
        )
    repo.scope = replace(
        repo.scope, manager_id=ADMIN, manager_ids=(ADMIN,), accompaniment=True
    )
    await app.decide(
        approve(pending["request_id"]), principal=ADMIN_PROOF, session=object()
    )


@pytest.mark.asyncio
async def test_changed_scope_without_receipt_requires_whole_transaction_retry():
    repo, _, app = setup()

    async def mutate(source, *, session):
        repo.scope = replace(source, replacement_count=1)

    repo.lock_scope = mutate
    with pytest.raises(
        ValueError, match="financial_scope_changed_retry_required"
    ):
        await request(app)
    assert repo.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bucket", ["reserved", "paid", "debt"])
async def test_reserved_and_paid_grounds_cannot_assign_or_offset(bucket):
    repo, ledger, app = setup()
    ledger.grounds = [
        SimpleNamespace(
            kind="creator_referral",
            business_key="old",
            recipient_id=CLIENT,
            currency="RUB",
            obligation_id=UUID(int=300),
        )
    ]

    async def journal(*args, **kwargs):
        return (
            SimpleNamespace(
                obligation_id=UUID(int=300),
                amount_minor=5000,
                movement_type="debt" if bucket == "debt" else "transfer",
                bucket_from="available",
                bucket_to=bucket if bucket != "debt" else None,
            ),
        )

    ledger.list_for_recipient = journal
    pending = await request(app)
    with pytest.raises(ValueError, match="reserved|paid_ground"):
        await app.decide(
            approve(pending["request_id"]),
            principal=ADMIN_PROOF,
            session=object(),
        )
    assert "assignment" not in repo.calls and "cancel" not in repo.calls


@pytest.mark.asyncio
async def test_missing_original_and_unavailable_contact_need_review():
    repo, ledger, app = setup()
    ledger.grounds = [
        SimpleNamespace(
            kind="creator_referral",
            business_key="old",
            recipient_id=CLIENT,
            currency="RUB",
            obligation_id=UUID(int=300),
        )
    ]

    async def absent(*args, **kwargs):
        return None

    ledger.get_issue = absent
    pending = await request(app)
    with pytest.raises(
        ValueError, match="replacement_original_ground_mismatch"
    ):
        await app.decide(
            approve(pending["request_id"]),
            principal=ADMIN_PROOF,
            session=object(),
        )
    command = ReplacementContact(
        "contact", CLIENT, UUID(int=500), "Контакт", "miniapp:explicit"
    )
    with pytest.raises(ValueError, match="replacement_allocation_not_found"):
        await app.contact(command, principal=CLIENT_PROOF, session=object())
    ledger.grounds = []
    # A real caller transaction rolls back the earlier refused authority.
    repo.decisions.clear()
    result = await app.decide(
        approve(pending["request_id"]), principal=ADMIN_PROOF, session=object()
    )
    repo.candidate_row = replace(repo.candidate_row, verified=False)
    with pytest.raises(ValueError, match="replacement_contact_unavailable"):
        await app.contact(
            replace(command, replacement_id=UUID(result["replacement_id"])),
            principal=CLIENT_PROOF,
            session=object(),
        )

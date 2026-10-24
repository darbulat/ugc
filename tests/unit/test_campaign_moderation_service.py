"""Synthetic exact-review cases; actual SQL ordering remains pending."""

from dataclasses import replace
from uuid import UUID

import pytest

from tests.unit.test_campaign_submission_service import (
    ADMIN,
    OWNER,
    SESSION,
    add_member,
    command,
    environment,
    submitted,
)
from ugc_bot.domain.campaign_moderation import CancelCampaign, ReviewCampaign


async def reviewing():
    from ugc_bot.application.services.campaign_moderation_service import (
        CampaignModerationService,
    )

    repository, _, capacity, result = await submitted()
    service = CampaignModerationService(repository, capacity, capacity.clock)
    detail = await service.review_detail(
        ADMIN, UUID(result["submission_id"]), session=SESSION
    )
    intent = ReviewCampaign(
        ADMIN,
        "approve",
        command().campaign_id,
        UUID(result["submission_id"]),
        result["version"],
        command().revision_digest,
        detail["review_context"],
        "approve",
        "Synthetic review",
    )
    return repository, service, detail, intent


@pytest.mark.asyncio
async def test_approval_retains_context_subset_envelope_and_waiting_jobs():
    repository, service, detail, intent = await reviewing()
    result = await service.decide(intent, session=SESSION)
    assert result["state"] == "approved_waiting" and len(repository.jobs) == 1
    job = next(iter(repository.jobs.values()))
    assert (
        job.envelope_digest
        == next(iter(repository.submissions.values())).seal.envelope.digest
    )
    assert result["delivery_state"] == "waiting_delivery_implementation"
    assert len(repository.decisions) == len(repository.facts.reservations) == 1
    assert (await service.decide(intent, session=SESSION))[
        "review_id"
    ] == result["review_id"]
    assert len(repository.writes) == 2
    assert detail["surviving_count"] == 1 and "101" not in str(detail)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    ["consent", "identity", "contact", "grant", "policy", "capacity", "admin"],
)
async def test_review_drift_or_lost_authority_aborts_effects(
    changed,
):
    from ugc_bot.application.campaign_moderation_ports import (
        CampaignCandidateFacts,
    )
    from ugc_bot.domain.campaign_capacity import CampaignUsage

    repository, service, _, intent = await reviewing()
    if changed in ("consent", "identity", "contact"):
        member = repository.members[0].member
        if changed == "consent":
            member["consent"]["version"] = 2
        elif changed == "identity":
            member["context"]["canonical_identity"] = "other-ig"
        else:
            member["context"]["actor"]["telegram_id"] = "202"
        repository.members[0] = CampaignCandidateFacts.from_member(member)
    elif changed == "grant":
        repository.grant = replace(repository.grant, version=5)
    elif changed == "policy":
        repository.policy = replace(
            repository.policy, stream_version=3, publication_version=3
        )
    elif changed == "capacity":
        repository.facts = replace(
            repository.facts,
            usage=(
                CampaignUsage(
                    UUID(int=900), "submission", OWNER, repository.at
                ),
            ),
        )
    else:
        repository.admins.clear()
    with pytest.raises((ValueError, PermissionError)):
        await service.decide(intent, session=SESSION)
    assert (
        len(repository.writes) == 1
        and not repository.jobs
        and not repository.decisions
    )


@pytest.mark.asyncio
async def test_admin_reject_and_paused_owner_cancel_release_active_only():
    repository, service, _, intent = await reviewing()
    with pytest.raises(PermissionError):
        await service.review_detail(
            OWNER, intent.submission_id, session=SESSION
        )
    rejected = await service.decide(
        replace(intent, decision="reject"), session=SESSION
    )
    assert rejected["state"] == "rejected" and not repository.jobs
    assert len(repository.facts.usage) == 1 and not repository.facts.occupations
    # A second synthetic prepared submission demonstrates safe cancellation.
    repository.states[command().campaign_id] = replace(
        repository.states[command().campaign_id], state="submitted"
    )
    repository.active = False
    result = await service.cancel(
        CancelCampaign(
            OWNER, "cancel", command().campaign_id, rejected["version"], "Stop"
        ),
        session=SESSION,
    )
    assert result["state"] == "cancelled" and len(repository.facts.usage) == 1


@pytest.mark.asyncio
async def test_review_keeps_entire_subset_and_never_adds_invitees():
    from ugc_bot.application.campaign_moderation_ports import (
        CampaignCandidateFacts,
    )
    from ugc_bot.application.services.campaign_moderation_service import (
        CampaignModerationService,
    )

    repository, submitter, capacity = environment()
    add_member(repository, 500)
    accepted = await submitter.submit(command(), session=SESSION)
    first = repository.members[0].member
    first["consent"]["active"] = False
    repository.members[0] = CampaignCandidateFacts.from_member(first)
    add_member(repository, 501)
    service = CampaignModerationService(repository, capacity, capacity.clock)
    detail = await service.review_detail(
        ADMIN, UUID(accepted["submission_id"]), session=SESSION
    )
    assert detail["submitted_count"] == 2 and detail["surviving_count"] == 1
    intent = ReviewCampaign(
        ADMIN,
        "subset",
        command().campaign_id,
        UUID(accepted["submission_id"]),
        accepted["version"],
        command().revision_digest,
        detail["review_context"],
        "approve",
        "Exact survivor",
    )
    result = await service.decide(intent, session=SESSION)
    approved_source = next(iter(repository.jobs.values())).source_id
    submitted_sources = next(iter(repository.submissions.values())).sources
    assert next(
        row for row in submitted_sources if row.source_id == approved_source
    ).candidate.user_id == UUID(int=500)
    assert result["approved_count"] == 1


@pytest.mark.asyncio
async def test_capacity_exclusion_is_reviewed_and_empty_approval_refuses():
    from ugc_bot.domain.campaign_capacity import CampaignUsage

    repository, service, _, intent = await reviewing()
    recipient = repository.members[0].scope
    repository.facts = replace(
        repository.facts,
        usage=repository.facts.usage
        + (
            CampaignUsage(
                UUID(int=991),
                "attempt_started",
                UUID(int=99),
                repository.at,
                recipient,
            ),
        ),
    )
    detail = await service.review_detail(
        ADMIN, intent.submission_id, session=SESSION
    )
    assert detail["surviving_count"] == 0 and detail["exclusions"] == {
        "recipient_capacity": 1
    }
    with pytest.raises(ValueError, match="empty_audience"):
        await service.decide(
            replace(intent, review_context=detail["review_context"]),
            session=SESSION,
        )
    assert len(repository.writes) == 1


@pytest.mark.asyncio
async def test_admin_queue_and_terminal_history_are_paged_safe_read_only():
    repository, service, _, intent = await reviewing()
    before = len(repository.writes)
    queue = await service.queue(ADMIN, 0, session=SESSION)
    assert len(queue["submissions"]) == 1 and not queue["has_more"]
    assert "telegram" not in str(queue) and len(repository.writes) == before
    repository.admins.add(OWNER)
    with pytest.raises(PermissionError, match="distinct_admin"):
        await service.review_detail(
            OWNER, intent.submission_id, session=SESSION
        )
    await service.decide(replace(intent, decision="reject"), session=SESSION)
    assert not (await service.queue(ADMIN, 0, session=SESSION))["submissions"]
    for page in (True, -1, 100001):
        with pytest.raises(ValueError, match="invalid_page"):
            await service.queue(ADMIN, page, session=SESSION)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "terminal",
        "expired",
        "untyped_review",
        "revision",
        "untyped_cancel",
        "foreign_cancel",
        "inactive_cancel",
    ],
)
async def test_review_and_cancel_refuse_stale_foreign_invalid_commands(failure):
    from datetime import timedelta

    repository, service, _, intent = await reviewing()
    if failure == "missing":
        repository.submissions.clear()
    elif failure == "terminal":
        state = repository.states[intent.campaign_id]
        repository.states[intent.campaign_id] = replace(
            state, state="cancelled"
        )
    elif failure == "expired":
        repository.at += timedelta(
            seconds=repository.policy.limits["review_ttl_seconds"]
        )
    elif failure == "revision":
        intent = replace(intent, revision_digest="f" * 64)
    elif failure == "untyped_review":
        intent = {}
    if failure in ("untyped_cancel", "foreign_cancel", "inactive_cancel"):
        if failure == "inactive_cancel":
            state = repository.states[intent.campaign_id]
            repository.states[intent.campaign_id] = replace(
                state, state="cancelled"
            )
        cancellation = (
            {}
            if failure == "untyped_cancel"
            else CancelCampaign(
                ADMIN if failure == "foreign_cancel" else OWNER,
                "cancel",
                command().campaign_id,
                4,
                "Stop",
            )
        )
        with pytest.raises((ValueError, PermissionError)):
            await service.cancel(cancellation, session=SESSION)
    else:
        with pytest.raises((ValueError, PermissionError, LookupError)):
            await service.decide(intent, session=SESSION)
    assert len(repository.writes) == 1


@pytest.mark.asyncio
async def test_owner_cancel_releases_only_unstarted_reservations_and_replays():
    repository, service, _, intent = await reviewing()
    approved = await service.decide(intent, session=SESSION)
    cancellation = CancelCampaign(
        OWNER,
        "cancel-approved",
        command().campaign_id,
        approved["version"],
        "Stop",
    )
    result = await service.cancel(cancellation, session=SESSION)
    assert result["state"] == "cancelled"
    assert all(
        row.status == "released" for row in repository.facts.reservations
    )
    assert len(repository.facts.usage) == 1 and not repository.facts.occupations
    assert (await service.cancel(cancellation, session=SESSION))[
        "state"
    ] == "cancelled"
    assert len(repository.writes) == 3


@pytest.mark.asyncio
async def test_owner_capacity_shortage_refuses_whole_reviewed_audience():
    from ugc_bot.application.services.campaign_moderation_service import (
        CampaignModerationService,
    )

    repository, submitter, capacity = environment()
    repository.policy = replace(
        repository.policy,
        limits=repository.policy.limits.with_values(attempts_per_owner=1),
    )
    add_member(repository, 500)
    accepted = await submitter.submit(command(), session=SESSION)
    service = CampaignModerationService(repository, capacity, capacity.clock)
    detail = await service.review_detail(
        ADMIN, UUID(accepted["submission_id"]), session=SESSION
    )
    assert (
        detail["surviving_count"] == 2
        and "owner_attempts" in detail["capacity"]["reasons"]
    )
    intent = ReviewCampaign(
        ADMIN,
        "capacity-refusal",
        command().campaign_id,
        UUID(accepted["submission_id"]),
        accepted["version"],
        command().revision_digest,
        detail["review_context"],
        "approve",
        "Whole audience",
    )
    with pytest.raises(ValueError, match="^campaign_capacity_exceeded$"):
        await service.decide(intent, session=SESSION)
    assert len(repository.writes) == 1 and not repository.jobs


@pytest.mark.asyncio
async def test_review_deadline_after_capacity_wait_uses_post_wait_time():
    repository, service, _, intent = await reviewing()
    original_due, original_facts = repository.due, repository.capacity_facts
    waiting = False

    async def due(*args, **kwargs):
        nonlocal waiting
        waiting = True
        return await original_due(*args, **kwargs)

    async def facts(*args, **kwargs):
        result = await original_facts(*args, **kwargs)
        if waiting:
            repository.at = repository.submissions[
                intent.submission_id
            ].seal.review_deadline
        return result

    repository.due, repository.capacity_facts = due, facts
    with pytest.raises(ValueError, match="^campaign_review_expired$"):
        await service.decide(intent, session=SESSION)
    assert len(repository.writes) == 1 and not repository.jobs


@pytest.mark.asyncio
async def test_approval_never_resolves_current_sender_or_rebuilds_template():
    from ugc_bot.application.campaign_moderation_ports import (
        CampaignSenderSnapshot,
    )

    repository, service, _, intent = await reviewing()
    expected = repository.submissions[intent.submission_id].seal.envelope

    async def changed_sender(*args, **kwargs):
        return CampaignSenderSnapshot("Changed current brand", "changed-source")

    repository.sender_snapshot = changed_sender
    await service.decide(intent, session=SESSION)
    review = next(iter(repository.decisions.values()))
    assert review.context.submission.envelope == expected
    assert (
        review.context.submission.envelope.payload["sender_label"]
        == "Synthetic sender"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["detail", "approve", "reject"])
@pytest.mark.parametrize("changed", ["content", "campaign", "owner"])
async def test_exact_sealed_revision_precedes_private_review_reads(
    boundary, changed
):
    from ugc_bot.domain.campaign_review import CampaignDraftContent
    from ugc_bot.domain.campaigns import digest

    repository, service, _, intent = await reviewing()
    state = repository.states[intent.campaign_id]
    values = {
        "content": {"content": CampaignDraftContent("Changed", "Other text")},
        "campaign": {"campaign_id": UUID(int=701)},
        "owner": {"owner_id": UUID(int=702)},
    }[changed]
    payload = {
        **state.revision.payload,
        **{
            key: value.payload if key == "content" else str(value)
            for key, value in values.items()
        },
    }
    altered = replace(state.revision, **values, revision_digest=digest(payload))
    repository.states[intent.campaign_id] = replace(state, revision=altered)
    assert altered.revision_version == state.revision.revision_version
    repository.trace.clear()
    with pytest.raises(
        ValueError, match="^campaign_submission_integrity_unavailable$"
    ):
        if boundary == "detail":
            await service.review_detail(
                ADMIN, intent.submission_id, session=SESSION
            )
        else:
            # Reuse the earlier valid context and call the decision directly;
            # no inconsistent detail is needed to prove this guard.
            await service.decide(
                replace(
                    intent,
                    decision=boundary,
                    revision_digest=altered.revision_digest,
                ),
                session=SESSION,
            )
    assert "candidates" not in repository.trace
    assert "capacity" not in repository.trace
    assert len(repository.writes) == 1
    assert not repository.jobs and not repository.decisions


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed", ["policy", "grant", "grant_version", "publication"]
)
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_fresh_rejection_cleans_up_after_authority_changes(
    changed, platform
):
    from ugc_bot.application.native_principal_ports import (
        AuthenticatedMessengerPrincipal,
    )

    repository, service, _, intent = await reviewing()
    if changed in ("grant", "grant_version"):
        repository.grant = replace(
            repository.grant, active=changed == "grant_version", version=5
        )
    else:
        repository.policy = replace(
            repository.policy,
            enabled=changed != "policy",
            stream_version=3,
            publication_version=3 if changed == "publication" else 2,
        )
    proof = AuthenticatedMessengerPrincipal(ADMIN, platform, "101")
    with pytest.raises(ValueError, match="^campaign_review_context_changed$"):
        await service.decide(
            replace(intent, decision="reject"),
            principal=proof,
            session=SESSION,
        )
    detail = await service.review_detail(
        ADMIN, intent.submission_id, principal=proof, session=SESSION
    )
    current = replace(intent, review_context=detail["review_context"])
    denial = "publisher" if changed.startswith("grant") else "terms"
    with pytest.raises(ValueError, match=f"^campaign_{denial}_changed$"):
        await service.decide(current, principal=proof, session=SESSION)
    assert len(repository.writes) == 1 and not repository.jobs
    repository.trace.clear()
    rejected = replace(current, decision="reject")
    result = await service.decide(rejected, principal=proof, session=SESSION)
    assert result["state"] == "rejected" and result["approved_count"] == 0
    assert result["delivery_state"] == "not_applicable"
    assert not repository.facts.occupations and not repository.jobs
    assert not repository.facts.reservations
    assert len(repository.facts.usage) == 1
    assert len(repository.decisions) == 1 and len(repository.writes) == 2
    assert "due" not in repository.trace
    assert not repository.writes[-1].capacity.reservations
    assert repository.trace.index("receipt") < repository.trace.index(
        "candidates"
    )
    assert (
        next(iter(repository.decisions.values())).context.submission.envelope
        == repository.submissions[intent.submission_id].seal.envelope
    )
    repository.trace.clear()
    replay = await service.decide(rejected, principal=proof, session=SESSION)
    assert replay["review_id"] == result["review_id"]
    assert replay["current_state"] == "rejected" and replay["is_current"]
    assert "candidates" not in repository.trace
    assert "capacity" not in repository.trace
    assert len(repository.writes) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    ["policy", "grant", "foreign_grant", "native", "inactive", "admin"],
)
async def test_safe_rejection_requires_current_native_admin_and_authority_facts(
    failure,
):
    from ugc_bot.application.native_principal_ports import (
        AuthenticatedMessengerPrincipal,
    )

    repository, service, _, intent = await reviewing()
    repository.policy = replace(
        repository.policy, enabled=False, stream_version=3
    )
    proof = AuthenticatedMessengerPrincipal(ADMIN, "telegram", "101")
    detail = await service.review_detail(
        ADMIN, intent.submission_id, principal=proof, session=SESSION
    )
    if failure == "policy":
        repository.policy = None
    elif failure == "grant":
        repository.grant = None
    elif failure == "foreign_grant":
        repository.grant = replace(repository.grant, owner_id=ADMIN)
    elif failure == "native":
        repository.native_changed = True
    elif failure == "inactive":
        repository.active = False
    else:
        repository.admins.clear()
    repository.trace.clear()
    with pytest.raises((ValueError, PermissionError)):
        await service.decide(
            replace(
                intent,
                decision="reject",
                review_context=detail["review_context"],
            ),
            principal=proof,
            session=SESSION,
        )
    assert "candidates" not in repository.trace
    assert "capacity" not in repository.trace
    assert len(repository.writes) == 1
    assert not repository.jobs and not repository.decisions

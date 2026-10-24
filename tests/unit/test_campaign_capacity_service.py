"""Declared synthetic quota history is not SQL or an attempt producer."""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from uuid import UUID

import pytest

from tests.unit.test_campaign_submission_service import (
    ADMIN,
    AT,
    OWNER,
    SESSION,
    command,
    environment,
    revision_for,
)


def limits(**changes):
    from ugc_bot.domain.campaign_capacity import CampaignLimits
    from ugc_bot.domain.campaigns import LIMIT_NAMES

    return CampaignLimits.from_mapping(
        {
            **dict.fromkeys(LIMIT_NAMES, 100),
            "window_seconds": 60,
            "recipient_cooldown_seconds": 30,
            **changes,
        }
    )


def scope(user=100, identity="synthetic-ig", destination="101"):
    from ugc_bot.domain.campaign_capacity import CampaignRecipientScope

    return CampaignRecipientScope(UUID(int=user), identity, destination)


def test_limits_are_complete_positive_and_windows_are_utc():
    from ugc_bot.domain.campaign_capacity import CampaignLimits, window_at

    value = limits()
    assert window_at(AT + timedelta(seconds=60), 60).start == AT + timedelta(
        seconds=60
    )
    for invalid in (
        {},
        {**value.payload, "attempts_global": True},
        {**value.payload, "invented": 1},
    ):
        with pytest.raises(ValueError):
            CampaignLimits.from_mapping(invalid)
    with pytest.raises(FrozenInstanceError):
        value.values = ()


def test_cross_publication_usage_reservations_and_cooldown_cannot_reset():
    from ugc_bot.domain.campaign_capacity import (
        CampaignCapacityFacts,
        CampaignUsage,
        evaluate_capacity,
    )

    use = CampaignUsage(UUID(int=1), "attempt_started", OWNER, AT, scope())
    facts = CampaignCapacityFacts((use, use), (), ())
    at = AT + timedelta(seconds=20)
    blocked = evaluate_capacity(
        facts,
        limits=limits(attempts_per_owner=1),
        owner_id=OWNER,
        recipients=(scope(),),
        at=at,
        intent="approve",
    )
    assert (
        "owner_attempts" in blocked.reasons
        and blocked.blocked_recipients == (UUID(int=100),)
    )
    # A changed window recomputes from immutable timestamps; it is no reset.
    changed = evaluate_capacity(
        facts,
        limits=limits(window_seconds=120, attempts_global=1),
        owner_id=OWNER,
        recipients=(scope(101, "alias-ig", "101"),),
        at=at,
        intent="approve",
    )
    assert (
        "global_attempts" in changed.reasons
        and changed.blocked_recipients == (UUID(int=101),)
    )
    free = evaluate_capacity(
        facts,
        limits=limits(window_seconds=10),
        owner_id=OWNER,
        recipients=(scope(),),
        at=AT + timedelta(seconds=30),
        intent="approve",
    )
    assert not free.reasons and not free.blocked_recipients


def test_frequency_counts_each_protected_key_without_union_overcount():
    from ugc_bot.domain.campaign_capacity import (
        CampaignCapacityFacts,
        CampaignUsage,
        evaluate_capacity,
    )

    # Each prior start shares a different protected key with this creator.
    # Neither key exceeds two starts when the new start is reserved.
    facts = CampaignCapacityFacts(
        (
            CampaignUsage(
                UUID(int=51),
                "attempt_started",
                OWNER,
                AT + timedelta(seconds=1),
                scope(100, "past-identity", "201"),
            ),
            CampaignUsage(
                UUID(int=52),
                "attempt_started",
                OWNER,
                AT + timedelta(seconds=1),
                scope(101, "synthetic-ig", "202"),
            ),
        ),
        (),
        (),
    )
    result = evaluate_capacity(
        facts,
        limits=limits(window_seconds=120, attempts_per_recipient=2),
        owner_id=OWNER,
        recipients=(scope(),),
        at=AT + timedelta(seconds=40),
        intent="approve",
    )
    assert not result.blocked_recipients and not result.reasons


def test_unreleased_claim_counts_and_future_usage_is_unavailable():
    from ugc_bot.domain.campaign_capacity import (
        CampaignCapacityFacts,
        CampaignReservation,
        CampaignUsage,
        evaluate_capacity,
        window_at,
    )

    reservation = CampaignReservation(
        UUID(int=1),
        UUID(int=2),
        UUID(int=3),
        OWNER,
        scope(),
        window_at(AT, 60),
        AT + timedelta(seconds=10),
    )
    facts = CampaignCapacityFacts((), (reservation,), ())
    blocked = evaluate_capacity(
        facts,
        limits=limits(),
        owner_id=UUID(int=99),
        recipients=(scope(),),
        at=AT + timedelta(seconds=11),
        intent="approve",
    )
    assert (
        "settlement_required" in blocked.reasons and blocked.blocked_recipients
    )
    future = CampaignUsage(
        UUID(int=4),
        "attempt_started",
        OWNER,
        AT + timedelta(seconds=1),
        scope(),
    )
    with pytest.raises(ValueError, match="integrity_unavailable"):
        evaluate_capacity(
            CampaignCapacityFacts((future,), (), ()),
            limits=limits(),
            owner_id=OWNER,
            recipients=(),
            at=AT,
            intent="submit",
        )


@pytest.mark.asyncio
async def test_bounded_expiry_commits_progress_and_replay_has_no_effect():
    from ugc_bot.application.campaign_moderation_ports import CampaignExpiryItem
    from ugc_bot.domain.campaign_moderation import SettleCampaignExpiry

    repository, _, capacity = environment()
    state = next(iter(repository.states.values()))
    repository.expiry = [
        CampaignExpiryItem(
            replace(state, state="submitted"),
            (),
            True,
            AT - timedelta(seconds=1),
            "review_expired",
        )
    ]
    intent = SettleCampaignExpiry(ADMIN, "expiry", 2, "Synthetic settlement")
    result = await capacity.settle_expired(intent, session=SESSION)
    assert result["settled_count"] == 1 and not result["has_more"]
    assert repository.states[state.campaign_id].state == "expired"
    assert (await capacity.settle_expired(intent, session=SESSION))[
        "settled_count"
    ] == 1
    assert len(repository.writes) == 1


def test_capacity_records_refuse_mutable_invalid_unknown_facts():
    from ugc_bot.domain.campaign_capacity import (
        CampaignCapacityDelta,
        CampaignCapacityFacts,
        CampaignLimits,
        CampaignOccupation,
        CampaignOccupationClose,
        CampaignReservation,
        CampaignReservationRelease,
        CampaignUsage,
        CampaignWindow,
        evaluate_capacity,
        window_at,
    )

    valid = CampaignReservation(
        UUID(int=1),
        UUID(int=2),
        UUID(int=3),
        OWNER,
        scope(),
        window_at(AT, 60),
        AT + timedelta(seconds=10),
    )
    for construct in (
        lambda: CampaignLimits(()),
        lambda: CampaignWindow(AT, AT),
        lambda: scope(identity=" "),
        lambda: scope(destination="00101"),
        lambda: CampaignUsage(UUID(int=1), "provider_accepted", OWNER, AT),
        lambda: CampaignOccupation(UUID(int=0), OWNER, AT),
        lambda: replace(valid, expires_at=AT),
        lambda: CampaignCapacityFacts([], (), ()),
        lambda: CampaignReservationRelease(UUID(int=1), AT, " "),
        lambda: CampaignOccupationClose(UUID(int=1), AT, " "),
        lambda: CampaignCapacityDelta(releases=[]),
        lambda: evaluate_capacity(
            CampaignCapacityFacts((), (), ()),
            limits=limits(),
            owner_id=OWNER,
            recipients=(),
            at=AT,
            intent="invented",
        ),
    ):
        with pytest.raises(ValueError):
            construct()
    first = CampaignUsage(UUID(int=2), "submission", OWNER, AT)
    with pytest.raises(ValueError, match="integrity_unavailable"):
        evaluate_capacity(
            CampaignCapacityFacts(
                (first, replace(first, owner_id=ADMIN)), (), ()
            ),
            limits=limits(),
            owner_id=OWNER,
            recipients=(),
            at=AT,
            intent="submit",
        )


def test_submission_and_active_limits_preserve_retained_usage():
    from ugc_bot.domain.campaign_capacity import (
        CampaignCapacityFacts,
        CampaignOccupation,
        CampaignUsage,
        evaluate_capacity,
    )

    facts = CampaignCapacityFacts(
        (CampaignUsage(UUID(int=1), "submission", OWNER, AT),),
        (),
        (CampaignOccupation(UUID(int=2), OWNER, AT + timedelta(seconds=20)),),
    )
    result = evaluate_capacity(
        facts,
        limits=limits(submissions_per_owner=1, active_per_owner=1),
        owner_id=OWNER,
        recipients=(),
        at=AT,
        intent="submit",
    )
    assert result.reasons == ("submissions_per_owner", "active_per_owner")


@pytest.mark.asyncio
async def test_expiry_backlog_needs_bounded_progress_before_admission():
    from ugc_bot.application.campaign_moderation_ports import (
        CampaignExpiryItem,
        CampaignState,
    )
    from ugc_bot.domain.campaign_capacity import CampaignOccupation
    from ugc_bot.domain.campaign_moderation import (
        CampaignLifecycleVersion,
        SettleCampaignExpiry,
    )

    repository, submitter, capacity = environment()
    states = tuple(
        CampaignState(
            revision_for(campaign=UUID(int=n)),
            CampaignLifecycleVersion(4, 3),
            "submitted",
        )
        for n in (100, 101, 102)
    )
    repository.states.update({row.campaign_id: row for row in states})
    repository.expiry = [
        CampaignExpiryItem(
            row, (), True, AT - timedelta(seconds=1), "review_expired"
        )
        for row in states
    ]
    repository.facts = replace(
        repository.facts,
        occupations=tuple(
            CampaignOccupation(
                row.campaign_id, OWNER, AT - timedelta(seconds=1)
            )
            for row in states
        ),
    )
    with pytest.raises(ValueError, match="settlement_required"):
        await submitter.submit(command(), session=SESSION)
    assert not repository.writes
    first = await capacity.settle_expired(
        SettleCampaignExpiry(ADMIN, "expiry-1", 2, "First batch"),
        session=SESSION,
    )
    assert first == {"settled_count": 2, "has_more": True}
    second = await capacity.settle_expired(
        SettleCampaignExpiry(ADMIN, "expiry-2", 2, "Second batch"),
        session=SESSION,
    )
    assert second == {"settled_count": 1, "has_more": False}
    assert not repository.expiry and not repository.facts.occupations


@pytest.mark.asyncio
async def test_window_expiry_releases_claim_but_keeps_campaign_active():
    from tests.unit.test_campaign_moderation_service import reviewing
    from ugc_bot.application.campaign_moderation_ports import CampaignExpiryItem
    from ugc_bot.domain.campaign_moderation import SettleCampaignExpiry

    repository, moderator, _, review = await reviewing()
    await moderator.decide(review, session=SESSION)
    state = repository.states[review.campaign_id]
    claim = repository.facts.reservations[0]
    repository.at = claim.expires_at
    repository.expiry = [
        CampaignExpiryItem(
            state,
            (claim.reservation_id,),
            False,
            claim.expires_at,
            "window_expired",
        )
    ]
    repository.policy = replace(repository.policy, enabled=False)
    await moderator.capacity.settle_expired(
        SettleCampaignExpiry(
            ADMIN, "window-expiry", 2, "Release unstarted claim"
        ),
        session=SESSION,
    )
    assert repository.states[state.campaign_id].state == "approved_waiting"
    assert (
        repository.facts.reservations[0].status == "released"
        and len(repository.facts.occupations) == 1
    )
    assert len(repository.facts.usage) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "facts",
        "batch",
        "future_due",
        "missing_reservation",
        "terminal_state",
        "policy",
        "version",
        "untyped",
        "context",
    ],
)
async def test_missing_inconsistent_capacity_is_unavailable_without_writes(
    failure,
):
    from ugc_bot.application.campaign_moderation_ports import CampaignExpiryItem
    from ugc_bot.domain.campaign_moderation import SettleCampaignExpiry

    repository, submitter, capacity = environment()
    intent = SettleCampaignExpiry(ADMIN, "expiry", 2, "Synthetic expiry")
    if failure == "facts":

        async def missing(*args, **kwargs):
            return None

        repository.capacity_facts = missing
    elif failure == "batch":

        async def missing_batch(*args, **kwargs):
            return None

        repository.due = missing_batch
        with pytest.raises(ValueError, match="capacity_unavailable"):
            await submitter.submit(command(), session=SESSION)
        return
    elif failure in ("future_due", "missing_reservation", "terminal_state"):
        state = next(iter(repository.states.values()))
        if failure != "terminal_state":
            state = replace(state, state="submitted")
        repository.expiry = [
            CampaignExpiryItem(
                state,
                (UUID(int=999),) if failure == "missing_reservation" else (),
                True,
                AT + timedelta(seconds=1) if failure == "future_due" else AT,
                "review_expired",
            )
        ]
    elif failure == "policy":
        repository.policy = None
    elif failure == "version":
        intent = replace(intent, expected_policy_version=1)
    elif failure == "untyped":
        intent = {}
    else:
        with pytest.raises(ValueError, match="caller_transaction"):
            await capacity.admission(
                OWNER,
                (),
                repository.policy,
                "submit",
                context=object(),
                session=SESSION,
            )
        return
    with pytest.raises(ValueError):
        await capacity.settle_expired(intent, session=SESSION)
    assert not repository.writes

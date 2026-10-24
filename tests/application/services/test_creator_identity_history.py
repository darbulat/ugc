"""Historical grades use observed canonical identities and direct links."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from tests.helpers.factories import create_test_blogger_profile
from ugc_bot.domain.entities import UserReferralBinding
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryUserReferralBindingRepository,
)

START = datetime(2026, 10, 23, tzinfo=timezone.utc)


class Clock:
    now = START

    def __call__(self):
        return self.now


def setup_history():
    from ugc_bot.application.services.creator_identity_history_service import (
        CreatorIdentityHistoryService,
    )
    from ugc_bot.infrastructure.memory_identity_history import (
        InMemoryCreatorIdentityHistoryRepository,
    )

    clock = Clock()
    history = InMemoryCreatorIdentityHistoryRepository(clock=clock)
    profiles = InMemoryBloggerProfileRepository(identity_history=history)
    bindings = InMemoryUserReferralBindingRepository(identity_history=history)
    return (
        CreatorIdentityHistoryService(history),
        history,
        profiles,
        bindings,
        clock,
    )


async def creator(
    profiles, bindings, partner, *, stable_id="stable-id", confirmed=True
):
    profile = await create_test_blogger_profile(
        profiles,
        uuid4(),
        instagram_url=f"https://instagram.com/u{uuid4().hex[:15]}",
        confirmed=confirmed,
    )
    profile = replace(profile, instagram_user_id=stable_id)
    await profiles.save(profile)
    await bindings.save(UserReferralBinding(partner, profile.user_id, START))
    return profile


@pytest.mark.asyncio
async def test_complete_empty_cutover_is_known_zero():
    service, _, _, _, _ = setup_history()
    result = await service.count_verified_direct_creators(uuid4(), START)
    assert result.verified_count == 0
    assert result.covered_from == START
    assert result.as_of == START


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "as_of",
    [START - timedelta(microseconds=1), START + timedelta(microseconds=1)],
)
async def test_out_of_coverage_payment_time_is_unknown(as_of):
    service, _, _, _, _ = setup_history()
    with pytest.raises(ValueError, match="coverage"):
        await service.count_verified_direct_creators(uuid4(), as_of)


@pytest.mark.asyncio
async def test_missing_cutover_is_unknown_instead_of_zero():
    from ugc_bot.application.services.creator_identity_history_service import (
        CreatorIdentityHistoryService,
    )
    from ugc_bot.infrastructure.memory_identity_history import (
        InMemoryCreatorIdentityHistoryRepository,
    )

    with pytest.raises(ValueError, match="coverage"):
        await CreatorIdentityHistoryService(
            InMemoryCreatorIdentityHistoryRepository()
        ).count_verified_direct_creators(uuid4(), START)


@pytest.mark.asyncio
async def test_unconfirmed_registration_then_proof_never_backdates_count():
    service, history, profiles, bindings, clock = setup_history()
    partner = uuid4()
    profile = await creator(profiles, bindings, partner, confirmed=False)
    clock.now += timedelta(hours=1)
    await profiles.save(replace(profile, confirmed=True))
    assert (
        await service.count_verified_direct_creators(partner, START)
    ).verified_count == 0
    assert (
        await service.count_verified_direct_creators(partner, clock.now)
    ).verified_count == 1
    assert history.identity_observations[-1].fact_at is None
    assert (
        history.identity_observations[-1].source == "canonical_profile_observed"
    )


@pytest.mark.asyncio
async def test_handle_change_and_revocation_preserve_past_identity():
    service, _, profiles, bindings, clock = setup_history()
    partner = uuid4()
    profile = await creator(profiles, bindings, partner)
    first = clock.now
    clock.now += timedelta(hours=1)
    renamed = replace(profile, instagram_url="https://instagram.com/renamed")
    await profiles.save(renamed)
    assert (
        await service.count_verified_direct_creators(partner, clock.now)
    ).verified_count == 1
    clock.now += timedelta(hours=1)
    await profiles.save(replace(renamed, confirmed=False))
    assert (
        await service.count_verified_direct_creators(partner, first)
    ).verified_count == 1
    assert (
        await service.count_verified_direct_creators(partner, clock.now)
    ).verified_count == 0


@pytest.mark.asyncio
async def test_new_stable_identity_revokes_old_without_double_counting():
    service, history, profiles, bindings, clock = setup_history()
    partner = uuid4()
    profile = await creator(profiles, bindings, partner)
    clock.now += timedelta(hours=1)
    await profiles.save(replace(profile, instagram_user_id="new-stable-id"))
    assert (
        await service.count_verified_direct_creators(partner, clock.now)
    ).verified_count == 1
    assert [
        (o.instagram_user_id, o.active)
        for o in history.identity_observations[-2:]
    ] == [
        ("stable-id", False),
        ("new-stable-id", True),
    ]


@pytest.mark.asyncio
async def test_duplicate_stable_id_in_observed_facts_never_increases_count():
    service, history, profiles, bindings, _ = setup_history()
    partner = uuid4()
    first = await creator(profiles, bindings, partner)
    second = replace(first, user_id=uuid4())
    history.observe_profile(None, second)
    await bindings.save(UserReferralBinding(partner, second.user_id, START))
    assert (
        await service.count_verified_direct_creators(partner, START)
    ).verified_count == 1


@pytest.mark.asyncio
async def test_new_direct_binding_cannot_be_backdated_by_source_created_at():
    service, _, profiles, bindings, clock = setup_history()
    partner, old_partner = uuid4(), uuid4()
    profile = await creator(profiles, bindings, old_partner)
    clock.now += timedelta(hours=1)
    await bindings.save(
        UserReferralBinding(
            partner, profile.user_id, START - timedelta(days=30)
        )
    )
    assert (
        await service.count_verified_direct_creators(partner, START)
    ).verified_count == 0
    assert (
        await service.count_verified_direct_creators(old_partner, START)
    ).verified_count == 1
    assert (
        await service.count_verified_direct_creators(partner, clock.now)
    ).verified_count == 1
    assert (
        await service.count_verified_direct_creators(old_partner, clock.now)
    ).verified_count == 0


@pytest.mark.asyncio
async def test_future_dated_direct_binding_activates_at_its_source_boundary():
    service, _, profiles, bindings, clock = setup_history()
    partner = uuid4()
    profile = await creator(profiles, bindings, uuid4())
    future = START + timedelta(hours=1)
    await bindings.save(UserReferralBinding(partner, profile.user_id, future))
    assert (
        await service.count_verified_direct_creators(partner, START)
    ).verified_count == 0
    clock.now = future
    assert (
        await service.count_verified_direct_creators(partner, future)
    ).verified_count == 1


@pytest.mark.asyncio
async def test_direct_binding_deletion_removes_future_count_only():
    service, history, profiles, bindings, clock = setup_history()
    partner = uuid4()
    profile = await creator(profiles, bindings, partner)
    old = await bindings.get_by_referred_user(profile.user_id)
    clock.now += timedelta(hours=1)
    history.observe_binding(old, None)
    assert (
        await service.count_verified_direct_creators(partner, START)
    ).verified_count == 1
    assert (
        await service.count_verified_direct_creators(partner, clock.now)
    ).verified_count == 0


@pytest.mark.asyncio
async def test_webhook_evidence_is_idempotent_and_keeps_actual_fact_time():
    from ugc_bot.application.identity_history_ports import (
        IdentityEvidence,
        identity_evidence,
    )

    service, history, profiles, bindings, clock = setup_history()
    partner = uuid4()
    profile = await creator(profiles, bindings, partner, confirmed=False)
    clock.now += timedelta(hours=1)
    evidence = IdentityEvidence(
        "instagram_webhook", "proof:123", clock.now - timedelta(minutes=1)
    )
    with identity_evidence(evidence):
        await profiles.save(replace(profile, confirmed=True))
    length = len(history.identity_observations)
    with identity_evidence(evidence):
        await profiles.save(replace(profile, confirmed=True))
    assert len(history.identity_observations) == length
    fact = history.identity_observations[-1]
    assert fact.fact_at == START + timedelta(minutes=59)
    assert fact.observed_at == START + timedelta(hours=1)
    assert fact.source == "instagram_webhook"
    assert (
        await service.count_verified_direct_creators(
            partner, START + timedelta(minutes=59)
        )
    ).verified_count == 0
    with identity_evidence(evidence), pytest.raises(ValueError, match="replay"):
        await profiles.save(
            replace(profile, instagram_user_id="other-id", confirmed=True)
        )
    assert (
        await profiles.get_by_user_id(profile.user_id)
    ).instagram_user_id == "stable-id"
    assert len(history.identity_observations) == length
    await profiles.save(replace(profile, confirmed=False))
    assert (
        history.identity_observations[-1].source == "canonical_profile_observed"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["instagram_webhook", "manual_code"])
async def test_real_verifier_emits_proof_provenance_without_request_fields(
    source,
):
    from tests.application.services.test_social_account_service import (
        setup_service,
    )
    from tests.helpers.factories import create_test_user
    from ugc_bot.application.services.instagram_verification_service import (
        InstagramVerificationService,
    )
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryInstagramGraphApiClient,
        InMemoryInstagramVerificationRepository,
        InMemoryUserRepository,
    )

    _, owner, _, profiles = await setup_service(
        confirmed=False, instagram_id=None
    )
    users = InMemoryUserRepository()
    await create_test_user(users, user_id=owner)
    verifier = InstagramVerificationService(
        users,
        profiles,
        InMemoryInstagramVerificationRepository(),
        InMemoryInstagramGraphApiClient(
            username_map={"known-stable-id": "creator"}
        ),
    )
    from tests.helpers.legacy_verification import MemoryVerificationTransaction

    verifier.transaction_manager = MemoryVerificationTransaction(
        users, profiles, verifier.verification_repo
    )
    proof = await verifier.generate_code(owner)
    if source == "instagram_webhook":
        await verifier.verify_code_by_instagram_sender(
            "known-stable-id", proof.code, "admin"
        )
    else:
        await verifier.verify_code(owner, proof.code)
    latest = profiles.identity_history.identity_observations[-1]
    assert latest.source == source
    assert str(proof.code_id) in latest.business_key
    assert latest.fact_at is not None
    assert latest.fact_at <= latest.observed_at


@pytest.mark.asyncio
async def test_missing_cutover_seed_fails_closed():
    from ugc_bot.application.services.creator_identity_history_service import (
        CreatorIdentityHistoryService,
    )
    from ugc_bot.infrastructure.memory_identity_history import (
        InMemoryCreatorIdentityHistoryRepository,
    )

    _, _, profiles, bindings, clock = setup_history()
    await creator(profiles, bindings, uuid4())
    history = InMemoryCreatorIdentityHistoryRepository(clock=clock)
    history.seed_profiles(tuple(profiles.profiles.values()))
    history.seed_bindings(tuple(bindings._bindings))
    history._identity_observations.clear()
    with pytest.raises(ValueError, match="coverage"):
        await CreatorIdentityHistoryService(
            history
        ).count_verified_direct_creators(uuid4(), START)


@pytest.mark.asyncio
async def test_future_source_fact_time_is_rejected_without_mutating_profile():
    from ugc_bot.application.identity_history_ports import (
        IdentityEvidence,
        identity_evidence,
    )

    _, _, profiles, bindings, clock = setup_history()
    profile = await creator(profiles, bindings, uuid4(), confirmed=False)
    with (
        pytest.raises(ValueError, match="future"),
        identity_evidence(
            IdentityEvidence(
                "instagram_webhook",
                "future-proof",
                clock.now + timedelta(hours=1),
            )
        ),
    ):
        await profiles.save(replace(profile, confirmed=True))
    assert (await profiles.get_by_user_id(profile.user_id)).confirmed is False


@pytest.mark.parametrize(
    "source,key",
    [
        ("request_body", "proof"),
        ("instagram_webhook", ""),
        ("manual_code", " " * 5),
        ("manual_code", "x" * 257),
    ],
)
def test_evidence_requires_server_source_and_real_proof_key(source, key):
    from ugc_bot.application.identity_history_ports import IdentityEvidence

    with pytest.raises(ValueError):
        IdentityEvidence(source, key, START)


@pytest.mark.asyncio
async def test_naive_payment_and_proof_times_cannot_be_interpreted_as_utc():
    from ugc_bot.application.identity_history_ports import IdentityEvidence

    service, _, _, _, _ = setup_history()
    with pytest.raises(ValueError, match="aware"):
        await service.count_verified_direct_creators(
            uuid4(), START.replace(tzinfo=None)
        )
    with pytest.raises(ValueError, match="aware"):
        IdentityEvidence(
            "instagram_webhook", "proof", START.replace(tzinfo=None)
        )


@pytest.mark.asyncio
async def test_memory_profile_deletion_preserves_past_count():
    service, history, profiles, bindings, clock = setup_history()
    partner = uuid4()
    profile = await creator(profiles, bindings, partner)
    clock.now += timedelta(hours=1)
    history.observe_profile(profile, None)
    assert (
        await service.count_verified_direct_creators(partner, START)
    ).verified_count == 1
    assert (
        await service.count_verified_direct_creators(partner, clock.now)
    ).verified_count == 0


@pytest.mark.asyncio
async def test_sqlite_has_no_trusted_postgres_coverage():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ugc_bot.application.services.creator_identity_history_service import (
        CreatorIdentityHistoryService,
    )
    from ugc_bot.infrastructure.db.repositories.identity_history import (
        SqlAlchemyCreatorIdentityHistoryRepository,
    )

    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        service = CreatorIdentityHistoryService(
            SqlAlchemyCreatorIdentityHistoryRepository(
                async_sessionmaker(engine)
            )
        )
        with pytest.raises(ValueError, match="coverage"):
            await service.count_verified_direct_creators(uuid4(), START)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_repeated_initialization_cannot_reset_the_coverage_boundary():
    service, history, profiles, bindings, clock = setup_history()
    partner = uuid4()
    await creator(profiles, bindings, partner)
    clock.now += timedelta(hours=1)
    history.seed_profiles(profiles.profiles.values())
    history.seed_bindings(bindings._bindings)
    result = await service.count_verified_direct_creators(partner, START)
    assert result.verified_count == 1
    assert result.covered_from == START


@pytest.mark.asyncio
async def test_direct_binding_replay_keeps_first_relation_and_one_observation():
    service, history, profiles, bindings, _ = setup_history()
    partner = uuid4()
    profile = await creator(profiles, bindings, partner)
    binding = await bindings.get_by_referred_user(profile.user_id)
    await bindings.save(binding)
    stored, created = await bindings.save_or_get_existing(
        replace(binding, referrer_user_id=uuid4())
    )
    assert stored == binding
    assert created is False
    assert len(history.binding_observations) == 1
    assert history.binding_observations[0].source == "direct_binding_observed"
    assert (
        await service.count_verified_direct_creators(partner, START)
    ).verified_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("number", [0, 100, 200, 400])
async def test_grade_input_counts_whole_verified_network_without_orders(number):
    service, _, profiles, bindings, _ = setup_history()
    partner = uuid4()
    for index in range(number):
        await creator(profiles, bindings, partner, stable_id=f"stable-{index}")
    assert (
        await service.count_verified_direct_creators(partner, START)
    ).verified_count == number

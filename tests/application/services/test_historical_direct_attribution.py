"""A payment uses its observed direct attribution, not today's binding row."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from tests.application.services.test_creator_identity_history import (
    START,
    setup_history,
)
from tests.helpers.factories import create_test_user
from ugc_bot.domain.entities import UserReferralBinding
from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository


async def setup_attribution():
    service, history, profiles, bindings, clock = setup_history()
    users = InMemoryUserRepository(identity_history=history)
    user = await create_test_user(users, created_at=START - timedelta(days=400))
    return service, history, users, bindings, clock, user


@pytest.mark.asyncio
async def test_known_absence_has_coverage_without_invented_registration():
    service, _, _, _, _, user = await setup_attribution()
    result = await service.resolve_direct_binding(user.user_id, START)
    assert result.referrer_user_id is None
    assert result.registered_at is None
    assert result.observation_sequence is None
    assert result.reason == "unbound"
    assert result.covered_from == START


@pytest.mark.asyncio
async def test_active_direct_relation_carries_immutable_registration_fact():
    service, _, users, bindings, _, user = await setup_attribution()
    partner = uuid4()
    await bindings.save(
        UserReferralBinding(partner, user.user_id, START - timedelta(days=100))
    )
    result = await service.resolve_direct_binding(user.user_id, START)
    assert result.referrer_user_id == partner
    assert result.registered_at == START - timedelta(days=400)
    assert result.binding_created_at == START - timedelta(days=100)
    assert result.binding_effective_at == START
    assert result.observation_sequence == 1
    assert result.reason is None
    assert (
        await users.get_by_id(user.user_id)
    ).created_at == result.registered_at


@pytest.mark.asyncio
async def test_correction_keeps_old_payment_attribution_and_original_date():
    service, _, _, bindings, clock, user = await setup_attribution()
    first, second = uuid4(), uuid4()
    old = UserReferralBinding(first, user.user_id, START - timedelta(days=100))
    await bindings.save(old)
    clock.now += timedelta(hours=1)
    await bindings.save(replace(old, referrer_user_id=second))
    assert (
        await service.resolve_direct_binding(user.user_id, START)
    ).referrer_user_id == first
    assert (
        await service.resolve_direct_binding(user.user_id, clock.now)
    ).referrer_user_id == second


@pytest.mark.asyncio
async def test_binding_created_after_payment_cannot_be_backdated():
    service, _, _, bindings, clock, user = await setup_attribution()
    clock.now += timedelta(hours=1)
    await bindings.save(
        UserReferralBinding(uuid4(), user.user_id, START - timedelta(days=100))
    )
    result = await service.resolve_direct_binding(user.user_id, START)
    assert result.referrer_user_id is None
    assert result.reason == "unbound"


@pytest.mark.asyncio
async def test_deletion_keeps_old_recipient_then_returns_known_revocation():
    service, history, _, bindings, clock, user = await setup_attribution()
    partner = uuid4()
    old = UserReferralBinding(partner, user.user_id, START)
    await bindings.save(old)
    clock.now += timedelta(hours=1)
    history.observe_binding(old, None)
    assert (
        await service.resolve_direct_binding(user.user_id, START)
    ).referrer_user_id == partner
    revoked = await service.resolve_direct_binding(user.user_id, clock.now)
    assert revoked.referrer_user_id is None
    assert revoked.reason == "revoked"
    assert revoked.registered_at == START - timedelta(days=400)


@pytest.mark.asyncio
async def test_future_replacement_never_resurrects_previous_referrer():
    service, history, _, bindings, clock, user = await setup_attribution()
    first, second = uuid4(), uuid4()
    old = UserReferralBinding(first, user.user_id, START)
    await bindings.save(old)
    clock.now += timedelta(hours=1)
    future = START + timedelta(hours=3)
    await bindings.save(UserReferralBinding(second, user.user_id, future))
    assert [o.active for o in history.binding_observations[-2:]] == [
        False,
        True,
    ]
    clock.now = START + timedelta(hours=2)
    gap = await service.resolve_direct_binding(user.user_id, clock.now)
    assert gap.referrer_user_id is None
    assert gap.reason == "not_yet_effective"
    assert gap.binding_effective_at == future
    clock.now = future
    assert (
        await service.resolve_direct_binding(user.user_id, future)
    ).referrer_user_id == second


@pytest.mark.asyncio
async def test_self_referral_is_known_ineligible():
    service, _, _, bindings, _, user = await setup_attribution()
    await bindings.save(UserReferralBinding(user.user_id, user.user_id, START))
    result = await service.resolve_direct_binding(user.user_id, START)
    assert result.referrer_user_id is None
    assert result.reason == "self_referral"


@pytest.mark.asyncio
async def test_self_referral_cannot_increase_verified_direct_count():
    from tests.helpers.factories import create_test_blogger_profile

    service, _, profiles, bindings, _ = setup_history()
    user_id = uuid4()
    profile = await create_test_blogger_profile(
        profiles, user_id, confirmed=True
    )
    await profiles.save(replace(profile, instagram_user_id="self-stable-id"))
    await bindings.save(UserReferralBinding(user_id, user_id, START))
    result = await service.count_verified_direct_creators(user_id, START)
    assert result.verified_count == 0


@pytest.mark.asyncio
async def test_attribution_before_cutover_is_unknown_not_unbound():
    service, _, _, _, _, user = await setup_attribution()
    with pytest.raises(ValueError, match="coverage"):
        await service.resolve_direct_binding(
            user.user_id, START - timedelta(microseconds=1)
        )


@pytest.mark.asyncio
async def test_active_binding_without_registration_fact_fails_closed():
    service, _, _, bindings, _ = setup_history()
    referred = uuid4()
    await bindings.save(UserReferralBinding(uuid4(), referred, START))
    with pytest.raises(ValueError, match="registration"):
        await service.resolve_direct_binding(referred, START)


@pytest.mark.asyncio
async def test_repeated_user_save_cannot_rewrite_first_registration_fact():
    service, history, users, bindings, clock, user = await setup_attribution()
    partner = uuid4()
    await bindings.save(UserReferralBinding(partner, user.user_id, START))
    clock.now += timedelta(hours=1)
    await users.save(replace(user, created_at=clock.now))
    current = await bindings.get_by_referred_user(user.user_id)
    await bindings.save(replace(current, referrer_user_id=uuid4()))
    result = await service.resolve_direct_binding(user.user_id, clock.now)
    assert result.registered_at == START - timedelta(days=400)
    assert all(
        o.registered_at == result.registered_at
        for o in history.binding_observations
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("created_at", [None, START.replace(tzinfo=None)])
async def test_unknown_legacy_registration_does_not_invent_proof(created_at):
    service, history, _, bindings, _ = setup_history()
    users = InMemoryUserRepository(identity_history=history)
    user = await create_test_user(users, created_at=created_at)
    await bindings.save(UserReferralBinding(uuid4(), user.user_id, START))
    with pytest.raises(ValueError, match="registration"):
        await service.resolve_direct_binding(user.user_id, START)


@pytest.mark.asyncio
async def test_memory_registration_seed_preserves_actual_first_user_date():
    _, history, users, bindings, clock, user = await setup_attribution()
    seeded = InMemoryUserRepository(
        users={user.user_id: user}, identity_history=history
    )
    await seeded.save(replace(user, created_at=START))
    await bindings.save(UserReferralBinding(uuid4(), user.user_id, START))
    service, *_ = setup_history()
    service.repository = history
    await service.acquire_snapshot_barrier(session=None)
    result = await service.resolve_direct_binding(user.user_id, clock.now)
    assert result.registered_at == START - timedelta(days=400)


@pytest.mark.asyncio
async def test_sqlite_transaction_cannot_claim_snapshot_serialization():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ugc_bot.application.services.creator_identity_history_service import (
        CreatorIdentityHistoryService,
    )
    from ugc_bot.infrastructure.db.repositories.identity_history import (
        SqlAlchemyCreatorIdentityHistoryRepository,
    )

    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine)
    service = CreatorIdentityHistoryService(
        SqlAlchemyCreatorIdentityHistoryRepository(factory)
    )
    try:
        async with factory() as session:
            await session.begin()
            with pytest.raises(ValueError, match="postgres"):
                await service.acquire_snapshot_barrier(session=session)
    finally:
        await engine.dispose()

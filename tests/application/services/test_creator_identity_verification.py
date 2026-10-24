"""Instagram proofs bind one stable identity and retain genuine sources."""

from dataclasses import replace
from uuid import uuid4

import pytest

from tests.application.services.test_social_account_service import setup_service
from tests.helpers.factories import (
    create_test_blogger_profile,
    create_test_user,
)
from tests.helpers.legacy_verification import MemoryVerificationTransaction
from ugc_bot.application.ports import InstagramProfileInfo
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
    VerificationSuccess,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryInstagramGraphApiClient,
    InMemoryInstagramVerificationRepository,
    InMemoryUserRepository,
)


@pytest.mark.asyncio
async def test_webhook_identity_collision_does_not_consume_proof():
    _, owner, _, profiles = await setup_service(
        confirmed=False, instagram_id=None
    )
    other = await create_test_blogger_profile(
        profiles,
        uuid4(),
        instagram_url="https://instagram.com/old_handle",
    )
    await profiles.save(replace(other, instagram_user_id="stable-id"))
    users = InMemoryUserRepository()
    await create_test_user(users, user_id=owner)
    proofs = InMemoryInstagramVerificationRepository()
    verifier = InstagramVerificationService(
        users,
        profiles,
        proofs,
        InMemoryInstagramGraphApiClient(username_map={"stable-id": "creator"}),
    )
    verifier.transaction_manager = MemoryVerificationTransaction(
        users, profiles, verifier.verification_repo, verifier.social_repo
    )
    proof = await verifier.generate_code(owner)
    with pytest.raises(ValueError, match="identity"):
        await verifier.verify_code_by_instagram_sender(
            "stable-id", proof.code, "admin"
        )
    assert (await proofs.get_valid_code(owner, proof.code)) is not None
    assert (await profiles.get_by_user_id(owner)).confirmed is False


@pytest.mark.asyncio
async def test_manual_code_identity_collision_does_not_consume_proof():
    _, owner, _, profiles = await setup_service(confirmed=False)
    other = await create_test_blogger_profile(
        profiles,
        uuid4(),
        instagram_url="https://instagram.com/other",
    )
    await profiles.save(replace(other, instagram_user_id="ig-123"))
    users = InMemoryUserRepository()
    await create_test_user(users, user_id=owner)
    proofs = InMemoryInstagramVerificationRepository()
    verifier = InstagramVerificationService(users, profiles, proofs)
    verifier.transaction_manager = MemoryVerificationTransaction(
        users, profiles, verifier.verification_repo, verifier.social_repo
    )
    proof = await verifier.generate_code(owner)
    with pytest.raises(ValueError, match="identity"):
        await verifier.verify_code(owner, proof.code)
    assert (await proofs.get_valid_code(owner, proof.code)) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("followers", [None, 0, 1234])
async def test_webhook_persists_graph_source_only_for_observed_metrics(
    followers,
):
    social, owner, accounts, profiles = await setup_service(
        confirmed=False, instagram_id=None
    )
    users = InMemoryUserRepository()
    await create_test_user(users, user_id=owner)
    verifier = InstagramVerificationService(
        users,
        profiles,
        InMemoryInstagramVerificationRepository(),
        InMemoryInstagramGraphApiClient(
            profile_map={
                "trusted-id": InstagramProfileInfo(
                    "creator", followers_count=followers
                ),
            }
        ),
        social_repo=accounts,
    )
    verifier.transaction_manager = MemoryVerificationTransaction(
        users, profiles, verifier.verification_repo, verifier.social_repo
    )
    proof = await verifier.generate_code(owner)
    result = await verifier.verify_code_by_instagram_sender(
        "trusted-id", proof.code, "admin"
    )
    assert isinstance(result, VerificationSuccess)
    (stored,) = await accounts.list_accounts(owner)
    assert stored.verified is True
    assert stored.external_id == "trusted-id"
    assert stored.verification_source == "instagram_webhook"
    assert stored.verified_at is not None
    assert stored.verification_observed_at == stored.verified_at
    assert stored.followers_count == followers
    assert stored.metrics_source == (
        "instagram_graph_api" if followers is not None else None
    )
    assert (stored.metrics_fetched_at is not None) == (followers is not None)
    (visible,) = await social.list_accounts(owner)
    assert visible.metrics_source == stored.metrics_source
    assert visible.metrics_fetched_at == stored.metrics_fetched_at
    assert visible.verified_at == stored.verified_at


@pytest.mark.asyncio
async def test_profile_change_never_reuses_stale_metrics_or_verification():
    social, owner, accounts, profiles = await setup_service(
        confirmed=False, instagram_id=None
    )
    users = InMemoryUserRepository()
    await create_test_user(users, user_id=owner)
    verifier = InstagramVerificationService(
        users,
        profiles,
        InMemoryInstagramVerificationRepository(),
        InMemoryInstagramGraphApiClient(
            profile_map={
                "trusted-id": InstagramProfileInfo(
                    "creator", followers_count=500
                ),
            }
        ),
        social_repo=accounts,
    )
    verifier.transaction_manager = MemoryVerificationTransaction(
        users, profiles, verifier.verification_repo, verifier.social_repo
    )
    proof = await verifier.generate_code(owner)
    await verifier.verify_code_by_instagram_sender(
        "trusted-id", proof.code, "admin"
    )
    profile = await profiles.get_by_user_id(owner)
    await profiles.save(
        replace(
            profile,
            confirmed=False,
            instagram_url="https://instagram.com/new_handle",
            instagram_followers_count=None,
            instagram_stats_fetched_at=None,
        )
    )
    (visible,) = await social.list_accounts(owner)
    assert visible.verified is False
    assert visible.handle == "new_handle"
    assert visible.followers_count is None
    assert visible.metrics_source is None
    assert await social.next_platform(owner) == "instagram"


@pytest.mark.asyncio
async def test_manual_code_keeps_observation_without_sender_proof_time():
    social, owner, accounts, profiles = await setup_service(confirmed=False)
    users = InMemoryUserRepository()
    await create_test_user(users, user_id=owner)
    verifier = InstagramVerificationService(
        users,
        profiles,
        InMemoryInstagramVerificationRepository(),
        social_repo=accounts,
    )
    verifier.transaction_manager = MemoryVerificationTransaction(
        users, profiles, verifier.verification_repo, verifier.social_repo
    )
    proof = await verifier.generate_code(owner)
    assert await verifier.verify_code(owner, proof.code) is True
    (stored,) = await accounts.list_accounts(owner)
    assert stored.verified_at is None
    assert stored.verification_observed_at is not None
    assert stored.verification_source == "manual_code"
    (visible,) = await social.list_accounts(owner)
    assert visible.verification_source == "manual_code"


@pytest.mark.asyncio
async def test_legacy_blank_instagram_id_never_becomes_a_persisted_identity():
    _, owner, accounts, profiles = await setup_service(
        confirmed=False, instagram_id=" "
    )
    users = InMemoryUserRepository()
    await create_test_user(users, user_id=owner)
    verifier = InstagramVerificationService(
        users,
        profiles,
        InMemoryInstagramVerificationRepository(),
        social_repo=accounts,
    )
    verifier.transaction_manager = MemoryVerificationTransaction(
        users, profiles, verifier.verification_repo, verifier.social_repo
    )
    proof = await verifier.generate_code(owner)
    assert await verifier.verify_code(owner, proof.code) is True
    assert await accounts.list_accounts(owner) == []

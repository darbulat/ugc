"""Creator ownership, identity and truthful social account collection."""

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from tests.helpers.factories import create_test_blogger_profile
from ugc_bot.domain.enums import WorkFormat
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
)

NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)


async def setup_service(*, confirmed=True, instagram_id="ig-123"):
    from ugc_bot.application.services.social_account_service import (
        SocialAccountService,
    )
    from ugc_bot.infrastructure.memory_social import (
        InMemorySocialAccountRepository,
    )

    owner = uuid4()
    profiles = InMemoryBloggerProfileRepository()
    profile = await create_test_blogger_profile(
        profiles,
        owner,
        instagram_url="https://instagram.com/creator",
        confirmed=confirmed,
    )
    await profiles.save(replace(profile, instagram_user_id=instagram_id))
    accounts = InMemorySocialAccountRepository()
    return SocialAccountService(accounts, profiles), owner, accounts, profiles


@pytest.mark.asyncio
async def test_unverified_instagram_cannot_add_other_networks():
    service, owner, accounts, _ = await setup_service(confirmed=False)
    with pytest.raises(ValueError, match="Instagram"):
        await service.save_account(owner, "tiktok", "https://tiktok.com/@name")
    assert await accounts.list_accounts(owner) == []


@pytest.mark.asyncio
async def test_supplemental_links_stay_unverified_with_null_metrics():
    service, owner, _, _ = await setup_service()
    account = await service.save_account(
        owner,
        "tiktok",
        "https://www.tiktok.com/@Creator/?lang=ru",
        work_format=WorkFormat.ADS_IN_ACCOUNT,
    )
    assert account.user_id == owner
    assert account.url == "https://www.tiktok.com/@creator"
    assert account.handle == "creator"
    assert account.verified is False
    assert account.external_id is None
    assert account.followers_count is None
    assert account.metrics_source is None
    assert account.metrics_fetched_at is None
    assert account.work_format == WorkFormat.ADS_IN_ACCOUNT
    assert [str(a.platform) for a in await service.list_accounts(owner)] == [
        "instagram",
        "tiktok",
    ]


@pytest.mark.asyncio
async def test_ordered_prompts_skip_added_or_explicitly_skipped_networks():
    service, owner, _, _ = await setup_service()
    assert await service.next_platform(owner) == "tiktok"
    await service.save_account(owner, "tiktok", "https://tiktok.com/@creator")
    assert await service.next_platform(owner) == "youtube"
    assert await service.next_platform(owner, skipped={"youtube"}) == "telegram"
    await service.save_account(owner, "youtube", "https://youtube.com/@creator")
    await service.save_account(owner, "telegram", "https://t.me/creator")
    assert await service.next_platform(owner) is None
    assert await service.next_platform(owner, include_vk=True) == "vk"


@pytest.mark.asyncio
async def test_unverified_profile_prompts_for_instagram_first():
    service, owner, _, _ = await setup_service(confirmed=False)
    assert await service.next_platform(owner) == "instagram"


@pytest.mark.asyncio
async def test_remove_enforces_owner_and_never_deletes_another_creators_link():
    service, owner, _, profiles = await setup_service()
    stranger = uuid4()
    await create_test_blogger_profile(
        profiles, stranger, instagram_url="https://instagram.com/stranger"
    )
    account = await service.save_account(
        owner, "telegram", "https://t.me/creator"
    )
    with pytest.raises(ValueError, match="owner"):
        await service.remove_account(stranger, account.account_id)
    assert len(await service.list_accounts(owner)) == 2
    assert [str(a.platform) for a in await service.list_accounts(stranger)] == [
        "instagram"
    ]
    assert await service.remove_account(owner, account.account_id) is True
    assert await service.remove_account(owner, account.account_id) is False


@pytest.mark.asyncio
async def test_updating_platform_preserves_account_identity_and_creation_time():
    service, owner, _, _ = await setup_service()
    first = await service.save_account(owner, "telegram", "https://t.me/first")
    updated = await service.save_account(
        owner, "telegram", "https://t.me/second"
    )
    assert updated.account_id == first.account_id
    assert updated.created_at == first.created_at
    assert updated.url == "https://t.me/second"
    assert len(await service.list_accounts(owner)) == 2


@pytest.mark.asyncio
async def test_url_edit_preserves_the_accounts_work_format():
    service, owner, _, _ = await setup_service()
    await service.save_account(
        owner,
        "telegram",
        "https://t.me/first",
        work_format=WorkFormat.ADS_IN_ACCOUNT,
    )
    updated = await service.save_account(
        owner, "telegram", "https://t.me/second"
    )
    assert updated.work_format == WorkFormat.ADS_IN_ACCOUNT


@pytest.mark.asyncio
async def test_unknown_work_format_cannot_be_saved():
    service, owner, _, _ = await setup_service()
    with pytest.raises(ValueError):
        await service.save_account(
            owner, "telegram", "https://t.me/creator", work_format="unknown"
        )
    assert len(await service.list_accounts(owner)) == 1


@pytest.mark.parametrize(
    ("platform", "url"),
    [
        ("tiktok", "https://tiktok.com.evil.test/@creator"),
        ("tiktok", "https://evil.test/tiktok.com/@creator"),
        ("tiktok", "https://tiktok.com/@creator/video/123"),
        ("youtube", "https://youtube.com/watch?v=123"),
        ("youtube", "https://youtu.be/123"),
        ("telegram", "https://t.me/+invite"),
        ("telegram", "https://t.me/creator/123"),
        ("vk", "https://vk.com/wall123_456"),
        ("instagram", "https://instagram.com/p/123"),
        ("telegram", "javascript:alert(1)"),
        ("telegram", "http://t.me/creator"),
        ("telegram", "https://user:password@t.me/creator"),
        ("telegram", "https://t.me:8443/creator"),
        ("unknown", "https://example.com/creator"),
    ],
)
@pytest.mark.asyncio
async def test_rejects_non_profile_and_wrong_platform_urls(platform, url):
    service, owner, _, _ = await setup_service()
    with pytest.raises(ValueError):
        await service.save_account(owner, platform, url)
    assert len(await service.list_accounts(owner)) == 1


@pytest.mark.parametrize(
    ("platform", "url", "canonical", "handle"),
    [
        (
            "youtube",
            "https://m.youtube.com/@Creator/?view=1",
            "https://www.youtube.com/@creator",
            "creator",
        ),
        (
            "youtube",
            "https://youtube.com/channel/UCAbC_123",
            "https://www.youtube.com/channel/UCAbC_123",
            "UCAbC_123",
        ),
        (
            "youtube",
            "https://youtube.com/c/Creator",
            "https://www.youtube.com/c/creator",
            "creator",
        ),
        (
            "youtube",
            "https://youtube.com/user/Creator",
            "https://www.youtube.com/user/creator",
            "creator",
        ),
        (
            "telegram",
            "https://telegram.me/Creator/",
            "https://t.me/creator",
            "creator",
        ),
        ("vk", "https://m.vk.com/Creator", "https://vk.com/creator", "creator"),
    ],
)
@pytest.mark.asyncio
async def test_normalizes_supported_public_profile_urls(
    platform,
    url,
    canonical,
    handle,
):
    service, owner, _, _ = await setup_service()
    account = await service.save_account(owner, platform, url)
    assert (account.url, account.handle) == (canonical, handle)


@pytest.mark.asyncio
async def test_legacy_confirmed_profiles_remain_readable_without_invented_id():
    service, owner, _, _ = await setup_service(instagram_id=None)
    (instagram,) = await service.list_accounts(owner)
    assert instagram.user_id == owner
    assert instagram.platform == "instagram"
    assert instagram.verified is True
    assert instagram.external_id is None
    assert instagram.followers_count is None
    assert instagram.work_format == WorkFormat.UGC_ONLY
    await service.save_account(owner, "telegram", "https://t.me/creator")
    assert len(await service.list_accounts(owner)) == 2


@pytest.mark.asyncio
async def test_profile_metrics_preserve_observed_value_and_original_time():
    service, owner, _, profiles = await setup_service()
    profile = await profiles.get_by_user_id(owner)
    await profiles.save(
        replace(
            profile,
            instagram_followers_count=0,
            instagram_stats_fetched_at=NOW,
        )
    )
    (instagram,) = await service.list_accounts(owner)
    assert instagram.followers_count == 0
    assert instagram.metrics_source == "legacy_profile"
    assert instagram.metrics_fetched_at == NOW


@pytest.mark.asyncio
async def test_profile_metrics_without_observation_time_remain_unknown():
    service, owner, _, profiles = await setup_service()
    profile = await profiles.get_by_user_id(owner)
    await profiles.save(replace(profile, instagram_followers_count=999))
    (instagram,) = await service.list_accounts(owner)
    assert instagram.followers_count is None
    assert instagram.metrics_source is None
    assert instagram.metrics_fetched_at is None


@pytest.mark.asyncio
async def test_social_service_requires_existing_canonical_profile():
    service, _, _, _ = await setup_service()
    with pytest.raises(ValueError, match="profile"):
        await service.save_account(uuid4(), "telegram", "https://t.me/creator")
    assert await service.list_accounts(uuid4()) == []


@pytest.mark.asyncio
async def test_instagram_can_only_be_changed_through_verification():
    service, owner, _, _ = await setup_service()
    with pytest.raises(ValueError, match="verification"):
        await service.save_account(
            owner, "instagram", "https://instagram.com/other"
        )
    (instagram,) = await service.list_accounts(owner)
    with pytest.raises(ValueError, match="verification"):
        await service.remove_account(owner, instagram.account_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "duplicate_id", ["stable-instagram-id", " stable-instagram-id "]
)
async def test_confirmed_instagram_identity_cannot_belong_to_two_creators(
    duplicate_id,
):
    profiles = InMemoryBloggerProfileRepository()
    first = await create_test_blogger_profile(
        profiles, uuid4(), instagram_url="https://instagram.com/old_handle"
    )
    await profiles.save(replace(first, instagram_user_id="stable-instagram-id"))
    second = await create_test_blogger_profile(
        profiles, uuid4(), instagram_url="https://instagram.com/new_handle"
    )
    with pytest.raises(ValueError, match="identity"):
        await profiles.save(replace(second, instagram_user_id=duplicate_id))
    stored = await profiles.get_by_user_id(second.user_id)
    assert stored.instagram_user_id is None


@pytest.mark.asyncio
async def test_stable_identity_lookup_survives_handle_changes():
    profiles = InMemoryBloggerProfileRepository()
    profile = await create_test_blogger_profile(profiles, uuid4())
    await profiles.save(replace(profile, instagram_user_id="stable-id"))
    found = await profiles.get_by_instagram_user_id("stable-id")
    assert found.user_id == profile.user_id
    assert await profiles.get_by_instagram_user_id("missing") is None


@pytest.mark.asyncio
async def test_repository_cannot_transfer_or_remove_another_owners_account():
    service, owner, accounts, _ = await setup_service()
    account = await service.save_account(
        owner, "telegram", "https://t.me/creator"
    )
    with pytest.raises(ValueError, match="owner"):
        await accounts.save(replace(account, user_id=uuid4()))
    assert await accounts.remove(uuid4(), account.account_id) is False
    assert await accounts.get_by_id(account.account_id) == account


@pytest.mark.asyncio
async def test_persisted_instagram_cannot_be_removed_through_link_collection():
    from ugc_bot.application.services.social_account_service import (
        instagram_account,
    )

    service, owner, accounts, profiles = await setup_service()
    stored = replace(
        instagram_account(await profiles.get_by_user_id(owner)),
        account_id=uuid4(),
    )
    await accounts.save(stored)
    with pytest.raises(ValueError, match="verification"):
        await service.remove_account(owner, stored.account_id)
    assert await accounts.get_by_id(stored.account_id) == stored

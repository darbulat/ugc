"""Tests for profile service."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.domain.entities import AdvertiserProfile, BloggerProfile, User
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    UserStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryBloggerProfileRepository,
    InMemoryUserRepository,
)


@pytest.mark.asyncio
async def test_get_user_by_external_without_tm() -> None:
    """ProfileService without transaction_manager uses repo directly."""
    user_repo = InMemoryUserRepository()
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        telegram_id="ext1",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(user)
    service = ProfileService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
    )
    result = await service.get_user_by_external("ext1", MessengerType.TELEGRAM)
    assert result is not None
    assert result.telegram_id == "ext1"


@pytest.mark.asyncio
async def test_get_user_by_external_with_transaction_manager(fake_tm) -> None:
    """ProfileService with transaction_manager uses session path."""
    user_repo = InMemoryUserRepository()
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000002"),
        telegram_id="ext2",
        messenger_type=MessengerType.TELEGRAM,
        username="u2",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(user)
    service = ProfileService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
        transaction_manager=fake_tm,
    )
    result = await service.get_user_by_external("ext2", MessengerType.TELEGRAM)
    assert result is not None
    assert result.telegram_id == "ext2"


@pytest.mark.asyncio
async def test_get_blogger_profile_with_transaction_manager(fake_tm) -> None:
    """ProfileService get_blogger_profile with tm uses session."""
    user_id = UUID("00000000-0000-0000-0000-000000000003")
    blogger_repo = InMemoryBloggerProfileRepository()
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/x",
        confirmed=False,
        city="Moscow",
        topics={"selected": ["tech"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )
    await blogger_repo.save(profile)
    service = ProfileService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=blogger_repo,
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
        transaction_manager=fake_tm,
    )
    result = await service.get_blogger_profile(user_id)
    assert result is not None
    assert result.city == "Moscow"


@pytest.mark.asyncio
async def test_get_advertiser_profile_with_transaction_manager(fake_tm) -> None:
    """ProfileService get_advertiser_profile with tm uses session."""
    user_id = UUID("00000000-0000-0000-0000-000000000004")
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    profile = AdvertiserProfile(
        user_id=user_id,
        phone="contact@test.com",
        brand="Brand",
    )
    await advertiser_repo.save(profile)
    service = ProfileService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        advertiser_repo=advertiser_repo,
        transaction_manager=fake_tm,
    )
    result = await service.get_advertiser_profile(user_id)
    assert result is not None
    assert result.phone == "contact@test.com"


@pytest.mark.asyncio
async def test_get_blogger_profiles_returns_map_by_user_id() -> None:
    """get_blogger_profiles fetches multiple profiles by user_ids."""
    user_id = UUID("00000000-0000-0000-0000-000000000005")
    blogger_repo = InMemoryBloggerProfileRepository()
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/y",
        confirmed=False,
        city="SPb",
        topics={"selected": ["food"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=20,
        audience_age_max=40,
        audience_geo="SPb",
        price=500.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )
    await blogger_repo.save(profile)
    service = ProfileService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=blogger_repo,
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
    )
    result = await service.get_blogger_profiles([user_id])
    assert user_id in result
    assert result[user_id].city == "SPb"

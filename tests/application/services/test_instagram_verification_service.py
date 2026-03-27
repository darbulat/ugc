"""Tests for Instagram verification service."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from ugc_bot.application.errors import (
    BloggerRegistrationError,
    UserNotFoundError,
)
from ugc_bot.application.ports import InstagramProfileInfo
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
    VerificationApiUnavailable,
    VerificationLinkSuccess,
    VerificationMismatch,
    VerificationSuccess,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import (
    BloggerProfile,
    InstagramVerificationCode,
    User,
)
from ugc_bot.domain.enums import (
    AudienceGender,
    BloggerGender,
    MessengerType,
    UserStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryInstagramGraphApiClient,
    InMemoryInstagramVerificationRepository,
    InMemoryUserRepository,
)


async def _seed_user(user_repo: InMemoryUserRepository) -> UUID:
    """Seed a user in memory."""

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000130"),
        telegram_id="999",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(user)
    return user.user_id


async def _seed_profile(
    repo: InMemoryBloggerProfileRepository, user_id: UUID
) -> None:
    """Seed a blogger profile in memory."""

    await repo.save(
        BloggerProfile(
            user_id=user_id,
            instagram_url="https://instagram.com/test_user",
            confirmed=False,
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1500.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=datetime.now(timezone.utc),
        )
    )


@pytest.mark.asyncio
async def test_generate_code_requires_user() -> None:
    """Fail when user is missing."""

    service = InstagramVerificationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
    )

    with pytest.raises(UserNotFoundError):
        await service.generate_code(
            UUID("00000000-0000-0000-0000-000000000131")
        )


@pytest.mark.asyncio
async def test_verify_code_requires_profile() -> None:
    """Fail when blogger profile is missing."""

    user_repo = InMemoryUserRepository()
    user_id = await _seed_user(user_repo)
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
    )

    with pytest.raises(BloggerRegistrationError):
        await service.verify_code(user_id, "ABC123")


@pytest.mark.asyncio
async def test_verify_code_success() -> None:
    """Verify code and confirm profile."""

    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = await _seed_user(user_repo)
    await _seed_profile(profile_repo, user_id)

    code = InstagramVerificationCode(
        code_id=UUID("00000000-0000-0000-0000-000000000132"),
        user_id=user_id,
        code="ABC123",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        used=False,
        created_at=datetime.now(timezone.utc),
    )
    await verification_repo.save(code)

    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
    )

    assert await service.verify_code(user_id, "ABC123") is True
    updated = await profile_repo.get_by_user_id(user_id)
    assert updated is not None
    assert updated.confirmed is True


@pytest.mark.asyncio
async def test_verify_code_invalid() -> None:
    """Return false for invalid code."""

    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = await _seed_user(user_repo)
    await _seed_profile(profile_repo, user_id)

    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
    )

    assert await service.verify_code(user_id, "WRONG") is False


@pytest.mark.asyncio
async def test_verify_code_preserves_optional_fields() -> None:
    """Regression: verify_code must not drop optional profile fields."""

    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = await _seed_user(user_repo)
    now = datetime.now(timezone.utc)
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/verify_opt",
        confirmed=False,
        city="Moscow",
        topics={"selected": []},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=now,
        blogger_gender=BloggerGender.MALE,
        instagram_user_id="ig_verify_opt",
        instagram_followers_count=3000,
        instagram_username="verify_opt",
    )
    await profile_repo.save(profile)
    code = InstagramVerificationCode(
        code_id=UUID("00000000-0000-0000-0000-000000000133"),
        user_id=user_id,
        code="XYZ789",
        expires_at=now + timedelta(minutes=5),
        used=False,
        created_at=now,
    )
    await verification_repo.save(code)
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
    )
    assert await service.verify_code(user_id, "XYZ789") is True
    updated = await profile_repo.get_by_user_id(user_id)
    assert updated is not None
    assert updated.confirmed is True
    assert updated.blogger_gender == BloggerGender.MALE
    assert updated.instagram_user_id == "ig_verify_opt"
    assert updated.instagram_followers_count == 3000
    assert updated.instagram_username == "verify_opt"


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_success() -> None:
    """Test successful verification via Instagram webhook."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = await _seed_user(user_repo)
    await _seed_profile(profile_repo, user_id)

    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
    )

    # Generate code
    verification = await service.generate_code(user_id)

    # Verify via Instagram sender
    result = await service.verify_code_by_instagram_sender(
        instagram_sender_id="instagram_user_123",
        code=verification.code,
        admin_instagram_username="admin_test",
    )

    assert isinstance(result, VerificationSuccess) and result.user_id == user_id
    updated = await profile_repo.get_by_user_id(user_id)
    assert updated is not None
    assert updated.confirmed is True


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_invalid_code() -> None:
    """Test verification with invalid code."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = await _seed_user(user_repo)
    await _seed_profile(profile_repo, user_id)

    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
    )

    result = await service.verify_code_by_instagram_sender(
        instagram_sender_id="instagram_user_123",
        code="INVALID",
        admin_instagram_username="admin_test",
    )

    assert result is None
    updated = await profile_repo.get_by_user_id(user_id)
    assert updated is not None
    assert updated.confirmed is False


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_expired_code() -> None:
    """Test verification with expired code."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = await _seed_user(user_repo)
    await _seed_profile(profile_repo, user_id)

    # Create expired code
    expired_code = InstagramVerificationCode(
        code_id=UUID("00000000-0000-0000-0000-000000000133"),
        user_id=user_id,
        code="EXPIRED",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        used=False,
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    await verification_repo.save(expired_code)

    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
    )

    result = await service.verify_code_by_instagram_sender(
        instagram_sender_id="instagram_user_123",
        code="EXPIRED",
        admin_instagram_username="admin_test",
    )

    assert result is None


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_no_profile() -> None:
    """Test verification when profile doesn't exist."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = await _seed_user(user_repo)
    # Don't create profile

    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
    )

    # Generate code
    verification = await service.generate_code(user_id)

    result = await service.verify_code_by_instagram_sender(
        instagram_sender_id="instagram_user_123",
        code=verification.code,
        admin_instagram_username="admin_test",
    )

    assert result is None


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_used_code() -> None:
    """Test verification with already used code."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = await _seed_user(user_repo)
    await _seed_profile(profile_repo, user_id)

    # Create used code
    used_code = InstagramVerificationCode(
        code_id=UUID("00000000-0000-0000-0000-000000000134"),
        user_id=user_id,
        code="USED123",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        used=True,
        created_at=datetime.now(timezone.utc),
    )
    await verification_repo.save(used_code)

    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
    )

    result = await service.verify_code_by_instagram_sender(
        instagram_sender_id="instagram_user_123",
        code="USED123",
        admin_instagram_username="admin_test",
    )

    assert result is None


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_extracts_username_from_url() -> (
    None
):
    """Test that username is correctly extracted from Instagram URL."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = await _seed_user(user_repo)

    # Create profile with different URL formats
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/test_user",
        confirmed=False,
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )
    await profile_repo.save(profile)

    # Create API client that returns matching username
    api_client = InMemoryInstagramGraphApiClient(
        username_map={"instagram_user_123": "test_user"}
    )

    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
        instagram_api_client=api_client,
    )

    verification = await service.generate_code(user_id)

    result = await service.verify_code_by_instagram_sender(
        instagram_sender_id="instagram_user_123",
        code=verification.code,
        admin_instagram_username="admin_test",
    )

    assert isinstance(result, VerificationSuccess) and result.user_id == user_id
    updated = await profile_repo.get_by_user_id(user_id)
    assert updated is not None
    assert updated.confirmed is True


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_saves_instagram_stats() -> None:
    """Webhook verification saves instagram_user_id and stats from API."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = await _seed_user(user_repo)
    await _seed_profile(profile_repo, user_id)

    full_profile = InstagramProfileInfo(
        username="test_user",
        followers_count=1000,
        media_count=50,
        follows_count=200,
        biography="Fitness",
    )
    api_client = InMemoryInstagramGraphApiClient(
        profile_map={"instagram_sender_1": full_profile},
    )

    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
        instagram_api_client=api_client,
    )
    verification = await service.generate_code(user_id)

    result = await service.verify_code_by_instagram_sender(
        instagram_sender_id="instagram_sender_1",
        code=verification.code,
        admin_instagram_username="admin",
    )

    assert isinstance(result, VerificationSuccess)
    updated = await profile_repo.get_by_user_id(user_id)
    assert updated is not None
    assert updated.confirmed is True
    assert updated.instagram_user_id == "instagram_sender_1"
    assert updated.instagram_username == "test_user"
    assert updated.instagram_followers_count == 1000
    assert updated.instagram_stats_fetched_at is not None


@pytest.mark.asyncio
async def test_verify_code_username_extraction_variants() -> None:
    """Test username extraction from different Instagram URL formats."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = await _seed_user(user_repo)

    # Test with different URL formats
    url_formats = [
        "https://instagram.com/test_user",
        "http://instagram.com/test_user",
        "instagram.com/test_user",
        "@test_user",
        "test_user",
    ]

    for url_format in url_formats:
        profile = BloggerProfile(
            user_id=user_id,
            instagram_url=url_format,
            confirmed=False,
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=datetime.now(timezone.utc),
        )
        await profile_repo.save(profile)

        # Create API client that returns matching username
        api_client = InMemoryInstagramGraphApiClient(
            username_map={
                "instagram_user_123": url_format.replace("@", "")
                .replace("https://", "")
                .replace("http://", "")
                .replace("instagram.com/", "")
                .split("/")[0]
                if "/" in url_format
                else url_format.replace("@", "")
            }
        )

        service = InstagramVerificationService(
            user_repo=user_repo,
            blogger_repo=profile_repo,
            verification_repo=verification_repo,
            instagram_api_client=api_client,
        )

        verification = await service.generate_code(user_id)

        result = await service.verify_code_by_instagram_sender(
            instagram_sender_id="instagram_user_123",
            code=verification.code,
            admin_instagram_username="admin_test",
        )

        assert (
            isinstance(result, VerificationSuccess)
            and result.user_id == user_id
        )
        updated = await profile_repo.get_by_user_id(user_id)
        assert updated is not None
        assert updated.confirmed is True

        # Reset for next iteration
        await profile_repo.save(
            BloggerProfile(
                user_id=user_id,
                instagram_url=url_format,
                confirmed=False,
                city="Moscow",
                topics={"selected": ["fitness"]},
                audience_gender=AudienceGender.ALL,
                audience_age_min=18,
                audience_age_max=35,
                audience_geo="Moscow",
                price=1000.0,
                barter=False,
                work_format=WorkFormat.UGC_ONLY,
                updated_at=datetime.now(timezone.utc),
            )
        )


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_username_mismatch() -> None:
    """Test verification fails when username from API doesn't match profile."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = await _seed_user(user_repo)

    # Create profile with specific username
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/test_user",
        confirmed=False,
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )
    await profile_repo.save(profile)

    # Create API client that returns different username
    api_client = InMemoryInstagramGraphApiClient(
        username_map={"instagram_user_123": "different_user"}
    )

    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
        instagram_api_client=api_client,
    )

    verification = await service.generate_code(user_id)

    result = await service.verify_code_by_instagram_sender(
        instagram_sender_id="instagram_user_123",
        code=verification.code,
        admin_instagram_username="admin_test",
    )

    assert isinstance(result, VerificationMismatch)
    assert result.user_id == user_id
    assert result.profile_username == "test_user"
    assert result.api_username == "different_user"
    updated = await profile_repo.get_by_user_id(user_id)
    assert updated is not None
    assert updated.confirmed is False


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_api_exception() -> None:
    """Test verification handles API exceptions gracefully."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = await _seed_user(user_repo)

    # Create profile
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/test_user",
        confirmed=False,
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )
    await profile_repo.save(profile)

    # Create API client that raises an exception
    class FailingInstagramGraphApiClient(InMemoryInstagramGraphApiClient):
        async def get_username_by_id(
            self, instagram_user_id: str
        ) -> str | None:
            raise Exception("API error")

    api_client = FailingInstagramGraphApiClient()

    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
        instagram_api_client=api_client,
    )

    verification = await service.generate_code(user_id)

    # API unavailable — should NOT verify, returns VerificationApiUnavailable
    result = await service.verify_code_by_instagram_sender(
        instagram_sender_id="instagram_user_123",
        code=verification.code,
        admin_instagram_username="admin_test",
    )

    assert isinstance(result, VerificationApiUnavailable)
    assert result.user_id == user_id
    updated = await profile_repo.get_by_user_id(user_id)
    assert updated is not None
    assert updated.confirmed is False


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_url_parsing_edge_case() -> None:
    """Test username extraction when URL doesn't contain username."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = await _seed_user(user_repo)

    # Create profile with URL that doesn't match expected pattern
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com",  # No username in URL
        confirmed=False,
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )
    await profile_repo.save(profile)

    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
    )

    verification = await service.generate_code(user_id)

    # Should still succeed (no API client, so no username verification)
    result = await service.verify_code_by_instagram_sender(
        instagram_sender_id="instagram_user_123",
        code=verification.code,
        admin_instagram_username="admin_test",
    )

    assert isinstance(result, VerificationSuccess) and result.user_id == user_id
    updated = await profile_repo.get_by_user_id(user_id)
    assert updated is not None
    assert updated.confirmed is True


@pytest.mark.asyncio
async def test_generate_code_with_transaction_manager(fake_tm: object) -> None:
    """Cover transaction_manager path for generate_code."""

    user_repo = InMemoryUserRepository()
    user_id = await _seed_user(user_repo)
    profile_repo = InMemoryBloggerProfileRepository()
    await _seed_profile(profile_repo, user_id)
    verification_repo = InMemoryInstagramVerificationRepository()
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
        transaction_manager=fake_tm,
    )
    verification = await service.generate_code(user_id)
    assert verification.user_id == user_id
    assert verification.code is not None


@pytest.mark.asyncio
async def test_verify_code_with_transaction_manager(fake_tm: object) -> None:
    """Cover transaction_manager path for verify_code (get profile and save)."""

    user_repo = InMemoryUserRepository()
    user_id = await _seed_user(user_repo)
    profile_repo = InMemoryBloggerProfileRepository()
    await _seed_profile(profile_repo, user_id)
    verification_repo = InMemoryInstagramVerificationRepository()
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
        transaction_manager=fake_tm,
    )
    verification = await service.generate_code(user_id)
    result = await service.verify_code(user_id, verification.code)
    assert result is True
    profile = await profile_repo.get_by_user_id(user_id)
    assert profile is not None and profile.confirmed is True


@pytest.mark.asyncio
async def test_mark_used_nonexistent_code_no_op() -> None:
    """mark_used with nonexistent code_id returns without error (no-op)."""

    verification_repo = InMemoryInstagramVerificationRepository()
    await verification_repo.mark_used(
        UUID("00000000-0000-0000-0000-000000000999")
    )
    assert len(verification_repo.codes) == 0


@pytest.mark.asyncio
async def test_get_notification_recipient_with_transaction_manager(
    fake_tm: object,
) -> None:
    """get_notification_recipient with tm returns user and profile."""

    user_repo = InMemoryUserRepository()
    user_id = await _seed_user(user_repo)
    profile_repo = InMemoryBloggerProfileRepository()
    await _seed_profile(profile_repo, user_id)
    verification_repo = InMemoryInstagramVerificationRepository()
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
        transaction_manager=fake_tm,
    )
    user, profile = await service.get_notification_recipient(user_id)
    assert user is not None
    assert profile is not None
    assert user.user_id == user_id
    assert profile.user_id == user_id


@pytest.mark.asyncio
async def test_get_notification_recipient_user_none_with_transaction_manager(
    fake_tm: object,
) -> None:
    """get_notification_recipient returns (None, None) when user missing."""

    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
        transaction_manager=fake_tm,
    )
    user, profile = await service.get_notification_recipient(
        UUID("00000000-0000-0000-0000-000000000999")
    )
    assert user is None
    assert profile is None


@pytest.mark.asyncio
async def test_generate_code_user_not_found_with_transaction_manager(
    fake_tm: object,
) -> None:
    """generate_code raises UserNotFoundError when user missing, tm used."""

    service = InstagramVerificationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
        transaction_manager=fake_tm,
    )
    with pytest.raises(UserNotFoundError):
        await service.generate_code(
            UUID("00000000-0000-0000-0000-000000000999")
        )


@pytest.mark.asyncio
async def test_verify_code_profile_not_found_with_transaction_manager(
    fake_tm: object,
) -> None:
    """verify_code raises BloggerRegistrationError when profile missing."""

    user_repo = InMemoryUserRepository()
    user_id = await _seed_user(user_repo)
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
        transaction_manager=fake_tm,
    )
    with pytest.raises(BloggerRegistrationError):
        await service.verify_code(user_id, "ABC123")


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_with_transaction_manager(
    fake_tm: object,
) -> None:
    """verify_code_by_instagram_sender succeeds with transaction_manager."""

    user_repo = InMemoryUserRepository()
    user_id = await _seed_user(user_repo)
    profile_repo = InMemoryBloggerProfileRepository()
    await _seed_profile(profile_repo, user_id)
    verification_repo = InMemoryInstagramVerificationRepository()
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
        transaction_manager=fake_tm,
    )
    verification = await service.generate_code(user_id)
    result = await service.verify_code_by_instagram_sender(
        instagram_sender_id="instagram_123",
        code=verification.code,
        admin_instagram_username="admin_test",
    )
    assert isinstance(result, VerificationSuccess) and result.user_id == user_id
    updated = await profile_repo.get_by_user_id(user_id)
    assert updated is not None
    assert updated.confirmed is True


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_link_success() -> None:
    """verify_code_by_instagram_sender returns VerificationLinkSuccess."""
    user_repo = InMemoryUserRepository()
    user_id = await _seed_user(user_repo)
    profile_repo = InMemoryBloggerProfileRepository()
    await _seed_profile(profile_repo, user_id)
    verification_repo = InMemoryInstagramVerificationRepository()
    user_role_service = UserRoleService(
        user_repo=user_repo,
        blogger_profile_repo=profile_repo,
    )
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
        user_role_service=user_role_service,
    )
    verification = await service.generate_code(
        user_id,
        link_max_id="max_sender_42",
        link_max_chat_id="max_chat_42",
        link_username="maxuser",
    )
    result = await service.verify_code_by_instagram_sender(
        instagram_sender_id="instagram_123",
        code=verification.code,
        admin_instagram_username="admin_test",
    )
    assert isinstance(result, VerificationLinkSuccess)
    assert result.user_id == user_id
    assert result.linked_user_id == user_id
    linked_user = await user_repo.get_by_id(user_id)
    assert linked_user is not None
    assert linked_user.max_id == "max_sender_42"
    assert linked_user.max_chat_id == "max_chat_42"


@pytest.mark.asyncio
async def test_verify_code_link_success() -> None:
    """verify_code returns VerificationLinkSuccess."""
    user_repo = InMemoryUserRepository()
    user_id = await _seed_user(user_repo)
    profile_repo = InMemoryBloggerProfileRepository()
    await _seed_profile(profile_repo, user_id)
    verification_repo = InMemoryInstagramVerificationRepository()
    user_role_service = UserRoleService(
        user_repo=user_repo,
        blogger_profile_repo=profile_repo,
    )
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
        user_role_service=user_role_service,
    )
    verification = await service.generate_code(
        user_id,
        link_max_id="max_link_1",
        link_max_chat_id="max_chat_1",
        link_username="maxuser",
    )
    result = await service.verify_code(user_id, verification.code)
    assert isinstance(result, VerificationLinkSuccess)
    assert result.user_id == user_id


@pytest.mark.asyncio
async def test_try_link_no_user_role_service() -> None:
    """_try_link returns None when no user_role_service."""
    user_repo = InMemoryUserRepository()
    user_id = await _seed_user(user_repo)
    profile_repo = InMemoryBloggerProfileRepository()
    await _seed_profile(profile_repo, user_id)
    verification_repo = InMemoryInstagramVerificationRepository()
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
    )
    verification = await service.generate_code(
        user_id,
        link_max_id="max_link_1",
        link_max_chat_id="max_chat_1",
        link_username="maxuser",
    )
    result = await service.verify_code(user_id, verification.code)
    assert result is True


@pytest.mark.asyncio
async def test_try_link_returns_none_when_link_fails() -> None:
    """_try_link returns None when user has different max_id."""
    user_repo = InMemoryUserRepository()
    user_id = await _seed_user(user_repo)
    user = await user_repo.get_by_id(user_id)
    assert user is not None
    from dataclasses import replace as dc_replace

    updated = dc_replace(user, max_id="other_max_id")
    await user_repo.save(updated)

    profile_repo = InMemoryBloggerProfileRepository()
    await _seed_profile(profile_repo, user_id)
    verification_repo = InMemoryInstagramVerificationRepository()
    user_role_service = UserRoleService(
        user_repo=user_repo,
        blogger_profile_repo=profile_repo,
    )
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
        user_role_service=user_role_service,
    )
    verification = await service.generate_code(
        user_id,
        link_max_id="new_max_id",
        link_max_chat_id="chat",
        link_username="maxuser",
    )
    result = await service.verify_code(user_id, verification.code)
    assert result is True

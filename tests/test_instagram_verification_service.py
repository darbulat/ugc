"""Tests for Instagram verification service."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from ugc_bot.application.errors import UserNotFoundError
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.domain.entities import BloggerProfile, InstagramVerificationCode, User
from ugc_bot.domain.enums import AudienceGender, MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryInstagramGraphApiClient,
    InMemoryInstagramVerificationRepository,
    InMemoryUserRepository,
)


def _seed_user(user_repo: InMemoryUserRepository) -> UUID:
    """Seed a user in memory."""

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000130"),
        external_id="999",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    return user.user_id


def _seed_profile(
    repo: InMemoryBloggerProfileRepository,
    user_id: UUID,
    user_repo: InMemoryUserRepository | None = None,
) -> None:
    """Seed a blogger profile in memory and update user with instagram_url."""

    repo.save(
        BloggerProfile(
            user_id=user_id,
            instagram_url="https://instagram.com/test_user",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1500.0,
            updated_at=datetime.now(timezone.utc),
        )
    )

    # Update user with instagram_url if user_repo is provided
    if user_repo:
        user = user_repo.get_by_id(user_id)
        if user:
            updated_user = User(
                user_id=user.user_id,
                external_id=user.external_id,
                messenger_type=user.messenger_type,
                username=user.username,
                status=user.status,
                issue_count=user.issue_count,
                created_at=user.created_at,
                instagram_url="https://instagram.com/test_user",
                confirmed=False,
            )
            user_repo.save(updated_user)


def test_generate_code_requires_user() -> None:
    """Fail when user is missing."""

    service = InstagramVerificationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
    )

    with pytest.raises(UserNotFoundError):
        service.generate_code(UUID("00000000-0000-0000-0000-000000000131"))


def test_verify_code_requires_instagram_url() -> None:
    """Fail when user has no Instagram URL."""

    user_repo = InMemoryUserRepository()
    user_id = _seed_user(user_repo)
    # User has no instagram_url
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
    )

    with pytest.raises(UserNotFoundError):
        service.verify_code(user_id, "ABC123")


def test_verify_code_success() -> None:
    """Verify code and confirm profile."""

    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = _seed_user(user_repo)
    _seed_profile(profile_repo, user_id, user_repo=user_repo)

    code = InstagramVerificationCode(
        code_id=UUID("00000000-0000-0000-0000-000000000132"),
        user_id=user_id,
        code="ABC123",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        used=False,
        created_at=datetime.now(timezone.utc),
    )
    verification_repo.save(code)

    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
    )

    assert service.verify_code(user_id, "ABC123") is True
    # Check user confirmed status
    updated_user = user_repo.get_by_id(user_id)
    assert updated_user is not None
    assert updated_user.confirmed is True


def test_verify_code_invalid() -> None:
    """Return false for invalid code."""

    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = _seed_user(user_repo)
    _seed_profile(profile_repo, user_id, user_repo=user_repo)

    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
    )

    assert service.verify_code(user_id, "WRONG") is False


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_success() -> None:
    """Test successful verification via Instagram webhook."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = _seed_user(user_repo)
    _seed_profile(profile_repo, user_id, user_repo=user_repo)

    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
    )

    # Generate code
    verification = service.generate_code(user_id)

    # Verify via Instagram sender
    result = await service.verify_code_by_instagram_sender(
        instagram_sender_id="instagram_user_123",
        code=verification.code,
        admin_instagram_username="admin_test",
    )

    assert result == user_id
    # Check user confirmed status
    updated_user = user_repo.get_by_id(user_id)
    assert updated_user is not None
    assert updated_user.confirmed is True


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_invalid_code() -> None:
    """Test verification with invalid code."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = _seed_user(user_repo)
    _seed_profile(profile_repo, user_id, user_repo=user_repo)

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
    # Check user confirmed status (should remain False)
    updated_user = user_repo.get_by_id(user_id)
    assert updated_user is not None
    assert updated_user.confirmed is False


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_expired_code() -> None:
    """Test verification with expired code."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = _seed_user(user_repo)
    _seed_profile(profile_repo, user_id, user_repo=user_repo)

    # Create expired code
    expired_code = InstagramVerificationCode(
        code_id=UUID("00000000-0000-0000-0000-000000000133"),
        user_id=user_id,
        code="EXPIRED",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        used=False,
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    verification_repo.save(expired_code)

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
    user_id = _seed_user(user_repo)
    # Don't create profile

    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
    )

    # Generate code
    verification = service.generate_code(user_id)

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
    user_id = _seed_user(user_repo)
    _seed_profile(profile_repo, user_id, user_repo=user_repo)

    # Create used code
    used_code = InstagramVerificationCode(
        code_id=UUID("00000000-0000-0000-0000-000000000134"),
        user_id=user_id,
        code="USED123",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        used=True,
        created_at=datetime.now(timezone.utc),
    )
    verification_repo.save(used_code)

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
async def test_verify_code_by_instagram_sender_extracts_username_from_url() -> None:
    """Test that username is correctly extracted from Instagram URL."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = _seed_user(user_repo)

    # Create profile with different URL formats
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/test_user",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        updated_at=datetime.now(timezone.utc),
    )
    profile_repo.save(profile)
    # Update user with instagram_url
    _seed_profile(profile_repo, user_id, user_repo=user_repo)

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

    verification = service.generate_code(user_id)

    result = await service.verify_code_by_instagram_sender(
        instagram_sender_id="instagram_user_123",
        code=verification.code,
        admin_instagram_username="admin_test",
    )

    assert result == user_id
    assert user_repo.get_by_id(user_id).confirmed is True


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_username_extraction_variants() -> None:
    """Test username extraction from different Instagram URL formats."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = _seed_user(user_repo)

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
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        )
        profile_repo.save(profile)
        # Update user with instagram_url
        user = user_repo.get_by_id(user_id)
        if user:
            updated_user = User(
                user_id=user.user_id,
                external_id=user.external_id,
                messenger_type=user.messenger_type,
                username=user.username,
                status=user.status,
                issue_count=user.issue_count,
                created_at=user.created_at,
                instagram_url=url_format,
                confirmed=False,
            )
            user_repo.save(updated_user)

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

        verification = service.generate_code(user_id)

        result = await service.verify_code_by_instagram_sender(
            instagram_sender_id="instagram_user_123",
            code=verification.code,
            admin_instagram_username="admin_test",
        )

        assert result == user_id
        assert user_repo.get_by_id(user_id).confirmed is True

        # Reset for next iteration
        profile_repo.save(
            BloggerProfile(
                user_id=user_id,
                instagram_url=url_format,
                topics={"selected": ["fitness"]},
                audience_gender=AudienceGender.ALL,
                audience_age_min=18,
                audience_age_max=35,
                audience_geo="Moscow",
                price=1000.0,
                updated_at=datetime.now(timezone.utc),
            )
        )
        # Reset user confirmed status
        user = user_repo.get_by_id(user_id)
        if user:
            reset_user = User(
                user_id=user.user_id,
                external_id=user.external_id,
                messenger_type=user.messenger_type,
                username=user.username,
                status=user.status,
                issue_count=user.issue_count,
                created_at=user.created_at,
                instagram_url=url_format,
                confirmed=False,
            )
            user_repo.save(reset_user)


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_username_mismatch() -> None:
    """Test verification fails when username from API doesn't match profile."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = _seed_user(user_repo)

    # Create profile with specific username
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/test_user",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        updated_at=datetime.now(timezone.utc),
    )
    profile_repo.save(profile)
    # Update user with instagram_url
    _seed_profile(profile_repo, user_id, user_repo=user_repo)

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

    verification = service.generate_code(user_id)

    result = await service.verify_code_by_instagram_sender(
        instagram_sender_id="instagram_user_123",
        code=verification.code,
        admin_instagram_username="admin_test",
    )

    assert result is None
    assert user_repo.get_by_id(user_id).confirmed is False


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_api_exception() -> None:
    """Test verification handles API exceptions gracefully."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = _seed_user(user_repo)

    # Create profile
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/test_user",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        updated_at=datetime.now(timezone.utc),
    )
    profile_repo.save(profile)
    # Update user with instagram_url
    _seed_profile(profile_repo, user_id, user_repo=user_repo)

    # Create API client that raises an exception
    class FailingInstagramGraphApiClient(InMemoryInstagramGraphApiClient):
        async def get_username_by_id(self, instagram_user_id: str) -> str | None:
            raise Exception("API error")

    api_client = FailingInstagramGraphApiClient()

    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
        instagram_api_client=api_client,
    )

    verification = service.generate_code(user_id)

    # Should still succeed even if API fails (fallback behavior)
    result = await service.verify_code_by_instagram_sender(
        instagram_sender_id="instagram_user_123",
        code=verification.code,
        admin_instagram_username="admin_test",
    )

    assert result == user_id
    assert user_repo.get_by_id(user_id).confirmed is True


@pytest.mark.asyncio
async def test_verify_code_by_instagram_sender_url_parsing_edge_case() -> None:
    """Test username extraction handles edge case where URL doesn't contain username."""
    user_repo = InMemoryUserRepository()
    profile_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_id = _seed_user(user_repo)

    # Create profile with URL that doesn't match expected pattern
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com",  # No username in URL
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        updated_at=datetime.now(timezone.utc),
    )
    profile_repo.save(profile)
    # Update user with instagram_url
    user = user_repo.get_by_id(user_id)
    if user:
        updated_user = User(
            user_id=user.user_id,
            external_id=user.external_id,
            messenger_type=user.messenger_type,
            username=user.username,
            status=user.status,
            issue_count=user.issue_count,
            created_at=user.created_at,
            instagram_url="https://instagram.com",
            confirmed=False,
        )
        user_repo.save(updated_user)

    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=profile_repo,
        verification_repo=verification_repo,
    )

    verification = service.generate_code(user_id)

    # Should still succeed (no API client, so no username verification)
    result = await service.verify_code_by_instagram_sender(
        instagram_sender_id="instagram_user_123",
        code=verification.code,
        admin_instagram_username="admin_test",
    )

    assert result == user_id
    assert user_repo.get_by_id(user_id).confirmed is True

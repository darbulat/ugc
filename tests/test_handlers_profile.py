"""Tests for profile handler."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.bot.handlers.profile import show_profile
from ugc_bot.domain.entities import AdvertiserProfile, BloggerProfile, User
from ugc_bot.domain.enums import AudienceGender, MessengerType, UserStatus


class FakeUser:
    """Minimal user stub."""

    def __init__(self, user_id: int) -> None:
        self.id = user_id


class FakeMessage:
    """Minimal message stub."""

    def __init__(self) -> None:
        self.from_user = FakeUser(1)
        self.answers: list[str] = []

    async def answer(self, text: str, reply_markup=None) -> None:  # type: ignore[no-untyped-def]
        """Capture response."""

        self.answers.append(text)


class FakeProfileService:
    """Stub profile service."""

    def __init__(self, user: User, has_blogger: bool, has_advertiser: bool) -> None:
        self._user = user
        self._has_blogger = has_blogger
        self._has_advertiser = has_advertiser

    def get_user_by_external(self, external_id, messenger_type):  # type: ignore[no-untyped-def]
        return self._user

    def get_blogger_profile(self, user_id):  # type: ignore[no-untyped-def]
        if not self._has_blogger:
            return None
        return BloggerProfile(
            user_id=user_id,
            instagram_url="https://instagram.com/test",
            confirmed=True,
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        )

    def get_advertiser_profile(self, user_id):  # type: ignore[no-untyped-def]
        if not self._has_advertiser:
            return None
        return AdvertiserProfile(user_id=user_id, contact="contact")


@pytest.mark.asyncio
async def test_show_profile_both_roles() -> None:
    """Show both roles in profile output."""

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000810"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    message = FakeMessage()
    service = FakeProfileService(user=user, has_blogger=True, has_advertiser=True)

    await show_profile(message, service)

    assert message.answers
    assert "Roles: blogger, advertiser" in message.answers[0]


@pytest.mark.asyncio
async def test_show_profile_missing_user() -> None:
    """Notify when user is missing."""

    class MissingProfileService:
        def get_user_by_external(self, external_id, messenger_type):  # type: ignore[no-untyped-def]
            return None

    message = FakeMessage()
    await show_profile(message, MissingProfileService())

    assert message.answers
    assert "Профиль не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_show_profile_missing_profiles() -> None:
    """Show hints when role profiles are missing."""

    class PartialProfileService:
        def get_user_by_external(self, external_id, messenger_type):  # type: ignore[no-untyped-def]
            return User(
                user_id=UUID("00000000-0000-0000-0000-000000000811"),
                external_id="2",
                messenger_type=MessengerType.TELEGRAM,
                username="user",
                status=UserStatus.ACTIVE,
                issue_count=0,
                created_at=datetime.now(timezone.utc),
            )

        def get_blogger_profile(self, user_id):  # type: ignore[no-untyped-def]
            return None

        def get_advertiser_profile(self, user_id):  # type: ignore[no-untyped-def]
            return None

    message = FakeMessage()
    await show_profile(message, PartialProfileService())

    assert message.answers
    assert "Профиль блогера не заполнен" in message.answers[0]
    assert "Профиль рекламодателя не заполнен" in message.answers[0]

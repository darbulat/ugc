"""Tests for profile handler."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.bot.handlers.profile import show_profile
from ugc_bot.domain.entities import AdvertiserProfile, BloggerProfile, User
from ugc_bot.domain.enums import AudienceGender
from tests.helpers.fakes import FakeMessage, FakeUser
from tests.helpers.factories import create_test_user


class FakeProfileService:
    """Stub profile service."""

    def __init__(
        self,
        user: User,
        has_blogger: bool,
        has_advertiser: bool,
        blogger_confirmed: bool = True,
    ) -> None:
        self._user = user
        self._has_blogger = has_blogger
        self._has_advertiser = has_advertiser
        self._blogger_confirmed = blogger_confirmed

    async def get_user_by_external(self, external_id, messenger_type):  # type: ignore[no-untyped-def]
        return self._user

    async def get_blogger_profile(self, user_id):  # type: ignore[no-untyped-def]
        if not self._has_blogger:
            return None
        return BloggerProfile(
            user_id=user_id,
            instagram_url="https://instagram.com/test",
            confirmed=self._blogger_confirmed,
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        )

    async def get_advertiser_profile(self, user_id):  # type: ignore[no-untyped-def]
        if not self._has_advertiser:
            return None
        return AdvertiserProfile(user_id=user_id, contact="contact")


@pytest.mark.asyncio
async def test_show_profile_both_roles(user_repo) -> None:
    """Show both roles in profile output."""

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000810"),
        external_id="1",
        username="user",
    )
    message = FakeMessage(user=FakeUser(1))
    service = FakeProfileService(user=user, has_blogger=True, has_advertiser=True)

    await show_profile(message, service)

    assert message.answers
    answer_text = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert "Roles: blogger, advertiser" in answer_text


@pytest.mark.asyncio
async def test_show_profile_missing_user() -> None:
    """Notify when user is missing."""

    class MissingProfileService:
        async def get_user_by_external(self, external_id, messenger_type):  # type: ignore[no-untyped-def]
            return None

    message = FakeMessage(user=FakeUser(1))
    await show_profile(message, MissingProfileService())

    assert message.answers
    assert "Профиль не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_show_profile_missing_profiles(user_repo) -> None:
    """Show hints when role profiles are missing."""

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000811"),
        external_id="2",
        username="user",
    )

    class PartialProfileService:
        async def get_user_by_external(self, external_id, messenger_type):  # type: ignore[no-untyped-def]
            return user

        async def get_blogger_profile(self, user_id):  # type: ignore[no-untyped-def]
            return None

        async def get_advertiser_profile(self, user_id):  # type: ignore[no-untyped-def]
            return None

    message = FakeMessage(user=FakeUser(2))
    await show_profile(message, PartialProfileService())

    assert message.answers
    assert "Профиль блогера не заполнен" in message.answers[0]
    assert "Профиль рекламодателя не заполнен" in message.answers[0]


@pytest.mark.asyncio
async def test_show_profile_blogger_keyboard_not_confirmed(user_repo) -> None:
    """Show verification button for unconfirmed blogger."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000812"),
        external_id="3",
        username="blogger",
    )
    message = FakeMessage(user=FakeUser(3))
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False, blogger_confirmed=False
    )

    await show_profile(message, service)

    assert message.reply_markups
    keyboard = message.reply_markups[0]
    assert keyboard.keyboard is not None
    assert len(keyboard.keyboard) == 2
    assert keyboard.keyboard[0][0].text == "Пройти верификацию"
    assert keyboard.keyboard[1][0].text == "Мой профиль"


@pytest.mark.asyncio
async def test_show_profile_blogger_keyboard_confirmed(user_repo) -> None:
    """Hide verification button for confirmed blogger."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000813"),
        external_id="4",
        username="blogger",
    )
    message = FakeMessage(user=FakeUser(4))
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False, blogger_confirmed=True
    )

    await show_profile(message, service)

    assert message.reply_markups
    keyboard = message.reply_markups[0]
    assert keyboard.keyboard is not None
    assert len(keyboard.keyboard) == 1
    assert keyboard.keyboard[0][0].text == "Мой профиль"


@pytest.mark.asyncio
async def test_show_profile_advertiser_keyboard(user_repo) -> None:
    """Show advertiser keyboard for advertiser."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000814"),
        external_id="5",
        username="advertiser",
    )
    message = FakeMessage(user=FakeUser(5))
    service = FakeProfileService(user=user, has_blogger=False, has_advertiser=True)

    await show_profile(message, service)

    assert message.reply_markups
    keyboard = message.reply_markups[0]
    assert keyboard.keyboard is not None
    assert any(btn.text == "Мой профиль" for row in keyboard.keyboard for btn in row)

"""Tests for InstagramStatsUpdateService."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ugc_bot.application.errors import InstagramUserNotFoundError
from ugc_bot.application.ports import InstagramProfileInfo
from ugc_bot.application.services.instagram_stats_update_service import (
    InstagramStatsUpdateService,
)
from ugc_bot.domain.entities import BloggerProfile, User
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    UserStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryInstagramGraphApiClient,
    InMemoryUserRepository,
)


def _make_profile(
    user_id=None, confirmed=True, instagram_user_id="ig_123"
) -> BloggerProfile:
    return BloggerProfile(
        user_id=user_id or uuid4(),
        instagram_url="https://instagram.com/test",
        confirmed=confirmed,
        city="Moscow",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="RU",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
        instagram_user_id=instagram_user_id,
    )


def _make_user(user_id, telegram_id="12345", language="ru") -> User:
    return User(
        user_id=user_id,
        messenger_type=MessengerType.TELEGRAM,
        username="testuser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        telegram_id=telegram_id,
        language=language,
    )


class _RaisingGraphApiClient(InMemoryInstagramGraphApiClient):
    """Graph API client that raises InstagramUserNotFoundError for given IDs."""

    def __init__(self, not_found_ids: set[str] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._not_found_ids = not_found_ids or set()

    async def get_profile_by_id(self, instagram_user_id: str):
        if instagram_user_id in self._not_found_ids:
            raise InstagramUserNotFoundError(instagram_user_id)
        return await super().get_profile_by_id(instagram_user_id)


@pytest.mark.asyncio
async def test_unconfirms_blogger_on_instagram_user_not_found() -> None:
    """Service sets confirmed=False when API returns 9010."""
    uid = uuid4()
    profile = _make_profile(user_id=uid, instagram_user_id="ig_gone")
    user = _make_user(uid, telegram_id="999")

    blogger_repo = InMemoryBloggerProfileRepository()
    await blogger_repo.save(profile)

    user_repo = InMemoryUserRepository()
    await user_repo.save(user)

    ig_client = _RaisingGraphApiClient(not_found_ids={"ig_gone"})
    messenger = MagicMock()
    messenger.send_text = AsyncMock()

    bot_texts = MagicMock()
    bot_texts.get = AsyncMock(return_value="Your Instagram was deleted.")

    service = InstagramStatsUpdateService(
        blogger_repo=blogger_repo,
        instagram_api_client=ig_client,
        batch_size=10,
        delay_seconds=0,
        user_repo=user_repo,
        messenger_client=messenger,
        bot_texts_service=bot_texts,
    )

    updated, errors = await service.run_once()

    # Profile should be unconfirmed
    saved = await blogger_repo.get_by_user_id(uid)
    assert saved is not None
    assert saved.confirmed is False

    # Notification sent to user's telegram_id
    messenger.send_text.assert_called_once()
    call_kwargs = messenger.send_text.call_args
    assert call_kwargs.kwargs["chat_id"] == "999"

    # Counted as error
    assert errors == 1
    assert updated == 0


@pytest.mark.asyncio
async def test_unconfirms_but_no_notification_when_no_user_repo() -> None:
    """Without user_repo, blogger is unconfirmed but no notification sent."""
    uid = uuid4()
    profile = _make_profile(user_id=uid, instagram_user_id="ig_gone")

    blogger_repo = InMemoryBloggerProfileRepository()
    await blogger_repo.save(profile)

    ig_client = _RaisingGraphApiClient(not_found_ids={"ig_gone"})

    service = InstagramStatsUpdateService(
        blogger_repo=blogger_repo,
        instagram_api_client=ig_client,
        batch_size=10,
        delay_seconds=0,
    )

    updated, errors = await service.run_once()

    # Profile should still be unconfirmed
    saved = await blogger_repo.get_by_user_id(uid)
    assert saved is not None
    assert saved.confirmed is False
    assert errors == 1


@pytest.mark.asyncio
async def test_normal_update_still_works() -> None:
    """Normal stats update path is not broken."""
    uid = uuid4()
    profile = _make_profile(user_id=uid, instagram_user_id="ig_ok")

    blogger_repo = InMemoryBloggerProfileRepository()
    await blogger_repo.save(profile)

    ig_client = InMemoryInstagramGraphApiClient(
        profile_map={
            "ig_ok": InstagramProfileInfo(
                username="testuser", followers_count=500
            )
        }
    )

    service = InstagramStatsUpdateService(
        blogger_repo=blogger_repo,
        instagram_api_client=ig_client,
        batch_size=10,
        delay_seconds=0,
    )

    updated, errors = await service.run_once()
    assert updated == 1
    assert errors == 0

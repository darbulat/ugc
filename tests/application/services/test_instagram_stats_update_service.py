"""Tests for Instagram stats update service."""

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


@pytest.mark.asyncio
async def test_run_once_no_client_returns_zero() -> None:
    """run_once returns (0, 0) when API client is None."""
    repo = InMemoryBloggerProfileRepository()
    service = InstagramStatsUpdateService(
        blogger_repo=repo,
        instagram_api_client=None,
    )
    updated, errors = await service.run_once()
    assert updated == 0
    assert errors == 0


@pytest.mark.asyncio
async def test_run_once_empty_list_returns_zero() -> None:
    """run_once returns (0, 0) when no profiles have instagram_user_id."""
    repo = InMemoryBloggerProfileRepository()
    client = InMemoryInstagramGraphApiClient()
    service = InstagramStatsUpdateService(
        blogger_repo=repo,
        instagram_api_client=client,
    )
    updated, errors = await service.run_once()
    assert updated == 0
    assert errors == 0


@pytest.mark.asyncio
async def test_run_once_updates_profile_stats() -> None:
    """run_once fetches API and updates profile with new stats."""
    user_id = uuid4()
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/jane",
        confirmed=True,
        city="Moscow",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="",
        price=100.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
        instagram_user_id="ig_123",
    )
    repo = InMemoryBloggerProfileRepository()
    await repo.save(profile)

    api_profile = InstagramProfileInfo(
        username="jane",
        followers_count=2000,
        media_count=100,
        follows_count=300,
    )
    client = InMemoryInstagramGraphApiClient(
        profile_map={"ig_123": api_profile},
    )
    service = InstagramStatsUpdateService(
        blogger_repo=repo,
        instagram_api_client=client,
        batch_size=10,
        delay_seconds=0.0,
    )

    updated, errors = await service.run_once()
    assert updated == 1
    assert errors == 0

    saved = await repo.get_by_user_id(user_id)
    assert saved is not None
    assert saved.instagram_followers_count == 2000
    assert saved.instagram_username == "jane"
    assert saved.instagram_stats_fetched_at is not None
    assert saved.instagram_url == "https://instagram.com/jane"


@pytest.mark.asyncio
async def test_run_once_updates_instagram_url_from_username() -> None:
    """When API returns username, instagram_url is set to canonical URL."""
    user_id = uuid4()
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/old_nickname",
        confirmed=True,
        city="Moscow",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="",
        price=100.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
        instagram_user_id="ig_456",
    )
    repo = InMemoryBloggerProfileRepository()
    await repo.save(profile)

    api_profile = InstagramProfileInfo(
        username="canonical_handle",
        followers_count=5000,
        media_count=200,
        follows_count=100,
    )
    client = InMemoryInstagramGraphApiClient(
        profile_map={"ig_456": api_profile},
    )
    service = InstagramStatsUpdateService(
        blogger_repo=repo,
        instagram_api_client=client,
        batch_size=10,
        delay_seconds=0.0,
    )

    updated, errors = await service.run_once()
    assert updated == 1
    assert errors == 0

    saved = await repo.get_by_user_id(user_id)
    assert saved is not None
    assert saved.instagram_url == "https://instagram.com/canonical_handle"
    assert saved.instagram_username == "canonical_handle"


@pytest.mark.asyncio
async def test_run_once_increments_errors_when_api_returns_none() -> None:
    """run_once counts errors when get_profile_by_id returns None."""
    user_id = uuid4()
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/jane",
        confirmed=True,
        city="Moscow",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="",
        price=100.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
        instagram_user_id="ig_unknown",
    )
    repo = InMemoryBloggerProfileRepository()
    await repo.save(profile)
    client = InMemoryInstagramGraphApiClient()
    service = InstagramStatsUpdateService(
        blogger_repo=repo,
        instagram_api_client=client,
        delay_seconds=0.0,
    )
    updated, errors = await service.run_once()
    assert updated == 0
    assert errors == 1


@pytest.mark.asyncio
async def test_run_once_preserves_location_geometry() -> None:
    """run_once does not overwrite location_geometry when updating stats."""
    user_id = uuid4()
    geometry_wkt = "MULTIPOINT((37.6 55.75))"
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/jane",
        confirmed=True,
        city="Moscow",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="",
        price=100.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
        instagram_user_id="ig_123",
        location_geometry=geometry_wkt,
    )
    repo = InMemoryBloggerProfileRepository()
    await repo.save(profile)

    api_profile = InstagramProfileInfo(
        username="jane",
        followers_count=2000,
        media_count=100,
        follows_count=300,
    )
    client = InMemoryInstagramGraphApiClient(
        profile_map={"ig_123": api_profile},
    )
    service = InstagramStatsUpdateService(
        blogger_repo=repo,
        instagram_api_client=client,
        batch_size=10,
        delay_seconds=0.0,
    )

    updated, errors = await service.run_once()
    assert updated == 1
    assert errors == 0

    saved = await repo.get_by_user_id(user_id)
    assert saved is not None
    assert saved.location_geometry == geometry_wkt
    assert saved.instagram_followers_count == 2000


@pytest.mark.asyncio
async def test_run_once_handles_api_exception() -> None:
    """run_once logs and counts error when get_profile_by_id raises."""
    user_id = uuid4()
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/jane",
        confirmed=True,
        city="Moscow",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="",
        price=100.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
        instagram_user_id="ig_123",
    )
    repo = InMemoryBloggerProfileRepository()
    await repo.save(profile)

    class RaisingClient(InMemoryInstagramGraphApiClient):
        async def get_profile_by_id(self, instagram_user_id: str):
            raise ValueError("API error")

    service = InstagramStatsUpdateService(
        blogger_repo=repo,
        instagram_api_client=RaisingClient(),
        delay_seconds=0.0,
    )
    updated, errors = await service.run_once()
    assert updated == 0
    assert errors == 1


# --- Instagram user not found (9010) tests ---


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


def _make_user(
    user_id,
    telegram_id: str | None = "12345",
    language="ru",
    max_id: str | None = None,
) -> User:
    return User(
        user_id=user_id,
        messenger_type=MessengerType.TELEGRAM,
        username="testuser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        telegram_id=telegram_id,
        max_id=max_id,
        language=language,
    )


class _GeometryInjectingRepo(InMemoryBloggerProfileRepository):
    """Returns profiles without geometry from list, with geometry from get."""

    def __init__(self, geometry: str) -> None:
        super().__init__()
        self._geometry = geometry

    async def list_confirmed_with_instagram_id(  # type: ignore[override]
        self,
        limit=50,
        offset=0,
        stats_older_than=None,
        session=None,
    ):
        profiles = await super().list_confirmed_with_instagram_id(
            limit=limit,
            offset=offset,
            stats_older_than=stats_older_than,
            session=session,
        )
        from dataclasses import replace as _replace

        return [_replace(p, location_geometry=None) for p in profiles]

    async def get_by_user_id(self, user_id, session=None):
        p = await super().get_by_user_id(user_id, session=session)
        if p is not None and p.location_geometry is None:
            from dataclasses import replace as _replace

            return _replace(p, location_geometry=self._geometry)
        return p


class _NotFoundGraphApiClient(InMemoryInstagramGraphApiClient):
    """Raises InstagramUserNotFoundError for given IDs."""

    def __init__(self, not_found_ids: set[str] | None = None, **kw):
        super().__init__(**kw)
        self._not_found_ids = not_found_ids or set()

    async def get_profile_by_id(self, instagram_user_id: str):
        if instagram_user_id in self._not_found_ids:
            raise InstagramUserNotFoundError(instagram_user_id)
        return await super().get_profile_by_id(instagram_user_id)


@pytest.mark.asyncio
async def test_unconfirms_blogger_on_instagram_user_not_found() -> None:
    """Service sets confirmed=False and notifies on API error 9010."""
    uid = uuid4()
    profile = _make_profile(user_id=uid, instagram_user_id="ig_gone")
    user = _make_user(uid, telegram_id="999")

    blogger_repo = InMemoryBloggerProfileRepository()
    await blogger_repo.save(profile)

    user_repo = InMemoryUserRepository()
    await user_repo.save(user)

    ig_client = _NotFoundGraphApiClient(not_found_ids={"ig_gone"})
    messenger = MagicMock()
    messenger.send_text = AsyncMock()

    bot_texts = MagicMock()
    bot_texts.get = AsyncMock(return_value="Your IG was deleted.")

    service = InstagramStatsUpdateService(
        blogger_repo=blogger_repo,
        instagram_api_client=ig_client,
        batch_size=10,
        delay_seconds=0,
        user_repo=user_repo,
        telegram_messenger_client=messenger,
        bot_texts_service=bot_texts,
    )

    updated, errors = await service.run_once()

    saved = await blogger_repo.get_by_user_id(uid)
    assert saved is not None
    assert saved.confirmed is False

    messenger.send_text.assert_called_once()
    call_kwargs = messenger.send_text.call_args
    assert call_kwargs.kwargs["chat_id"] == "999"

    assert errors == 1
    assert updated == 0


@pytest.mark.asyncio
async def test_unconfirms_no_notification_without_user_repo() -> None:
    """Without user_repo, blogger is unconfirmed but no notification."""
    uid = uuid4()
    profile = _make_profile(user_id=uid, instagram_user_id="ig_gone")

    blogger_repo = InMemoryBloggerProfileRepository()
    await blogger_repo.save(profile)

    ig_client = _NotFoundGraphApiClient(not_found_ids={"ig_gone"})

    service = InstagramStatsUpdateService(
        blogger_repo=blogger_repo,
        instagram_api_client=ig_client,
        batch_size=10,
        delay_seconds=0,
    )

    _, errors = await service.run_once()

    saved = await blogger_repo.get_by_user_id(uid)
    assert saved is not None
    assert saved.confirmed is False
    assert errors == 1


@pytest.mark.asyncio
async def test_unconfirm_preserves_location_geometry() -> None:
    """Unconfirm preserves location_geometry from stored profile."""
    uid = uuid4()
    geometry = "MULTIPOINT((37.6 55.75))"
    profile = _make_profile(user_id=uid, instagram_user_id="ig_gone")
    # Store profile with geometry
    stored = BloggerProfile(
        user_id=uid,
        instagram_url=profile.instagram_url,
        confirmed=True,
        city=profile.city,
        topics=profile.topics,
        audience_gender=profile.audience_gender,
        audience_age_min=profile.audience_age_min,
        audience_age_max=profile.audience_age_max,
        audience_geo=profile.audience_geo,
        price=profile.price,
        barter=profile.barter,
        work_format=profile.work_format,
        updated_at=profile.updated_at,
        instagram_user_id="ig_gone",
        location_geometry=geometry,
    )

    blogger_repo = InMemoryBloggerProfileRepository()
    await blogger_repo.save(stored)

    ig_client = _NotFoundGraphApiClient(not_found_ids={"ig_gone"})

    service = InstagramStatsUpdateService(
        blogger_repo=blogger_repo,
        instagram_api_client=ig_client,
        batch_size=10,
        delay_seconds=0,
    )

    await service.run_once()

    saved = await blogger_repo.get_by_user_id(uid)
    assert saved is not None
    assert saved.confirmed is False
    assert saved.location_geometry == geometry


@pytest.mark.asyncio
async def test_unconfirm_restores_geometry_from_db() -> None:
    """Unconfirm picks up geometry from DB when entity has None."""
    uid = uuid4()
    geometry = "MULTIPOINT((37.6 55.75))"
    profile = _make_profile(user_id=uid, instagram_user_id="ig_gone")

    repo = _GeometryInjectingRepo(geometry=geometry)
    await repo.save(
        BloggerProfile(
            user_id=uid,
            instagram_url=profile.instagram_url,
            confirmed=True,
            city=profile.city,
            topics=profile.topics,
            audience_gender=profile.audience_gender,
            audience_age_min=profile.audience_age_min,
            audience_age_max=profile.audience_age_max,
            audience_geo=profile.audience_geo,
            price=profile.price,
            barter=profile.barter,
            work_format=profile.work_format,
            updated_at=profile.updated_at,
            instagram_user_id="ig_gone",
            location_geometry=geometry,
        )
    )

    ig_client = _NotFoundGraphApiClient(not_found_ids={"ig_gone"})

    service = InstagramStatsUpdateService(
        blogger_repo=repo,
        instagram_api_client=ig_client,
        batch_size=10,
        delay_seconds=0,
    )

    await service.run_once()

    saved = await repo.get_by_user_id(uid)
    assert saved is not None
    assert saved.confirmed is False
    assert saved.location_geometry == geometry


@pytest.mark.asyncio
async def test_stats_update_restores_geometry_from_db() -> None:
    """Stats update picks up geometry from DB when entity has None."""
    uid = uuid4()
    geometry = "MULTIPOINT((37.6 55.75))"
    profile = _make_profile(user_id=uid, instagram_user_id="ig_123")

    repo = _GeometryInjectingRepo(geometry=geometry)
    await repo.save(
        BloggerProfile(
            user_id=uid,
            instagram_url=profile.instagram_url,
            confirmed=True,
            city=profile.city,
            topics=profile.topics,
            audience_gender=profile.audience_gender,
            audience_age_min=profile.audience_age_min,
            audience_age_max=profile.audience_age_max,
            audience_geo=profile.audience_geo,
            price=profile.price,
            barter=profile.barter,
            work_format=profile.work_format,
            updated_at=profile.updated_at,
            instagram_user_id="ig_123",
            location_geometry=geometry,
        )
    )

    api_profile = InstagramProfileInfo(
        username="jane",
        followers_count=2000,
        media_count=100,
        follows_count=300,
    )
    ig_client = InMemoryInstagramGraphApiClient(
        profile_map={"ig_123": api_profile},
    )

    service = InstagramStatsUpdateService(
        blogger_repo=repo,
        instagram_api_client=ig_client,
        batch_size=10,
        delay_seconds=0.0,
    )

    updated, errors = await service.run_once()
    assert updated == 1
    assert errors == 0

    saved = await repo.get_by_user_id(uid)
    assert saved is not None
    assert saved.location_geometry == geometry
    assert saved.instagram_followers_count == 2000


@pytest.mark.asyncio
async def test_unconfirm_without_bot_texts_uses_fallback() -> None:
    """Without bot_texts_service, fallback Russian text is sent."""
    uid = uuid4()
    profile = _make_profile(user_id=uid, instagram_user_id="ig_gone")
    user = _make_user(uid, telegram_id="999")

    blogger_repo = InMemoryBloggerProfileRepository()
    await blogger_repo.save(profile)
    user_repo = InMemoryUserRepository()
    await user_repo.save(user)

    ig_client = _NotFoundGraphApiClient(not_found_ids={"ig_gone"})
    messenger = MagicMock()
    messenger.send_text = AsyncMock()

    service = InstagramStatsUpdateService(
        blogger_repo=blogger_repo,
        instagram_api_client=ig_client,
        batch_size=10,
        delay_seconds=0,
        user_repo=user_repo,
        telegram_messenger_client=messenger,
        bot_texts_service=None,
    )

    await service.run_once()

    messenger.send_text.assert_called_once()
    call_kwargs = messenger.send_text.call_args
    assert "удалён" in call_kwargs.kwargs["text"]


@pytest.mark.asyncio
async def test_unconfirm_no_notification_when_user_missing() -> None:
    """No notification if user not found in user_repo."""
    uid = uuid4()
    profile = _make_profile(user_id=uid, instagram_user_id="ig_gone")

    blogger_repo = InMemoryBloggerProfileRepository()
    await blogger_repo.save(profile)

    user_repo = InMemoryUserRepository()
    # user NOT added — should not crash

    ig_client = _NotFoundGraphApiClient(not_found_ids={"ig_gone"})
    messenger = MagicMock()
    messenger.send_text = AsyncMock()

    service = InstagramStatsUpdateService(
        blogger_repo=blogger_repo,
        instagram_api_client=ig_client,
        batch_size=10,
        delay_seconds=0,
        user_repo=user_repo,
        telegram_messenger_client=messenger,
    )

    _, errors = await service.run_once()

    saved = await blogger_repo.get_by_user_id(uid)
    assert saved is not None
    assert saved.confirmed is False
    messenger.send_text.assert_not_called()
    assert errors == 1


@pytest.mark.asyncio
async def test_unconfirm_messenger_error_does_not_crash() -> None:
    """Messenger send failure is logged but doesn't crash."""
    uid = uuid4()
    profile = _make_profile(user_id=uid, instagram_user_id="ig_gone")
    user = _make_user(uid, telegram_id="999")

    blogger_repo = InMemoryBloggerProfileRepository()
    await blogger_repo.save(profile)
    user_repo = InMemoryUserRepository()
    await user_repo.save(user)

    ig_client = _NotFoundGraphApiClient(not_found_ids={"ig_gone"})
    messenger = MagicMock()
    messenger.send_text = AsyncMock(side_effect=RuntimeError("send failed"))

    bot_texts = MagicMock()
    bot_texts.get = AsyncMock(return_value="")

    service = InstagramStatsUpdateService(
        blogger_repo=blogger_repo,
        instagram_api_client=ig_client,
        batch_size=10,
        delay_seconds=0,
        user_repo=user_repo,
        telegram_messenger_client=messenger,
        bot_texts_service=bot_texts,
    )

    _, errors = await service.run_once()

    saved = await blogger_repo.get_by_user_id(uid)
    assert saved is not None
    assert saved.confirmed is False
    assert errors == 1


@pytest.mark.asyncio
async def test_unconfirm_notifies_both_telegram_and_max() -> None:
    """User with both telegram_id and max_id receives notification on both."""
    uid = uuid4()
    profile = _make_profile(user_id=uid, instagram_user_id="ig_gone")
    user = _make_user(uid, telegram_id="999", max_id="max_111")

    blogger_repo = InMemoryBloggerProfileRepository()
    await blogger_repo.save(profile)
    user_repo = InMemoryUserRepository()
    await user_repo.save(user)

    ig_client = _NotFoundGraphApiClient(not_found_ids={"ig_gone"})
    tg = MagicMock()
    tg.send_text = AsyncMock()
    mx = MagicMock()
    mx.send_text = AsyncMock()
    bot_texts = MagicMock()
    bot_texts.get = AsyncMock(return_value="Your IG was deleted.")

    service = InstagramStatsUpdateService(
        blogger_repo=blogger_repo,
        instagram_api_client=ig_client,
        batch_size=10,
        delay_seconds=0,
        user_repo=user_repo,
        telegram_messenger_client=tg,
        max_messenger_client=mx,
        bot_texts_service=bot_texts,
    )

    await service.run_once()

    tg.send_text.assert_called_once()
    assert tg.send_text.call_args.kwargs["chat_id"] == "999"
    mx.send_text.assert_called_once()
    assert mx.send_text.call_args.kwargs["chat_id"] == "max_111"


@pytest.mark.asyncio
async def test_unconfirm_notifies_only_max_when_no_telegram_id() -> None:
    """User with only max_id is notified via Max only."""
    uid = uuid4()
    profile = _make_profile(user_id=uid, instagram_user_id="ig_gone")
    user = _make_user(uid, telegram_id=None, max_id="max_222")

    blogger_repo = InMemoryBloggerProfileRepository()
    await blogger_repo.save(profile)
    user_repo = InMemoryUserRepository()
    await user_repo.save(user)

    ig_client = _NotFoundGraphApiClient(not_found_ids={"ig_gone"})
    tg = MagicMock()
    tg.send_text = AsyncMock()
    mx = MagicMock()
    mx.send_text = AsyncMock()

    service = InstagramStatsUpdateService(
        blogger_repo=blogger_repo,
        instagram_api_client=ig_client,
        batch_size=10,
        delay_seconds=0,
        user_repo=user_repo,
        telegram_messenger_client=tg,
        max_messenger_client=mx,
    )

    await service.run_once()

    tg.send_text.assert_not_called()
    mx.send_text.assert_called_once()
    assert mx.send_text.call_args.kwargs["chat_id"] == "max_222"


@pytest.mark.asyncio
async def test_unconfirm_max_failure_does_not_block_telegram() -> None:
    """If Max send fails, Telegram still receives the notification."""
    uid = uuid4()
    profile = _make_profile(user_id=uid, instagram_user_id="ig_gone")
    user = _make_user(uid, telegram_id="999", max_id="max_333")

    blogger_repo = InMemoryBloggerProfileRepository()
    await blogger_repo.save(profile)
    user_repo = InMemoryUserRepository()
    await user_repo.save(user)

    ig_client = _NotFoundGraphApiClient(not_found_ids={"ig_gone"})
    tg = MagicMock()
    tg.send_text = AsyncMock()
    mx = MagicMock()
    mx.send_text = AsyncMock(side_effect=RuntimeError("max api down"))

    service = InstagramStatsUpdateService(
        blogger_repo=blogger_repo,
        instagram_api_client=ig_client,
        batch_size=10,
        delay_seconds=0,
        user_repo=user_repo,
        telegram_messenger_client=tg,
        max_messenger_client=mx,
    )

    _, errors = await service.run_once()

    saved = await blogger_repo.get_by_user_id(uid)
    assert saved is not None
    assert saved.confirmed is False
    tg.send_text.assert_called_once()
    mx.send_text.assert_called_once()
    assert errors == 1

"""Unit tests for UGC video URL feature."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from tests.helpers.fakes import FakeMessengerClient
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryOfferDispatchRepository,
)

ORDER_ID = UUID("00000000-0000-0000-0000-000000000c00")
BLOGGER_ID = UUID("00000000-0000-0000-0000-000000000c01")
ADV_ID = UUID("00000000-0000-0000-0000-000000000c02")


@pytest.mark.asyncio
async def test_get_by_order_and_blogger_returns_none_when_missing() -> None:
    repo = InMemoryOfferDispatchRepository()
    result = await repo.get_by_order_and_blogger(ORDER_ID, BLOGGER_ID)
    assert result is None


@pytest.mark.asyncio
async def test_get_by_order_and_blogger_returns_dispatch() -> None:
    repo = InMemoryOfferDispatchRepository()
    await repo.record_sent(ORDER_ID, BLOGGER_ID)
    result = await repo.get_by_order_and_blogger(ORDER_ID, BLOGGER_ID)
    assert result is not None
    assert result.order_id == ORDER_ID
    assert result.blogger_id == BLOGGER_ID
    assert result.ugc_video_url is None


@pytest.mark.asyncio
async def test_set_ugc_video_url_stores_value() -> None:
    repo = InMemoryOfferDispatchRepository()
    await repo.record_sent(ORDER_ID, BLOGGER_ID)
    await repo.set_ugc_video_url(ORDER_ID, BLOGGER_ID, "https://example.com/video")
    result = await repo.get_by_order_and_blogger(ORDER_ID, BLOGGER_ID)
    assert result is not None
    assert result.ugc_video_url == "https://example.com/video"


@pytest.mark.asyncio
async def test_set_ugc_video_url_can_update() -> None:
    repo = InMemoryOfferDispatchRepository()
    await repo.record_sent(ORDER_ID, BLOGGER_ID)
    await repo.set_ugc_video_url(ORDER_ID, BLOGGER_ID, "https://example.com/v1")
    await repo.set_ugc_video_url(ORDER_ID, BLOGGER_ID, "https://example.com/v2")
    result = await repo.get_by_order_and_blogger(ORDER_ID, BLOGGER_ID)
    assert result is not None
    assert result.ugc_video_url == "https://example.com/v2"


@pytest.mark.asyncio
async def test_set_ugc_video_url_noop_when_dispatch_missing() -> None:
    """Should not raise if dispatch does not exist."""
    repo = InMemoryOfferDispatchRepository()
    await repo.set_ugc_video_url(ORDER_ID, BLOGGER_ID, "https://example.com/v")
    result = await repo.get_by_order_and_blogger(ORDER_ID, BLOGGER_ID)
    assert result is None


@pytest.fixture
def messenger_client() -> FakeMessengerClient:
    return FakeMessengerClient()


def _make_user(user_id: UUID, external_id: str, username: str, **kwargs) -> User:
    """Helper to build a User with required fields."""
    return User(
        user_id=user_id,
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
        username=username,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_first_save_notifies_creator_and_advertiser(
    bot_texts_service,
    messenger_client: FakeMessengerClient,
) -> None:
    """On first save both creator and advertiser receive a message."""
    from ugc_bot.miniapp.api import _notify_ugc_video_saved

    creator = _make_user(
        BLOGGER_ID,
        "901",
        "creator_user",
        telegram="creator_tg",
        language="ru",
    )
    advertiser = _make_user(
        ADV_ID,
        "902",
        "advertiser_user",
        language="ru",
    )

    await _notify_ugc_video_saved(
        creator=creator,
        advertiser=advertiser,
        video_url="https://example.com/video",
        messenger_client=messenger_client,
        bot_texts_service=bot_texts_service,
    )

    creator_msgs = [s for s in messenger_client.sent_text if s["chat_id"] == "901"]
    adv_msgs = [s for s in messenger_client.sent_text if s["chat_id"] == "902"]
    assert len(creator_msgs) == 1
    assert "принято" in creator_msgs[0]["text"] or "accepted" in creator_msgs[0]["text"]
    assert len(adv_msgs) == 1
    assert "@creator_tg" in adv_msgs[0]["text"]
    assert "https://example.com/video" in adv_msgs[0]["text"]


@pytest.mark.asyncio
async def test_notify_creator_not_found_skips_creator_msg(
    bot_texts_service,
    messenger_client: FakeMessengerClient,
) -> None:
    """When creator is None only advertiser gets notified."""
    from ugc_bot.miniapp.api import _notify_ugc_video_saved

    advertiser = _make_user(
        ADV_ID,
        "902",
        "advertiser_user",
        language="ru",
    )

    await _notify_ugc_video_saved(
        creator=None,
        advertiser=advertiser,
        video_url="https://example.com/video",
        messenger_client=messenger_client,
        bot_texts_service=bot_texts_service,
    )

    assert all(s["chat_id"] != "901" for s in messenger_client.sent_text)
    adv_msgs = [s for s in messenger_client.sent_text if s["chat_id"] == "902"]
    assert len(adv_msgs) == 1


@pytest.mark.asyncio
async def test_notify_advertiser_not_found_skips_advertiser_msg(
    bot_texts_service,
    messenger_client: FakeMessengerClient,
) -> None:
    """When advertiser is None only creator gets notified."""
    from ugc_bot.miniapp.api import _notify_ugc_video_saved

    creator = _make_user(
        BLOGGER_ID,
        "901",
        "creator_user",
        telegram="creator_tg",
        language="ru",
    )

    await _notify_ugc_video_saved(
        creator=creator,
        advertiser=None,
        video_url="https://example.com/video",
        messenger_client=messenger_client,
        bot_texts_service=bot_texts_service,
    )

    assert all(s["chat_id"] != "902" for s in messenger_client.sent_text)
    creator_msgs = [s for s in messenger_client.sent_text if s["chat_id"] == "901"]
    assert len(creator_msgs) == 1

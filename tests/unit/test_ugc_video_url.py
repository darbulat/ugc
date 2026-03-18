"""Unit tests for UGC video URL feature."""

from uuid import UUID

import pytest

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

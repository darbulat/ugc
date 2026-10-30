"""Service read paths and explicit transaction ownership."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ugc_bot.application.rating_eligibility_ports import RatingParticipant
from ugc_bot.application.services.blogger_rating_service import (
    BloggerRatingService,
)
from ugc_bot.application.services.geocoder_rate_limit_store import (
    NOMINATIM_RATE_LIMIT_KEY,
    RedisGeocoderRateLimitStore,
)
from ugc_bot.application.services.manager_service import ManagerService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, RaterRole, UserStatus
from ugc_bot.infrastructure.memory_rating_eligibility import (
    InMemoryRatingEligibilityRepository,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerRatingRepository,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_session", [False, True])
async def test_rating_reads_aggregate_and_sort_without_leaking_other_bloggers(
    explicit_session,
):
    repo = InMemoryBloggerRatingRepository()
    transactions = []
    session = object()

    @asynccontextmanager
    async def transaction():
        transactions.append("begin")
        try:
            yield session
        finally:
            transactions.append("end")

    blogger_id, other, rater = uuid4(), uuid4(), uuid4()
    orders = [uuid4() for _ in range(3)]
    eligibility = InMemoryRatingEligibilityRepository(
        users={
            rater: User(
                rater,
                MessengerType.TELEGRAM,
                "Rater",
                UserStatus.ACTIVE,
                0,
                datetime.now(timezone.utc),
            )
        },
        owners={order: rater for order in orders},
        participants={
            order: (RatingParticipant(creator, "Creator", True),)
            for order, creator in zip(
                orders, (blogger_id, blogger_id, other), strict=True
            )
        },
    )
    service = BloggerRatingService(
        repo, NS(transaction=transaction), eligibility
    )
    kwargs = {"session": session} if explicit_session else {}
    assert await service.get_blogger_avg_rating(blogger_id, **kwargs) is None
    assert await service.get_blogger_ratings(blogger_id, **kwargs) == []
    first = await service.rate_blogger(
        blogger_id, orders[0], rater, RaterRole.ADMIN, 2, **kwargs
    )
    second = await service.rate_blogger(
        blogger_id, orders[1], rater, RaterRole.MANAGER, 5, **kwargs
    )
    await service.rate_blogger(
        other, orders[2], rater, RaterRole.ADVERTISER, 1, **kwargs
    )
    assert await service.get_blogger_avg_rating(blogger_id, **kwargs) == 3.5
    assert await service.get_blogger_ratings(blogger_id, **kwargs) == [
        second,
        first,
    ]
    assert transactions == ([] if explicit_session else ["begin", "end"] * 7)


@pytest.mark.asyncio
async def test_manager_admin_pagination_returns_total_independent_of_page():
    session = object()

    @asynccontextmanager
    async def transaction():
        yield session

    orders = [NS(order_id=uuid4())]
    repo = NS(
        count_all=AsyncMock(return_value=13),
        list_all_paginated=AsyncMock(return_value=orders),
    )
    service = ManagerService(
        Mock(), Mock(), repo, transaction_manager=NS(transaction=transaction)
    )
    assert await service.list_all_orders(limit=4, offset=12) == (orders, 13)
    repo.count_all.assert_awaited_once_with(session=session)
    repo.list_all_paginated.assert_awaited_once_with(
        limit=4, offset=12, session=session
    )


@pytest.mark.asyncio
async def test_advertiser_batch_profiles_preserves_sparse_mapping():
    requested = [uuid4(), uuid4()]
    profile = NS(user_id=requested[0], brand="Known brand")
    repo = NS(get_by_user_ids=AsyncMock(return_value={requested[0]: profile}))
    service = ProfileService(Mock(), Mock(), repo)
    assert await service.get_advertiser_profiles(requested) == {
        requested[0]: profile
    }
    repo.get_by_user_ids.assert_awaited_once_with(requested, session=None)


@pytest.mark.asyncio
async def test_redis_rate_limit_initializes_once_and_waits_for_reserved_slot(
    monkeypatch,
):
    from ugc_bot.application.services import geocoder_rate_limit_store as module

    client = NS(eval=AsyncMock(side_effect=["105.0", "105.0"]))
    factory = Mock(return_value=client)
    monkeypatch.setattr("redis.asyncio.Redis.from_url", factory)
    monkeypatch.setattr(
        module.time, "time", Mock(side_effect=[100.0, 101.0, 106.0, 107.0])
    )
    sleep = AsyncMock()
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    store = RedisGeocoderRateLimitStore("redis://not-connected", 2)
    await store.wait_until_allowed()
    await store.wait_until_allowed()
    factory.assert_called_once_with(
        "redis://not-connected", decode_responses=True
    )
    sleep.assert_awaited_once_with(4.0)
    assert client.eval.await_args_list[0].args[1:] == (
        1,
        NOMINATIM_RATE_LIMIT_KEY,
        "100.0",
        "2",
    )
    assert client.eval.await_args_list[1].args[1:] == (
        1,
        NOMINATIM_RATE_LIMIT_KEY,
        "106.0",
        "2",
    )

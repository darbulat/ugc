"""Tests for offer dispatch service."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.ports import BloggerProfileRepository
from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
)
from ugc_bot.domain.entities import (
    BloggerProfile,
    Interaction,
    Order,
    User,
)
from ugc_bot.domain.enums import (
    AudienceGender,
    InteractionStatus,
    MessengerType,
    OrderStatus,
    OrderType,
    UserStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryInteractionRepository,
    InMemoryOfferDispatchRepository,
    InMemoryOrderRepository,
    InMemoryUserRepository,
)


@pytest.mark.asyncio
async def test_dispatch_selects_confirmed_bloggers() -> None:
    """Dispatch returns only confirmed active bloggers."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000600"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000601"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000602"),
        external_id="100",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger)
    await blogger_repo.save(
        BloggerProfile(
            user_id=blogger.user_id,
            instagram_url="https://instagram.com/blogger",
            confirmed=True,
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
    )

    result = await service.dispatch(order.order_id)
    assert result == [blogger]


@pytest.mark.asyncio
async def test_dispatch_with_transaction_manager(fake_tm: object) -> None:
    """Cover transaction_manager path for dispatch."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
        transaction_manager=fake_tm,
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000650"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000651"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000652"),
        external_id="200",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger_tm",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger)
    await blogger_repo.save(
        BloggerProfile(
            user_id=blogger.user_id,
            instagram_url="https://instagram.com/blogger_tm",
            confirmed=True,
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
    )
    result = await service.dispatch(order.order_id)
    assert result == [blogger]


@pytest.mark.asyncio
async def test_dispatch_raises_when_order_not_found() -> None:
    """Dispatch raises OrderCreationError when order does not exist."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )
    missing_order_id = UUID("00000000-0000-0000-0000-000000000605")

    with pytest.raises(OrderCreationError, match="Order not found"):
        await service.dispatch(missing_order_id)


@pytest.mark.asyncio
async def test_dispatch_requires_active_order() -> None:
    """Dispatch fails for inactive orders."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000610"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000611"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    with pytest.raises(OrderCreationError):
        await service.dispatch(order.order_id)


@pytest.mark.asyncio
async def test_get_order_and_advertiser_with_transaction_manager(
    fake_tm: object,
) -> None:
    """get_order_and_advertiser uses transaction when tm is set."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
        transaction_manager=fake_tm,
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000612"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000613"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)
    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000613"),
        external_id="adv",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)

    got_order, got_advertiser = await service.get_order_and_advertiser(
        order.order_id
    )
    assert got_order is not None and got_order.order_id == order.order_id
    assert (
        got_advertiser is not None
        and got_advertiser.user_id == advertiser.user_id
    )


@pytest.mark.asyncio
async def test_get_order_and_advertiser_returns_none_when_order_missing() -> (
    None
):
    """get_order_and_advertiser returns (None, None) when order missing."""
    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )
    missing_order_id = UUID("00000000-0000-0000-0000-000000000617")
    got_order, got_advertiser = await service.get_order_and_advertiser(
        missing_order_id
    )
    assert got_order is None
    assert got_advertiser is None


@pytest.mark.asyncio
async def test_get_order_and_advertiser_returns_none_when_order_missing_with_tm(
    fake_tm: object,
) -> None:
    """get_order_and_advertiser with tm returns (None, None) when missing."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
        transaction_manager=fake_tm,
    )
    missing_order_id = UUID("00000000-0000-0000-0000-000000000616")
    got_order, got_advertiser = await service.get_order_and_advertiser(
        missing_order_id
    )
    assert got_order is None
    assert got_advertiser is None


def test_format_offer_ugc_only() -> None:
    """format_offer uses UGC-видео for ugc_only order."""
    service = OfferDispatchService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        order_repo=InMemoryOrderRepository(),
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        interaction_repo=InMemoryInteractionRepository(),
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000614"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000615"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Task",
        barter_description=None,
        price=500.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    text = service.format_offer(order, "Advertiser")
    assert "UGC-видео для бренда" in text
    assert "Task" in text
    assert "500" in text


def test_format_offer_with_barter_and_optional_fields() -> None:
    """format_offer includes barter, content_usage, deadlines, geography."""
    service = OfferDispatchService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        order_repo=InMemoryOrderRepository(),
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        interaction_repo=InMemoryInteractionRepository(),
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000618"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000619"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Task",
        barter_description="Product sample",
        price=0.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        content_usage="Stories and reels",
        deadlines="2 weeks",
        geography="Russia",
    )
    text = service.format_offer(order, "Advertiser")
    assert "Бартер: Product sample" in text
    assert "Использование: Stories and reels" in text
    assert "Сроки: 2 weeks" in text
    assert "География: Russia" in text


def test_format_offer_ugc_plus_placement() -> None:
    """format_offer uses UGC+размещение for ugc_plus_placement order."""

    service = OfferDispatchService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        order_repo=InMemoryOrderRepository(),
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        interaction_repo=InMemoryInteractionRepository(),
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000614"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000615"),
        order_type=OrderType.UGC_PLUS_PLACEMENT,
        product_link="https://example.com",
        offer_text="Task",
        barter_description=None,
        price=500.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    text = service.format_offer(order, "Advertiser")
    assert "UGC + размещение" in text
    assert "Task" in text
    assert "500" in text


@pytest.mark.asyncio
async def test_dispatch_skips_ineligible_bloggers() -> None:
    """Skip bloggers with missing user or invalid status."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000620"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000621"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    await blogger_repo.save(
        BloggerProfile(
            user_id=UUID("00000000-0000-0000-0000-000000000622"),
            instagram_url="https://instagram.com/ghost",
            confirmed=True,
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
    )

    await user_repo.save(
        User(
            user_id=UUID("00000000-0000-0000-0000-000000000623"),
            external_id="101",
            messenger_type=MessengerType.TELEGRAM,
            username="advertiser",
            status=UserStatus.BLOCKED,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
        )
    )
    await blogger_repo.save(
        BloggerProfile(
            user_id=UUID("00000000-0000-0000-0000-000000000623"),
            instagram_url="https://instagram.com/advertiser",
            confirmed=True,
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
    )

    assert await service.dispatch(order.order_id) == []


@pytest.mark.asyncio
async def test_dispatch_no_profiles_returns_empty() -> None:
    """Return empty list when no confirmed profiles."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000640"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000641"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    result = await service.dispatch(order.order_id)
    assert result == []


@pytest.mark.asyncio
async def test_dispatch_filters_by_geography_city() -> None:
    """With order geography 'Казань', only bloggers from Казань are returned."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000670"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000671"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        geography="Казань",
    )
    await order_repo.save(order)

    kazan_blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000672"),
        external_id="kazan",
        messenger_type=MessengerType.TELEGRAM,
        username="kazan_blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    moscow_blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000673"),
        external_id="moscow",
        messenger_type=MessengerType.TELEGRAM,
        username="moscow_blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(kazan_blogger)
    await user_repo.save(moscow_blogger)
    await blogger_repo.save(
        BloggerProfile(
            user_id=kazan_blogger.user_id,
            instagram_url="https://instagram.com/kazan",
            confirmed=True,
            city="Казань",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Казань",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=datetime.now(timezone.utc),
        )
    )
    await blogger_repo.save(
        BloggerProfile(
            user_id=moscow_blogger.user_id,
            instagram_url="https://instagram.com/moscow",
            confirmed=True,
            city="Москва",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Москва",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=datetime.now(timezone.utc),
        )
    )

    result = await service.dispatch(order.order_id)
    assert len(result) == 1
    assert result[0].user_id == kazan_blogger.user_id


@pytest.mark.asyncio
async def test_dispatch_geography_country_includes_all() -> None:
    """With order geography 'РФ', all confirmed bloggers are returned."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000680"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000681"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        geography="РФ",
    )
    await order_repo.save(order)

    blogger1 = User(
        user_id=UUID("00000000-0000-0000-0000-000000000682"),
        external_id="b1",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger1",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger2 = User(
        user_id=UUID("00000000-0000-0000-0000-000000000683"),
        external_id="b2",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger2",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger1)
    await user_repo.save(blogger2)
    for user, city in [(blogger1, "Казань"), (blogger2, "Москва")]:
        await blogger_repo.save(
            BloggerProfile(
                user_id=user.user_id,
                instagram_url=f"https://instagram.com/{user.username}",
                confirmed=True,
                city=city,
                topics={"selected": ["tech"]},
                audience_gender=AudienceGender.ALL,
                audience_age_min=18,
                audience_age_max=35,
                audience_geo=city,
                price=1000.0,
                barter=False,
                work_format=WorkFormat.UGC_ONLY,
                updated_at=datetime.now(timezone.utc),
            )
        )

    result = await service.dispatch(order.order_id)
    assert len(result) == 2
    assert {u.user_id for u in result} == {blogger1.user_id, blogger2.user_id}


@pytest.mark.asyncio
async def test_dispatch_geography_empty_no_filter() -> None:
    """No order geography: all confirmed bloggers returned."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000690"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000691"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000692"),
        external_id="b",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger)
    await blogger_repo.save(
        BloggerProfile(
            user_id=blogger.user_id,
            instagram_url="https://instagram.com/blogger",
            confirmed=True,
            city="Владивосток",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Владивосток",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=datetime.now(timezone.utc),
        )
    )

    result = await service.dispatch(order.order_id)
    assert len(result) == 1
    assert result[0].user_id == blogger.user_id


@pytest.mark.asyncio
async def test_dispatch_excludes_order_author() -> None:
    """Do not send order to its author even if they are a confirmed blogger."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )

    advertiser_id = UUID("00000000-0000-0000-0000-000000000650")
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000651"),
        advertiser_id=advertiser_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    # Advertiser who is also a blogger
    advertiser_blogger = User(
        user_id=advertiser_id,
        external_id="200",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser_blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser_blogger)
    await blogger_repo.save(
        BloggerProfile(
            user_id=advertiser_id,
            instagram_url="https://instagram.com/advertiser",
            confirmed=True,
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
    )

    # Another blogger
    other_blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000652"),
        external_id="201",
        messenger_type=MessengerType.TELEGRAM,
        username="other_blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(other_blogger)
    await blogger_repo.save(
        BloggerProfile(
            user_id=other_blogger.user_id,
            instagram_url="https://instagram.com/other",
            confirmed=True,
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
    )

    # Should only return other_blogger, not advertiser_blogger
    result = await service.dispatch(order.order_id)
    assert len(result) == 1
    assert result[0].user_id == other_blogger.user_id
    assert result[0].user_id != advertiser_id


@pytest.mark.asyncio
async def test_dispatch_excludes_bloggers_who_already_received_offer() -> None:
    """Do not return bloggers who already received an offer for this order."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000660"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000661"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    blogger_sent = User(
        user_id=UUID("00000000-0000-0000-0000-000000000662"),
        external_id="100",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger_sent",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger_new = User(
        user_id=UUID("00000000-0000-0000-0000-000000000663"),
        external_id="101",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger_new",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_sent)
    await user_repo.save(blogger_new)
    for b, url in [
        (blogger_sent, "instagram.com/sent"),
        (blogger_new, "instagram.com/new"),
    ]:
        await blogger_repo.save(
            BloggerProfile(
                user_id=b.user_id,
                instagram_url=f"https://{url}",
                confirmed=True,
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
        )

    await offer_dispatch_repo.record_sent(order.order_id, blogger_sent.user_id)

    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )

    result = await service.dispatch(order.order_id)
    assert len(result) == 1
    assert result[0].user_id == blogger_new.user_id


@pytest.mark.asyncio
async def test_record_offer_sent() -> None:
    """record_offer_sent persists to repo."""

    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferDispatchService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        order_repo=InMemoryOrderRepository(),
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )

    order_id = UUID("00000000-0000-0000-0000-000000000670")
    blogger_id = UUID("00000000-0000-0000-0000-000000000671")

    await service.record_offer_sent(order_id, blogger_id)

    sent = await offer_dispatch_repo.list_blogger_ids_sent_for_order(order_id)
    assert sent == [blogger_id]


@pytest.mark.asyncio
async def test_record_skip() -> None:
    """record_skip persists accepted=False, in_offer=False to repo."""
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferDispatchService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        order_repo=InMemoryOrderRepository(),
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )
    order_id = UUID("00000000-0000-0000-0000-000000000001")
    blogger_id = UUID("00000000-0000-0000-0000-000000000002")
    await offer_dispatch_repo.record_sent(order_id, blogger_id)
    await service.record_skip(order_id, blogger_id)
    responses = await offer_dispatch_repo.list_responses_by_order(order_id)
    assert len(responses) == 1
    assert responses[0].accepted is False
    assert responses[0].in_offer is False


@pytest.mark.asyncio
async def test_dispatch_excludes_bloggers_with_unfulfilled_interaction() -> (
    None
):
    """Bloggers with PENDING or ISSUE interaction are excluded from dispatch."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    interaction_repo = InMemoryInteractionRepository()

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000700"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000701"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    blogger_with_pending = User(
        user_id=UUID("00000000-0000-0000-0000-000000000702"),
        external_id="102",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger_pending",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_with_pending)
    await blogger_repo.save(
        BloggerProfile(
            user_id=blogger_with_pending.user_id,
            instagram_url="https://instagram.com/pending",
            confirmed=True,
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
    )

    interaction_pending = Interaction(
        interaction_id=UUID("00000000-0000-0000-0000-000000000710"),
        order_id=UUID("00000000-0000-0000-0000-000000000711"),
        blogger_id=blogger_with_pending.user_id,
        advertiser_id=order.advertiser_id,
        status=InteractionStatus.PENDING,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=0,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await interaction_repo.save(interaction_pending)

    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=interaction_repo,
    )

    result = await service.dispatch(order.order_id)
    assert result == []
    assert blogger_with_pending.user_id not in [u.user_id for u in result]


@pytest.mark.asyncio
async def test_dispatch_includes_bloggers_with_only_ok_or_no_deal() -> None:
    """Bloggers with only OK or NO_DEAL interactions are included."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    interaction_repo = InMemoryInteractionRepository()

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000720"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000721"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    blogger_ok = User(
        user_id=UUID("00000000-0000-0000-0000-000000000722"),
        external_id="122",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger_ok",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_ok)
    await blogger_repo.save(
        BloggerProfile(
            user_id=blogger_ok.user_id,
            instagram_url="https://instagram.com/ok",
            confirmed=True,
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
    )

    interaction_ok = Interaction(
        interaction_id=UUID("00000000-0000-0000-0000-000000000730"),
        order_id=UUID("00000000-0000-0000-0000-000000000731"),
        blogger_id=blogger_ok.user_id,
        advertiser_id=order.advertiser_id,
        status=InteractionStatus.OK,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=0,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await interaction_repo.save(interaction_ok)

    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=interaction_repo,
    )

    result = await service.dispatch(order.order_id)
    assert len(result) == 1
    assert result[0].user_id == blogger_ok.user_id


@pytest.mark.asyncio
async def test_dispatch_min_followers_excludes_below_threshold() -> None:
    """Min followers on: bloggers with followers < threshold excluded."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000740"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000741"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        min_followers=1000,
        max_followers=None,
    )
    await order_repo.save(order)

    blogger_low = User(
        user_id=UUID("00000000-0000-0000-0000-000000000742"),
        external_id="142",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger_low",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_low)
    await blogger_repo.save(
        BloggerProfile(
            user_id=blogger_low.user_id,
            instagram_url="https://instagram.com/low",
            confirmed=True,
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
            instagram_followers_count=999,
        )
    )

    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )

    result = await service.dispatch(order.order_id)
    assert result == []


@pytest.mark.asyncio
async def test_dispatch_min_followers_includes_at_or_above_threshold() -> None:
    """Min followers on: bloggers with followers >= threshold included."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000750"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000751"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        min_followers=1000,
        max_followers=None,
    )
    await order_repo.save(order)

    blogger_ok = User(
        user_id=UUID("00000000-0000-0000-0000-000000000752"),
        external_id="152",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger_ok",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_ok)
    await blogger_repo.save(
        BloggerProfile(
            user_id=blogger_ok.user_id,
            instagram_url="https://instagram.com/ok",
            confirmed=True,
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
            instagram_followers_count=1000,
        )
    )

    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )

    result = await service.dispatch(order.order_id)
    assert len(result) == 1
    assert result[0].user_id == blogger_ok.user_id


@pytest.mark.asyncio
async def test_dispatch_min_followers_excludes_none_when_enabled() -> None:
    """Min followers on: bloggers with followers_count None excluded."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000760"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000761"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        min_followers=1000,
        max_followers=None,
    )
    await order_repo.save(order)

    blogger_no_stats = User(
        user_id=UUID("00000000-0000-0000-0000-000000000762"),
        external_id="162",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger_nostats",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_no_stats)
    await blogger_repo.save(
        BloggerProfile(
            user_id=blogger_no_stats.user_id,
            instagram_url="https://instagram.com/nostats",
            confirmed=True,
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
            instagram_followers_count=None,
        )
    )

    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )

    result = await service.dispatch(order.order_id)
    assert result == []


@pytest.mark.asyncio
async def test_dispatch_max_followers_excludes_above_threshold() -> None:
    """Max followers on: bloggers with followers > threshold excluded."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000770"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000771"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        min_followers=None,
        max_followers=5000,
    )
    await order_repo.save(order)

    blogger_high = User(
        user_id=UUID("00000000-0000-0000-0000-000000000772"),
        external_id="172",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger_high",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_high)
    await blogger_repo.save(
        BloggerProfile(
            user_id=blogger_high.user_id,
            instagram_url="https://instagram.com/high",
            confirmed=True,
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
            instagram_followers_count=10_000,
        )
    )

    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )

    result = await service.dispatch(order.order_id)
    assert result == []


@pytest.mark.asyncio
async def test_dispatch_max_followers_excludes_none_when_enabled() -> None:
    """Max followers on: bloggers with followers_count None excluded."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000775"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000776"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        min_followers=None,
        max_followers=5000,
    )
    await order_repo.save(order)

    blogger_nostats = User(
        user_id=UUID("00000000-0000-0000-0000-000000000777"),
        external_id="177",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger_nostats",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_nostats)
    await blogger_repo.save(
        BloggerProfile(
            user_id=blogger_nostats.user_id,
            instagram_url="https://instagram.com/nostats",
            confirmed=True,
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
            instagram_followers_count=None,
        )
    )

    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )

    result = await service.dispatch(order.order_id)
    assert result == []


@pytest.mark.asyncio
async def test_dispatch_uses_order_min_max_followers(fake_tm: object) -> None:
    """Order min_followers/max_followers are used for filtering."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000780"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000781"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        min_followers=500,
        max_followers=3000,
    )
    await order_repo.save(order)

    blogger_in_range = User(
        user_id=UUID("00000000-0000-0000-0000-000000000782"),
        external_id="182",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger_ok",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_in_range)
    await blogger_repo.save(
        BloggerProfile(
            user_id=blogger_in_range.user_id,
            instagram_url="https://instagram.com/ok",
            confirmed=True,
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
            instagram_followers_count=2000,
        )
    )

    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
        transaction_manager=fake_tm,
    )
    result = await service.dispatch(order.order_id)
    assert len(result) == 1
    assert result[0].user_id == blogger_in_range.user_id


class _BloggerRepoNoneProfile(BloggerProfileRepository):
    """One confirmed user_id but get_by_user_id returns None (edge case)."""

    def __init__(self, user_id: UUID) -> None:
        self._user_id = user_id

    async def list_confirmed_user_ids(
        self, session: object | None = None
    ) -> list[UUID]:
        return [self._user_id]

    async def get_by_user_id(
        self, user_id: UUID, session: object | None = None
    ):
        return None

    async def list_confirmed_with_instagram_id(
        self,
        limit: int,
        offset: int = 0,
        stats_older_than=None,
        session: object | None = None,
    ):
        return []

    async def save(self, profile, session: object | None = None) -> None:
        pass

    async def get_by_instagram_url(
        self, instagram_url: str, session: object | None = None
    ):
        return None


@pytest.mark.asyncio
async def test_dispatch_skips_when_profile_fetch_returns_none() -> None:
    """Skip when need_profile and get_by_user_id returns None."""
    user_id = UUID("00000000-0000-0000-0000-000000000790")
    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=user_id,
            external_id="790",
            messenger_type=MessengerType.TELEGRAM,
            username="u",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
        )
    )
    blogger_repo = _BloggerRepoNoneProfile(user_id)
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000791"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000792"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        min_followers=1000,
        max_followers=None,
    )
    await order_repo.save(order)
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )
    result = await service.dispatch(order.order_id)
    assert result == []

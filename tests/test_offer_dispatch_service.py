"""Tests for offer dispatch service."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
)
from ugc_bot.domain.entities import BloggerProfile, Order, User
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    OrderStatus,
    OrderType,
    UserStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
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
        transaction_manager=fake_tm,
    )
    missing_order_id = UUID("00000000-0000-0000-0000-000000000616")
    got_order, got_advertiser = await service.get_order_and_advertiser(
        missing_order_id
    )
    assert got_order is None
    assert got_advertiser is None


def test_format_offer_ugc_plus_placement() -> None:
    """format_offer uses UGC+размещение for ugc_plus_placement order."""

    service = OfferDispatchService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        order_repo=InMemoryOrderRepository(),
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
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
    )

    order_id = UUID("00000000-0000-0000-0000-000000000670")
    blogger_id = UUID("00000000-0000-0000-0000-000000000671")

    await service.record_offer_sent(order_id, blogger_id)

    sent = await offer_dispatch_repo.list_blogger_ids_sent_for_order(order_id)
    assert sent == [blogger_id]

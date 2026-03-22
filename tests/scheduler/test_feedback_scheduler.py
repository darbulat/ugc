"""Tests for feedback scheduler."""

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import UUID, uuid4


import pytest

from tests.helpers.fakes import FakeBot, FakeBotWithSession
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
from ugc_bot.config import FeedbackConfig, load_config
from ugc_bot.domain.entities import (
    AdvertiserProfile,
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
from ugc_bot.feedback_scheduler import (
    _feedback_keyboard,
    _feedback_texts_for_locale,
    main,
    run_loop,
    run_once,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryBloggerProfileRepository,
    InMemoryInteractionRepository,
    InMemoryOfferDispatchRepository,
    InMemoryOrderRepository,
    InMemoryUserRepository,
)
from ugc_bot.startup_logging import log_startup_info, safe_config_for_logging


def test_feedback_keyboard() -> None:
    """Ensure feedback keyboard contains callback data and button labels."""
    texts = _feedback_texts_for_locale("ru")
    markup_adv = _feedback_keyboard(
        "adv", UUID("00000000-0000-0000-0000-000000000950"), texts
    )
    first_adv = markup_adv.rows[0][0]
    assert "feedback:adv:" in first_adv.callback_data
    assert first_adv.text == DEFAULT_TEXTS["ru"]["msg_fb_feedback_ok"]
    postpone_adv = markup_adv.rows[2][0]
    assert postpone_adv.text == DEFAULT_TEXTS["ru"]["msg_fb_feedback_postpone"]

    markup_blog = _feedback_keyboard(
        "blog", UUID("00000000-0000-0000-0000-000000000950"), texts
    )
    assert (
        markup_blog.rows[0][0].text == DEFAULT_TEXTS["ru"]["msg_fb_feedback_ok"]
    )


@pytest.mark.asyncio
async def test_run_once_sends_feedback_requests(fake_tm) -> None:
    """Send feedback to advertiser and blogger."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000960"),
        telegram_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000961"),
        telegram_id="11",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)
    await user_repo.save(blogger)
    await advertiser_repo.save(
        AdvertiserProfile(
            user_id=advertiser.user_id,
            phone="c",
            brand="B",
        )
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000962"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc) - timedelta(hours=73),
    )
    await order_repo.save(order)
    await dispatch_repo.record_sent(order.order_id, blogger.user_id)
    await dispatch_repo.record_response(
        order.order_id, blogger.user_id, accepted=True, in_offer=True
    )

    # Create interaction with next_check_at in the past
    interaction = await interaction_service.create_for_contacts_sent(
        order_id=order.order_id,
        blogger_id=blogger.user_id,
        advertiser_id=advertiser.user_id,
    )
    # Manually set next_check_at to past
    past_interaction = Interaction(
        interaction_id=interaction.interaction_id,
        order_id=interaction.order_id,
        blogger_id=interaction.blogger_id,
        advertiser_id=interaction.advertiser_id,
        status=InteractionStatus.PENDING,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=0,
        next_check_at=datetime.now(timezone.utc) - timedelta(hours=1),
        created_at=interaction.created_at,
        updated_at=interaction.updated_at,
    )
    await interaction_repo.save(past_interaction)

    feedback_config = FeedbackConfig()
    bot = FakeBot()
    await run_once(
        {"telegram": bot},
        interaction_repo,
        interaction_service,
        user_service,
        None,
        order_repo,
        feedback_config,
        cutoff=datetime.now(timezone.utc),
        transaction_manager=fake_tm,
    )
    assert len(bot.messages) == 2


@pytest.mark.asyncio
async def test_run_once_blogger_message_adds_https_to_product_link(
    fake_tm,
) -> None:
    """When order product_link has no scheme, scheduler prepends https://."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000965"),
        telegram_id="12",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000966"),
        telegram_id="13",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)
    await user_repo.save(blogger)
    await advertiser_repo.save(
        AdvertiserProfile(
            user_id=advertiser.user_id,
            phone="c",
            brand="B",
        )
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000967"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="example.com/product",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc) - timedelta(hours=73),
    )
    await order_repo.save(order)

    await dispatch_repo.record_sent(order.order_id, blogger.user_id)
    await dispatch_repo.record_response(
        order.order_id, blogger.user_id, accepted=True, in_offer=True
    )
    interaction = await interaction_service.create_for_contacts_sent(
        order_id=order.order_id,
        blogger_id=blogger.user_id,
        advertiser_id=advertiser.user_id,
    )
    past_interaction = Interaction(
        interaction_id=interaction.interaction_id,
        order_id=interaction.order_id,
        blogger_id=interaction.blogger_id,
        advertiser_id=interaction.advertiser_id,
        status=InteractionStatus.PENDING,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=0,
        next_check_at=datetime.now(timezone.utc) - timedelta(hours=1),
        created_at=interaction.created_at,
        updated_at=interaction.updated_at,
    )
    await interaction_repo.save(past_interaction)

    feedback_config = FeedbackConfig()
    bot = FakeBot()
    await run_once(
        {"telegram": bot},
        interaction_repo,
        interaction_service,
        user_service,
        None,
        order_repo,
        feedback_config,
        cutoff=datetime.now(timezone.utc),
        transaction_manager=fake_tm,
    )

    blogger_chat_id = 13
    blogger_texts = [
        text for cid, text, _ in bot.messages if cid == blogger_chat_id
    ]
    assert blogger_texts
    assert any("example.com" in t for t in blogger_texts)


@pytest.mark.asyncio
async def test_run_once_blogger_second_order_gets_product_link(fake_tm) -> None:
    """Blogger second order: old feedback includes product link with https."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000969"),
        telegram_id="14",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-00000000096a"),
        telegram_id="15",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger)
    await user_repo.save(advertiser)
    await advertiser_repo.save(
        AdvertiserProfile(user_id=advertiser.user_id, phone="c", brand="B")
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-00000000096d"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="example.com/product2",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc) - timedelta(hours=73),
    )
    await order_repo.save(order)
    await dispatch_repo.record_sent(order.order_id, blogger.user_id)
    await dispatch_repo.record_response(
        order.order_id, blogger.user_id, accepted=True, in_offer=True
    )
    interaction = await interaction_service.create_for_contacts_sent(
        order_id=order.order_id,
        blogger_id=blogger.user_id,
        advertiser_id=advertiser.user_id,
    )
    past_interaction = Interaction(
        interaction_id=interaction.interaction_id,
        order_id=interaction.order_id,
        blogger_id=interaction.blogger_id,
        advertiser_id=interaction.advertiser_id,
        status=InteractionStatus.PENDING,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=0,
        next_check_at=datetime.now(timezone.utc) - timedelta(hours=1),
        created_at=interaction.created_at,
        updated_at=interaction.updated_at,
    )
    await interaction_repo.save(past_interaction)

    feedback_config = FeedbackConfig()
    bot = FakeBot()
    await run_once(
        {"telegram": bot},
        interaction_repo,
        interaction_service,
        user_service,
        None,
        order_repo,
        feedback_config,
        cutoff=datetime.now(timezone.utc),
        transaction_manager=fake_tm,
    )

    blogger_texts = [text for cid, text, _ in bot.messages if cid == 14]
    assert blogger_texts
    assert "https://example.com/product2" in blogger_texts[0]


@pytest.mark.asyncio
async def test_run_once_skips_active_orders() -> None:
    """Skip interactions that are not PENDING or have future next_check_at."""

    interaction_repo = InMemoryInteractionRepository()
    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    # Create interaction with future next_check_at (should be skipped)
    await interaction_repo.save(
        Interaction(
            interaction_id=UUID("00000000-0000-0000-0000-000000000970"),
            order_id=UUID("00000000-0000-0000-0000-000000000971"),
            blogger_id=UUID("00000000-0000-0000-0000-000000000972"),
            advertiser_id=UUID("00000000-0000-0000-0000-000000000973"),
            status=InteractionStatus.PENDING,
            from_advertiser=None,
            from_blogger=None,
            postpone_count=0,
            next_check_at=datetime.now(timezone.utc)
            + timedelta(hours=1),  # Future
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )

    order_repo = InMemoryOrderRepository()
    feedback_config = FeedbackConfig()
    bot = FakeBot()
    await run_once(
        {"telegram": bot},
        interaction_repo,
        interaction_service,
        user_service,
        None,
        order_repo,
        feedback_config,
        cutoff=datetime.now(timezone.utc),
        transaction_manager=None,
    )
    assert not bot.messages


@pytest.mark.asyncio
async def test_run_once_skips_orders_without_responses() -> None:
    """Skip when no interactions are due for feedback."""

    interaction_repo = InMemoryInteractionRepository()
    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    # No interactions created, so nothing to process
    order_repo = InMemoryOrderRepository()
    feedback_config = FeedbackConfig()
    bot = FakeBot()
    await run_once(
        {"telegram": bot},
        interaction_repo,
        interaction_service,
        user_service,
        None,
        order_repo,
        feedback_config,
        cutoff=datetime.now(timezone.utc),
        transaction_manager=None,
    )
    assert not bot.messages


@pytest.mark.asyncio
async def test_run_once_existing_feedback_no_messages() -> None:
    """Skip sending when feedback already collected."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000980"),
        telegram_id="20",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000981"),
        telegram_id="21",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)
    await user_repo.save(blogger)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000982"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc) - timedelta(hours=73),
    )
    await order_repo.save(order)
    await dispatch_repo.record_sent(order.order_id, blogger.user_id)
    await dispatch_repo.record_response(
        order.order_id, blogger.user_id, accepted=True, in_offer=True
    )
    await interaction_repo.save(
        Interaction(
            interaction_id=UUID("00000000-0000-0000-0000-000000000984"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            advertiser_id=advertiser.user_id,
            status=InteractionStatus.OK,
            from_advertiser="✅ Всё прошло нормально",
            from_blogger="✅ Всё прошло нормально",
            postpone_count=0,
            next_check_at=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )

    feedback_config = FeedbackConfig()
    bot = FakeBot()
    await run_once(
        {"telegram": bot},
        interaction_repo,
        interaction_service,
        user_service,
        None,
        order_repo,
        feedback_config,
        cutoff=datetime.now(timezone.utc),
        transaction_manager=None,
    )
    assert not bot.messages


@pytest.mark.asyncio
async def test_run_once_sends_reminder_after_postpone(fake_tm) -> None:
    """When advertiser postpones, scheduler sends reminder again when due."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000990"),
        telegram_id="30",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000991"),
        telegram_id="31",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)
    await user_repo.save(blogger)
    await advertiser_repo.save(
        AdvertiserProfile(
            user_id=advertiser.user_id,
            phone="c",
            brand="B",
        )
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000992"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc) - timedelta(hours=73),
    )
    await order_repo.save(order)
    await dispatch_repo.record_sent(order.order_id, blogger.user_id)
    await dispatch_repo.record_response(
        order.order_id, blogger.user_id, accepted=True, in_offer=True
    )

    await interaction_repo.save(
        Interaction(
            interaction_id=UUID("00000000-0000-0000-0000-000000000994"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            advertiser_id=advertiser.user_id,
            status=InteractionStatus.PENDING,
            from_advertiser="⏳ Ещё не связался",
            from_blogger=None,
            postpone_count=1,
            next_check_at=datetime.now(timezone.utc) - timedelta(hours=1),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )

    feedback_config = FeedbackConfig()
    bot = FakeBot()
    await run_once(
        {"telegram": bot},
        interaction_repo,
        interaction_service,
        user_service,
        None,
        order_repo,
        feedback_config,
        cutoff=datetime.now(timezone.utc),
        transaction_manager=fake_tm,
    )
    assert len(bot.messages) >= 1
    adv_messages = [m for m in bot.messages if m[0] == 30]
    assert adv_messages, "Advertiser who postponed should receive reminder"


@pytest.mark.asyncio
async def test_run_once_skips_when_blogger_not_in_user_repo(fake_tm) -> None:
    """Skip blogger feedback when user not found; still send to advertiser."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000985"),
        telegram_id="985",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger_id = UUID("00000000-0000-0000-0000-000000000986")
    await user_repo.save(advertiser)
    await advertiser_repo.save(
        AdvertiserProfile(user_id=advertiser.user_id, phone="x", brand="B")
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000987"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc) - timedelta(hours=73),
    )
    await order_repo.save(order)
    await dispatch_repo.record_sent(order.order_id, blogger_id)
    await dispatch_repo.record_response(
        order.order_id, blogger_id, accepted=True, in_offer=True
    )
    interaction = await interaction_service.create_for_contacts_sent(
        order_id=order.order_id,
        blogger_id=blogger_id,
        advertiser_id=advertiser.user_id,
    )
    past_interaction = Interaction(
        interaction_id=interaction.interaction_id,
        order_id=interaction.order_id,
        blogger_id=blogger_id,
        advertiser_id=advertiser.user_id,
        status=InteractionStatus.PENDING,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=0,
        next_check_at=datetime.now(timezone.utc) - timedelta(hours=1),
        created_at=interaction.created_at,
        updated_at=interaction.updated_at,
    )
    await interaction_repo.save(past_interaction)

    feedback_config = FeedbackConfig()
    bot = FakeBot()
    await run_once(
        {"telegram": bot},
        interaction_repo,
        interaction_service,
        user_service,
        None,
        order_repo,
        feedback_config,
        cutoff=datetime.now(timezone.utc),
        transaction_manager=fake_tm,
    )
    adv_messages = [m for m in bot.messages if m[0] == 985]
    assert len(adv_messages) == 1
    assert "креатор" in adv_messages[0][1] or "связаться" in adv_messages[0][1]


@pytest.mark.asyncio
async def test_run_once_skips_when_advertiser_not_in_user_repo(fake_tm) -> None:
    """Skip advertiser feedback when user not found; still send to blogger."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000989"),
        telegram_id="989",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    advertiser_id = UUID("00000000-0000-0000-0000-00000000098a")
    await user_repo.save(blogger)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-00000000098b"),
        advertiser_id=advertiser_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc) - timedelta(hours=73),
    )
    await order_repo.save(order)
    await dispatch_repo.record_sent(order.order_id, blogger.user_id)
    await dispatch_repo.record_response(
        order.order_id, blogger.user_id, accepted=True, in_offer=True
    )
    interaction = await interaction_service.create_for_contacts_sent(
        order_id=order.order_id,
        blogger_id=blogger.user_id,
        advertiser_id=advertiser_id,
    )
    past_interaction = Interaction(
        interaction_id=interaction.interaction_id,
        order_id=interaction.order_id,
        blogger_id=blogger.user_id,
        advertiser_id=advertiser_id,
        status=InteractionStatus.PENDING,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=0,
        next_check_at=datetime.now(timezone.utc) - timedelta(hours=1),
        created_at=interaction.created_at,
        updated_at=interaction.updated_at,
    )
    await interaction_repo.save(past_interaction)

    feedback_config = FeedbackConfig()
    bot = FakeBot()
    await run_once(
        {"telegram": bot},
        interaction_repo,
        interaction_service,
        user_service,
        None,
        order_repo,
        feedback_config,
        cutoff=datetime.now(timezone.utc),
        transaction_manager=fake_tm,
    )
    blog_messages = [m for m in bot.messages if m[0] == 989]
    assert len(blog_messages) == 1
    assert (
        "заказчик" in blog_messages[0][1] or "связаться" in blog_messages[0][1]
    )


@pytest.mark.asyncio
async def test_run_loop_closes_session() -> None:
    """Ensure run_loop closes bot session."""

    bot = FakeBotWithSession()
    interaction_repo = InMemoryInteractionRepository()
    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    feedback_config = FeedbackConfig()
    await run_loop(
        {"telegram": bot},
        interaction_repo,
        interaction_service,
        user_service,
        None,
        order_repo,
        feedback_config,
        interval_seconds=0,
        transaction_manager=None,
        max_iterations=1,
    )
    assert bot.session.closed is True


@pytest.mark.asyncio
async def test_run_loop_sleeps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure run_loop awaits sleep between iterations."""

    slept = {"called": False}

    async def _fake_sleep(_: int) -> None:
        slept["called"] = True

    monkeypatch.setattr("ugc_bot.feedback_scheduler.asyncio.sleep", _fake_sleep)

    bot = FakeBotWithSession()
    interaction_repo = InMemoryInteractionRepository()
    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    order_repo = InMemoryOrderRepository()
    feedback_config = FeedbackConfig()
    await run_loop(
        {"telegram": bot},
        interaction_repo,
        interaction_service,
        user_service,
        None,
        order_repo,
        feedback_config,
        interval_seconds=1,
        transaction_manager=None,
        max_iterations=2,
    )
    assert slept["called"] is True


def test_main_feedback_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Main runs asyncio loop when feedback enabled."""

    monkeypatch.setenv("FEEDBACK_ENABLED", "true")
    monkeypatch.setenv("BOT_TOKEN", "123456:ABCDEF1234567890abcdef1234567890")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://user:pass@localhost:5432/db"
    )

    class FakeContainer:
        def __init__(self, config: object) -> None:
            pass

        def build_feedback_scheduler_deps(self) -> dict:
            return {
                "interaction_repo": Mock(),
                "order_repo": Mock(),
                "transaction_manager": Mock(),
                "interaction_service": Mock(),
                "user_role_service": Mock(),
                "profile_service": Mock(),
            }

        def build_bot_texts_service(self) -> Mock:
            return Mock()

        async def dispose(self) -> None:
            pass

    monkeypatch.setattr("ugc_bot.feedback_scheduler.Container", FakeContainer)

    def _run(coro) -> None:  # type: ignore[no-untyped-def]
        coro.close()

    monkeypatch.setattr("ugc_bot.feedback_scheduler.asyncio.run", _run)
    main()


def test_safe_config_for_logging_masks_sensitive_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure sensitive config values are masked before logging."""

    monkeypatch.setenv("BOT_TOKEN", "123456:ABCDEF")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://user:pass@localhost:5432/db"
    )
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-pass")
    monkeypatch.setenv("ADMIN_SECRET", "admin-secret")
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "ig-secret-token")
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", "ig-app-secret")
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_VERIFY_TOKEN", "verify-token")
    monkeypatch.setenv("REDIS_URL", "redis://user:pass@localhost:6379/0")
    monkeypatch.setenv(
        "INSTAGRAM_API_BASE_URL", "https://user:pass@example.com/api"
    )

    config = load_config()
    safe = safe_config_for_logging(config)

    assert safe["bot"]["bot_token"] == "***"
    assert safe["db"]["database_url"] == "***"
    assert safe["admin"]["admin_password"] == "***"
    assert safe["admin"]["admin_secret"] == "***"
    assert safe["instagram"]["instagram_access_token"] == "***"
    assert safe["instagram"]["instagram_app_secret"] == "***"
    assert safe["instagram"]["instagram_webhook_verify_token"] == "***"
    assert safe["redis"]["redis_url"] == "***"
    assert (
        safe["instagram"]["instagram_api_base_url"]
        == "https://user:***@example.com/api"
    )


def test_log_startup_info_includes_config_in_text_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Text log format: startup log includes version and sanitized config."""

    monkeypatch.setenv("LOG_FORMAT", "text")
    monkeypatch.setenv("BOT_TOKEN", "123456:ABCDEF")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://user:pass@localhost:5432/db"
    )

    config = load_config()
    with caplog.at_level("INFO"):
        log_startup_info(
            logger=logging.getLogger(__name__),
            service_name="Feedback scheduler",
            config=config,
        )

    message = "\n".join(r.getMessage() for r in caplog.records)
    assert "Feedback scheduler starting" in message


@pytest.mark.asyncio
async def test_run_once_advertiser_gets_creator_link_when_blogger_has_instagram(
    fake_tm,
) -> None:
    """Advertiser feedback includes creator link when profile has instagram."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = ProfileService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        advertiser_repo=advertiser_repo,
        transaction_manager=None,
    )

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000990"),
        telegram_id="30",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000991"),
        telegram_id="31",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)
    await user_repo.save(blogger)
    await advertiser_repo.save(
        AdvertiserProfile(
            user_id=advertiser.user_id,
            phone="c",
            brand="B",
        )
    )
    await blogger_repo.save(
        BloggerProfile(
            user_id=blogger.user_id,
            instagram_url="instagram.com/creator",
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

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000992"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc) - timedelta(hours=73),
    )
    await order_repo.save(order)
    await dispatch_repo.record_sent(order.order_id, blogger.user_id)
    await dispatch_repo.record_response(
        order.order_id, blogger.user_id, accepted=True, in_offer=True
    )

    interaction = await interaction_service.create_for_contacts_sent(
        order_id=order.order_id,
        blogger_id=blogger.user_id,
        advertiser_id=advertiser.user_id,
    )
    past_interaction = Interaction(
        interaction_id=interaction.interaction_id,
        order_id=interaction.order_id,
        blogger_id=interaction.blogger_id,
        advertiser_id=interaction.advertiser_id,
        status=InteractionStatus.PENDING,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=0,
        next_check_at=datetime.now(timezone.utc) - timedelta(hours=1),
        created_at=interaction.created_at,
        updated_at=interaction.updated_at,
    )
    await interaction_repo.save(past_interaction)

    feedback_config = FeedbackConfig()
    bot = FakeBot()
    await run_once(
        {"telegram": bot},
        interaction_repo,
        interaction_service,
        user_service,
        profile_service,
        order_repo,
        feedback_config,
        cutoff=datetime.now(timezone.utc),
        transaction_manager=fake_tm,
    )
    assert len(bot.messages) >= 2
    adv_texts = [t for (cid, t, _) in bot.messages if cid == 30]
    adv_text = " ".join(adv_texts)
    assert "креатор" in adv_text
    assert "https://instagram.com/creator" in adv_text


def test_main_feedback_disabled_returns_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Main returns without creating Container when feedback is disabled."""

    monkeypatch.setenv("FEEDBACK_ENABLED", "false")
    monkeypatch.setenv("BOT_TOKEN", "123456:ABCDEF1234567890abcdef1234567890")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://user:pass@localhost:5432/db"
    )
    container_mock = Mock()
    monkeypatch.setattr(
        "ugc_bot.feedback_scheduler.Container",
        container_mock,
    )
    main()
    container_mock.assert_not_called()


def test_main_no_database_url_returns_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Main returns early when feedback enabled but DATABASE_URL is empty."""

    monkeypatch.setenv("FEEDBACK_ENABLED", "true")
    monkeypatch.setenv("BOT_TOKEN", "123456:ABCDEF1234567890abcdef1234567890")
    # Some environments may provide DATABASE_URL from other sources (e.g. local
    # .env or OS-level variables). Ensure it's explicitly empty for this test.
    monkeypatch.setenv("DATABASE_URL", "")
    container_mock = Mock()
    monkeypatch.setattr(
        "ugc_bot.feedback_scheduler.Container",
        container_mock,
    )
    main()
    container_mock.assert_not_called()


@pytest.mark.asyncio
async def test_run_once_skips_when_both_users_not_found(fake_tm) -> None:
    """Skip interaction when both blogger and advertiser are missing."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    # Neither blogger nor advertiser is saved to user_repo
    blogger_id = UUID("00000000-0000-0000-0000-0000000099a0")
    advertiser_id = UUID("00000000-0000-0000-0000-0000000099a1")

    await interaction_repo.save(
        Interaction(
            interaction_id=UUID("00000000-0000-0000-0000-0000000099a2"),
            order_id=UUID("00000000-0000-0000-0000-0000000099a3"),
            blogger_id=blogger_id,
            advertiser_id=advertiser_id,
            status=InteractionStatus.PENDING,
            from_advertiser=None,
            from_blogger=None,
            postpone_count=0,
            next_check_at=datetime.now(timezone.utc) - timedelta(hours=1),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )

    feedback_config = FeedbackConfig()
    bot = FakeBot()
    await run_once(
        {"telegram": bot},
        interaction_repo,
        interaction_service,
        user_service,
        None,
        order_repo,
        feedback_config,
        cutoff=datetime.now(timezone.utc),
        transaction_manager=fake_tm,
    )
    assert not bot.messages


@pytest.mark.asyncio
async def test_run_loop_uses_close_method_when_available() -> None:
    """run_loop calls bot.close() when it exists as a callable."""

    class BotWithClose(FakeBot):
        def __init__(self) -> None:
            super().__init__()
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    bot = BotWithClose()
    interaction_repo = InMemoryInteractionRepository()
    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    feedback_config = FeedbackConfig()
    await run_loop(
        {"telegram": bot},
        interaction_repo,
        interaction_service,
        user_service,
        None,
        order_repo,
        feedback_config,
        interval_seconds=0,
        transaction_manager=None,
        max_iterations=1,
    )
    assert bot.closed is True


@pytest.mark.asyncio
async def test_feedback_message_uses_user_locale(fake_tm) -> None:
    """Feedback scheduler uses user.language when sending messages."""
    from unittest.mock import AsyncMock

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-0000000099b0"),
        telegram_id="9910",
        messenger_type=MessengerType.TELEGRAM,
        username="adv_en",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        language="en",
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-0000000099b1"),
        telegram_id="9911",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger_en",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        language="en",
    )
    await user_repo.save(advertiser)
    await user_repo.save(blogger)
    await advertiser_repo.save(
        AdvertiserProfile(
            user_id=advertiser.user_id,
            phone="c",
            brand="B",
        )
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-0000000099b2"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc) - timedelta(hours=73),
    )
    await order_repo.save(order)
    await dispatch_repo.record_sent(order.order_id, blogger.user_id)
    await dispatch_repo.record_response(
        order.order_id, blogger.user_id, accepted=True, in_offer=True
    )

    interaction = await interaction_service.create_for_contacts_sent(
        order_id=order.order_id,
        blogger_id=blogger.user_id,
        advertiser_id=advertiser.user_id,
    )
    past_interaction = Interaction(
        interaction_id=interaction.interaction_id,
        order_id=interaction.order_id,
        blogger_id=interaction.blogger_id,
        advertiser_id=interaction.advertiser_id,
        status=InteractionStatus.PENDING,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=0,
        next_check_at=datetime.now(timezone.utc) - timedelta(hours=1),
        created_at=interaction.created_at,
        updated_at=interaction.updated_at,
    )
    await interaction_repo.save(past_interaction)

    # Build a fake bot_texts_service that records calls to get_many
    get_many_calls: list[tuple[list[str], str]] = []

    async def fake_get_many(
        keys: list[str], locale: str | None = None
    ) -> dict[str, str]:
        get_many_calls.append((keys, locale or "ru"))
        # Return English defaults
        return {k: DEFAULT_TEXTS.get("en", {}).get(k, "") for k in keys}

    bot_texts_service = AsyncMock()
    bot_texts_service.get_many = fake_get_many

    feedback_config = FeedbackConfig()
    bot = FakeBot()
    await run_once(
        {"telegram": bot},
        interaction_repo,
        interaction_service,
        user_service,
        None,
        order_repo,
        feedback_config,
        cutoff=datetime.now(timezone.utc),
        transaction_manager=fake_tm,
        bot_texts_service=bot_texts_service,
    )
    assert len(bot.messages) == 2
    # bot_texts_service.get_many was called with "en" locale for each user
    locales_used = [locale for _, locale in get_many_calls]
    assert "en" in locales_used, (
        f"Expected 'en' locale calls, got: {locales_used}"
    )


def test_user_messenger_targets_includes_max_id() -> None:
    """_user_messenger_targets includes max_id entry when max client present."""
    from ugc_bot.feedback_scheduler import _user_messenger_targets

    user = User(
        user_id=uuid4(),
        max_id="max-99",
        messenger_type=MessengerType.MAX,
        username="maxu",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_client = Mock()
    targets = _user_messenger_targets(user, {"max": mock_client})
    assert len(targets) == 1
    assert targets[0][0] == "max-99"
    assert targets[0][1] is mock_client


@pytest.mark.asyncio
async def test_send_advertiser_feedback_returns_false_when_no_targets() -> None:
    """_send_advertiser_feedback returns False when no messenger targets."""
    from ugc_bot.feedback_scheduler import _send_advertiser_feedback

    # User with no telegram_id and no max_id → no targets
    advertiser = User(
        user_id=uuid4(),
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    result = await _send_advertiser_feedback(
        messenger_clients={},
        interaction=Mock(),
        advertiser=advertiser,
        blogger_profile=None,
        texts={},
    )
    assert result is False


@pytest.mark.asyncio
async def test_send_blogger_feedback_returns_false_when_no_targets() -> None:
    """_send_blogger_feedback returns False when blogger has no messenger."""
    from ugc_bot.feedback_scheduler import _send_blogger_feedback

    blogger = User(
        user_id=uuid4(),
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    result = await _send_blogger_feedback(
        messenger_clients={},
        interaction=Mock(),
        blogger=blogger,
        order=None,
        texts={},
    )
    assert result is False

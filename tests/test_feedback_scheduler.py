"""Tests for feedback scheduler."""

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import UUID

import pytest

from tests.helpers.fakes import FakeBot, FakeBotWithSession
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.config import FeedbackConfig, load_config
from ugc_bot.domain.entities import (
    AdvertiserProfile,
    BloggerProfile,
    Interaction,
    Order,
    OrderResponse,
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
    main,
    run_loop,
    run_once,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryBloggerProfileRepository,
    InMemoryInteractionRepository,
    InMemoryOrderRepository,
    InMemoryOrderResponseRepository,
    InMemoryUserRepository,
)
from ugc_bot.startup_logging import log_startup_info, safe_config_for_logging


def test_feedback_keyboard() -> None:
    """Ensure feedback keyboard contains callback data and TZ button labels."""

    markup_adv = _feedback_keyboard(
        "adv", UUID("00000000-0000-0000-0000-000000000950")
    )
    first_adv = markup_adv.inline_keyboard[0][0]
    assert "feedback:adv:" in first_adv.callback_data
    assert first_adv.text == "✅ Всё прошло нормально"
    postpone_adv = markup_adv.inline_keyboard[2][0]
    assert postpone_adv.text == "⏳ Ещё не связался"

    markup_blog = _feedback_keyboard(
        "blog", UUID("00000000-0000-0000-0000-000000000950")
    )
    assert markup_blog.inline_keyboard[0][0].text == "✅ Всё прошло нормально"


@pytest.mark.asyncio
async def test_run_once_sends_feedback_requests(fake_tm) -> None:
    """Send feedback to advertiser and blogger."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000960"),
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000961"),
        external_id="11",
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
    await response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000000963"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            responded_at=datetime.now(timezone.utc),
        )
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
        bot,
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
    response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000965"),
        external_id="12",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000966"),
        external_id="13",
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

    await response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000000968"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            responded_at=datetime.now(timezone.utc),
        )
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
        bot,
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
    response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000969"),
        external_id="14",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-00000000096a"),
        external_id="15",
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
    await response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-00000000096e"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            responded_at=datetime.now(timezone.utc),
        )
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
        bot,
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
        bot,
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
        bot,
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
    response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000980"),
        external_id="20",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000981"),
        external_id="21",
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
    await response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000000983"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            responded_at=datetime.now(timezone.utc),
        )
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
        bot,
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
    response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000990"),
        external_id="30",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000991"),
        external_id="31",
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
    await response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000000993"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            responded_at=datetime.now(timezone.utc),
        )
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
        bot,
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
    response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000985"),
        external_id="985",
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
    await response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000000988"),
            order_id=order.order_id,
            blogger_id=blogger_id,
            responded_at=datetime.now(timezone.utc),
        )
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
        bot,
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
    response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000989"),
        external_id="989",
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
    await response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-00000000098c"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            responded_at=datetime.now(timezone.utc),
        )
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
        bot,
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
        bot,
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
        bot,
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
    monkeypatch.setattr(
        "ugc_bot.feedback_scheduler.create_session_factory",
        lambda _, **__: object(),
    )

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
    response_repo = InMemoryOrderResponseRepository()
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
        external_id="30",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000991"),
        external_id="31",
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
    await response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000000993"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            responded_at=datetime.now(timezone.utc),
        )
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
        bot,
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
    """Main returns without creating session when feedback is disabled."""

    monkeypatch.setenv("FEEDBACK_ENABLED", "false")
    monkeypatch.setenv("BOT_TOKEN", "123456:ABCDEF1234567890abcdef1234567890")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://user:pass@localhost:5432/db"
    )
    create_session_factory_mock = Mock()
    monkeypatch.setattr(
        "ugc_bot.feedback_scheduler.create_session_factory",
        create_session_factory_mock,
    )
    main()
    create_session_factory_mock.assert_not_called()

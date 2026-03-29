"""Unit tests for _send_contact_immediately in offer_responses handler."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from tests.helpers.factories import (
    create_test_blogger_profile,
    create_test_order,
    create_test_user,
)
from tests.helpers.fakes import FakeMessengerClient
from tests.helpers.services import build_profile_service
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.telegram.handlers.offer_responses import (
    _send_contact_immediately,
)
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryOrderRepository,
    InMemoryUserRepository,
)

ORDER_ID = UUID("00000000-0000-0000-0000-000000000b00")
ADV_ID = UUID("00000000-0000-0000-0000-000000000b01")
BLOGGER_ID = UUID("00000000-0000-0000-0000-000000000b02")
MANAGER_ID = UUID("00000000-0000-0000-0000-000000000b03")


@pytest.mark.asyncio
async def test_send_contact_uses_manager_telegram_when_manager_present(
    bot_texts_service,
    messenger_client: FakeMessengerClient,
) -> None:
    """Blogger gets manager telegram; advertiser profile not fetched."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()

    await create_test_user(
        user_repo,
        user_id=ADV_ID,
        external_id="801",
        username="advertiser",
        telegram="advertiser_tg",
    )
    blogger = await create_test_user(
        user_repo,
        user_id=BLOGGER_ID,
        external_id="802",
        username="blogger",
    )
    await create_test_blogger_profile(blogger_repo, BLOGGER_ID, confirmed=True)

    manager = User(
        user_id=MANAGER_ID,
        telegram_id="803",
        messenger_type=MessengerType.TELEGRAM,
        username="manager_user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        telegram="manager_tg",
    )

    order = await create_test_order(
        InMemoryOrderRepository(),
        ADV_ID,
        order_id=ORDER_ID,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
    )

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    spy = AsyncMock(
        side_effect=AssertionError(
            "get_advertiser_profile must not be called when manager is set"
        )
    )
    with patch.object(ProfileService, "get_advertiser_profile", spy):
        await _send_contact_immediately(
            order=order,
            blogger_id=BLOGGER_ID,
            blogger_chat_id=blogger.telegram_id,
            response_count=1,
            user_role_service=user_service,
            profile_service=profile_service,
            interaction_service=None,
            messenger_client=messenger_client,
            texts={},
            bot_texts_service=bot_texts_service,
            manager=manager,
        )

    sent_to_blogger = [
        s
        for s in messenger_client.sent_text
        if s["chat_id"] == blogger.telegram_id
    ]
    contact_msg = next(
        (
            s["text"]
            for s in sent_to_blogger
            if "Контакты заказчика" in s["text"]
        ),
        None,
    )
    assert contact_msg is not None, "Blogger should receive a contact message"
    assert "manager_tg" in contact_msg, (
        "Manager telegram should appear in blogger's contact"
    )
    assert "advertiser_tg" not in contact_msg, (
        "Advertiser telegram must NOT appear"
    )


@pytest.mark.asyncio
async def test_send_contact_includes_blogger_phone(
    bot_texts_service,
    messenger_client: FakeMessengerClient,
) -> None:
    """Advertiser message should contain blogger phone when available."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()

    advertiser = await create_test_user(
        user_repo,
        user_id=ADV_ID,
        external_id="801",
        username="advertiser",
        telegram="advertiser_tg",
    )
    blogger = await create_test_user(
        user_repo,
        user_id=BLOGGER_ID,
        external_id="802",
        username="blogger",
    )
    await create_test_blogger_profile(
        blogger_repo, BLOGGER_ID, confirmed=True, phone="+79001234567"
    )

    order = await create_test_order(
        InMemoryOrderRepository(),
        ADV_ID,
        order_id=ORDER_ID,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
    )

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    await _send_contact_immediately(
        order=order,
        blogger_id=BLOGGER_ID,
        blogger_chat_id=blogger.telegram_id,
        response_count=1,
        user_role_service=user_service,
        profile_service=profile_service,
        interaction_service=None,
        messenger_client=messenger_client,
        texts={},
        bot_texts_service=bot_texts_service,
        manager=None,
    )

    sent_to_advertiser = [
        s
        for s in messenger_client.sent_text
        if s["chat_id"] == advertiser.telegram_id
    ]
    contact_msg = next(
        (
            s["text"]
            for s in sent_to_advertiser
            if "Новый отклик" in s["text"] or "Креатор" in s["text"]
        ),
        None,
    )
    assert contact_msg is not None, (
        "Advertiser should receive a contact message"
    )
    assert "+79001234567" in contact_msg, (
        "Blogger phone should appear in advertiser's contact message"
    )

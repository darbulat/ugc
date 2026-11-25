"""Preview navigation must never enter real response or dispatch paths."""

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aiogram import Bot, Router
from aiogram.types import Update

from ugc_bot.application.creator_offer_cards import (
    CALLBACK_PREFIX,
    NEUTRAL_COVER,
    render_public_offer,
)
from ugc_bot.application.creator_offer_preview import (
    PREVIEW_ACTIONS,
    PREVIEW_CALLBACK_PREFIX,
    render_offer_preview,
)
from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.application.ports import OrderRepository
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.creator_offer_preview import (
    ACCESS_DENIED,
    NOT_READY,
    CreatorOfferPreview,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import Order, User
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    OrderType,
    UserStatus,
)
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)


@pytest.fixture
def preview():
    order = Order(
        uuid4(),
        uuid4(),
        OrderType.UGC_PLUS_PLACEMENT,
        "https://private-brand.example.com",
        "Private brand and internal details",
        None,
        5000,
        10,
        OrderStatus.PENDING_MODERATION,
        datetime.now(timezone.utc),
        dispatch_stopped=True,
        brief_link="https://private-brief.example.com",
        product_photo_file_id="private-photo",
        creator_offer_card={
            "title": "Товары для малышей",
            "task": "Продукцию не предоставляем, бартера нет.",
            "brief": "Удалённое видео по материалам бренда",
            "deadline": "По согласованию",
            "usage": "Публикация в блоге автора",
        },
    )
    admin = User(
        uuid4(),
        MessengerType.TELEGRAM,
        "Admin",
        UserStatus.ACTIVE,
        0,
        datetime.now(timezone.utc),
        telegram_id="100",
        admin=True,
    )
    orders = AsyncMock(spec=OrderRepository)
    orders.get_by_id.return_value = order
    users = AsyncMock(spec=UserRoleService)
    users.get_user.return_value = admin
    messenger = AsyncMock()
    messenger.send_offer_card.return_value = "77"
    incoming = IncomingMessage(
        "100", IncomingUser("100", MessengerType.TELEGRAM)
    )
    return SimpleNamespace(
        order=order,
        admin=admin,
        orders=orders,
        users=users,
        messenger=messenger,
        incoming=incoming,
        flow=CreatorOfferPreview(orders, users, messenger),
    )


@pytest.mark.parametrize("locale", ["ru", "en"])
def test_preview_reuses_public_content_and_isolates_all_callbacks(
    preview, locale
):
    for action in PREVIEW_ACTIONS:
        card = render_offer_preview(preview.order, locale, action)
        for row in card.keyboard.rows:
            for button in row:
                if button.callback_data:
                    assert button.callback_data.startswith(
                        PREVIEW_CALLBACK_PREFIX
                    )
                    assert len(button.callback_data.encode()) <= 64
                    assert not button.callback_data.startswith(CALLBACK_PREFIX)
    for view in ("open", "brief", "safe"):
        card = render_offer_preview(preview.order, locale, view)
        assert (
            card.text == render_public_offer(preview.order, locale, view).text
        )
        assert not any(
            button.url for row in card.keyboard.rows for button in row
        )
        assert "private-" not in card.text
    saved = render_offer_preview(preview.order, locale, "done")
    assert saved.keyboard.rows[0][0].callback_data.startswith(
        f"{PREVIEW_CALLBACK_PREFIX}full:"
    )
    brief = render_offer_preview(preview.order, locale, "full")
    assert {
        button.url
        for row in brief.keyboard.rows
        for button in row
        if button.url
    } == {
        preview.order.product_link,
        preview.order.brief_link,
    }
    assert (
        "Предпросмотр отклика" in saved.text or "Response preview" in saved.text
    )
    with pytest.raises(ValueError, match="Unknown preview action"):
        render_offer_preview(preview.order, locale, "activate")


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [False, True])
async def test_send_preview_is_private_and_does_not_register_dispatch(
    preview, approved
):
    if approved:
        preview.orders.get_by_id.return_value = replace(
            preview.order,
            creator_offer_card={
                **preview.order.creator_offer_card,
                "photo": "approved",
            },
        )
    message_id = await preview.flow.send(
        preview.incoming, str(preview.order.order_id)
    )
    assert message_id == "77"
    preview.messenger.send_text.assert_not_awaited()
    preview.messenger.send_offer_card.assert_awaited_once()
    call = preview.messenger.send_offer_card.call_args
    assert call.args[0] == "100"
    assert call.args[2] == ("private-photo" if approved else NEUTRAL_COVER)
    assert all(call[0] == "get_by_id" for call in preview.orders.mock_calls)


@pytest.mark.asyncio
async def test_full_preview_navigation_and_repeated_confirmation_only_read(
    preview,
):
    original = replace(preview.order)
    incoming = IncomingCallback(
        "query", "100", preview.incoming.user, message_id="77"
    )
    for action in (
        "brief",
        "safe",
        "open",
        "confirm",
        "done",
        "done",
        "open",
        "skip",
        "s_price",
        "s_format",
        "s_time",
        "s_product",
        "s_brand",
    ):
        await preview.flow.handle(
            replace(
                incoming,
                data=f"{PREVIEW_CALLBACK_PREFIX}{action}:{preview.order.order_id}",
            )
        )
    assert preview.messenger.edit_offer_card.await_count == 13
    assert all(call[0] == "get_by_id" for call in preview.orders.mock_calls)
    assert preview.order == original
    assert preview.order.status == OrderStatus.PENDING_MODERATION
    assert preview.order.dispatch_stopped
    preview.messenger.send_text.assert_not_awaited()
    preview.messenger.send_offer_card.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", [None, "nonadmin", "blocked", "paused"])
async def test_unauthorized_actor_cannot_send_or_open_preview(preview, actor):
    account = {
        None: None,
        "nonadmin": replace(preview.admin, admin=False),
        "blocked": replace(preview.admin, status=UserStatus.BLOCKED),
        "paused": replace(preview.admin, status=UserStatus.PAUSE),
    }[actor]
    preview.users.get_user.return_value = account
    await preview.flow.send(preview.incoming, str(preview.order.order_id))
    await preview.flow.handle(
        IncomingCallback(
            "q",
            "100",
            preview.incoming.user,
            data=f"{PREVIEW_CALLBACK_PREFIX}done:{preview.order.order_id}",
            message_id="77",
        )
    )
    preview.orders.get_by_id.assert_not_awaited()
    preview.messenger.send_offer_card.assert_not_awaited()
    preview.messenger.edit_offer_card.assert_not_awaited()
    assert (
        preview.messenger.answer_callback.call_args.kwargs["text"]
        == ACCESS_DENIED
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "chat_id,platform",
    [
        ("-100", MessengerType.TELEGRAM),
        ("101", MessengerType.TELEGRAM),
        ("100", MessengerType.MAX),
    ],
)
async def test_groups_forwarded_chats_and_other_platforms_are_denied(
    preview, chat_id, platform
):
    user = replace(preview.incoming.user, messenger_type=platform)
    await preview.flow.send(
        replace(preview.incoming, chat_id=chat_id, user=user),
        str(preview.order.order_id),
    )
    await preview.flow.handle(
        IncomingCallback(
            "q",
            chat_id,
            user,
            data=f"{PREVIEW_CALLBACK_PREFIX}done:{preview.order.order_id}",
            message_id="77",
        )
    )
    preview.users.get_user.assert_not_awaited()
    preview.orders.get_by_id.assert_not_awaited()
    preview.messenger.edit_offer_card.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        "offer_card:done:bad",
        "offer_preview:activate:bad",
        "offer_preview:open:bad",
    ],
)
async def test_invalid_or_production_callback_cannot_enter_preview(
    preview, data
):
    await preview.flow.handle(
        IncomingCallback(
            "q", "100", preview.incoming.user, data=data, message_id="77"
        )
    )
    preview.orders.get_by_id.assert_not_awaited()
    preview.messenger.edit_offer_card.assert_not_awaited()
    assert (
        preview.messenger.answer_callback.call_args.kwargs["text"] == NOT_READY
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_order", [None, "deleted", "empty", "incomplete"])
async def test_missing_deleted_and_incomplete_orders_cannot_be_previewed(
    preview, bad_order
):
    orders = {
        None: None,
        "deleted": replace(preview.order, status=OrderStatus.DELETED),
        "empty": replace(preview.order, creator_offer_card={}),
        "incomplete": replace(
            preview.order, creator_offer_card={"title": "Draft"}
        ),
    }
    preview.orders.get_by_id.return_value = orders[bad_order]
    await preview.flow.send(preview.incoming, str(preview.order.order_id))
    await preview.flow.handle(
        IncomingCallback(
            "q",
            "100",
            preview.incoming.user,
            data=f"{PREVIEW_CALLBACK_PREFIX}done:{preview.order.order_id}",
            message_id="77",
        )
    )
    preview.messenger.send_offer_card.assert_not_awaited()
    preview.messenger.edit_offer_card.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_dispatcher_routes_preview_before_state_catchalls(
    preview, monkeypatch
):
    import ugc_bot.app as app_module

    responses, dispatch, followup = AsyncMock(), AsyncMock(), AsyncMock()
    services = {
        "metrics_collector": MagicMock(),
        "order_repo": preview.orders,
        "user_role_service": preview.users,
        "offer_response_service": responses,
        "offer_dispatch_service": dispatch,
        "profile_service": AsyncMock(),
        "client_followup_service": followup,
    }
    monkeypatch.setattr(
        app_module,
        "Container",
        lambda _: SimpleNamespace(build_bot_services=lambda: services),
    )
    for name, original in list(vars(app_module).items()):
        if name.endswith("_router") and isinstance(original, Router):
            fresh = Router()
            for observer, value in original.observers.items():
                fresh.observers[observer].handlers.extend(value.handlers)
            monkeypatch.setattr(app_module, name, fresh)
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "123:" + "A" * 35,
            "DATABASE_URL": "sqlite:///unused-preview",
            "KAFKA_ENABLED": False,
        }
    )
    dispatcher = app_module.build_dispatcher(config)
    async with Bot(config.bot.bot_token) as bot:
        bot.send_message = AsyncMock()
        bot.send_photo = AsyncMock(return_value=SimpleNamespace(message_id=77))
        bot.edit_message_caption = AsyncMock()
        bot.answer_callback_query = AsyncMock()
        dispatcher["messenger_client"] = TelegramMessengerClient(bot)
        state = dispatcher.fsm.get_context(bot=bot, chat_id=100, user_id=100)
        await state.set_state("AdminWriteStates:waiting_text")
        await state.set_data({"target_user_id": "200"})
        person = {"id": 100, "is_bot": False, "first_name": "Admin"}
        base = {
            "message_id": 77,
            "date": 1792800000,
            "chat": {"id": 100, "type": "private"},
            "from": person,
        }
        command = Update.model_validate(
            {
                "update_id": 1,
                "message": {
                    **base,
                    "text": "/preview_offer " + str(preview.order.order_id),
                    "entities": [
                        {"type": "bot_command", "offset": 0, "length": 14}
                    ],
                },
            }
        )
        await dispatcher.feed_update(bot, command)
        bot.send_photo.assert_awaited_once()
        for index, action in enumerate(
            ("brief", "safe", "confirm", "done", "open"), start=2
        ):
            callback = Update.model_validate(
                {
                    "update_id": index,
                    "callback_query": {
                        "id": str(index),
                        "from": person,
                        "chat_instance": "test",
                        "message": base,
                        "data": (
                            f"{PREVIEW_CALLBACK_PREFIX}{action}:"
                            f"{preview.order.order_id}"
                        ),
                    },
                }
            )
            await dispatcher.feed_update(bot, callback)
        assert bot.edit_message_caption.await_count == 5
        assert (
            "Предпросмотр отклика"
            in bot.edit_message_caption.await_args_list[3].kwargs["caption"]
        )
        assert await state.get_state() == "AdminWriteStates:waiting_text"
        assert await state.get_data() == {"target_user_id": "200"}
        assert not responses.mock_calls and not dispatch.mock_calls
        followup.record_activity.assert_not_awaited()
        assert all(call[0] == "get_by_id" for call in preview.orders.mock_calls)

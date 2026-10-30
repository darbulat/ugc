"""Customer activity records only authenticated active advertiser visits."""

from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.bot.customer_activity import record_customer_visit
from ugc_bot.domain.enums import MessengerType


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", [MessengerType.TELEGRAM, MessengerType.MAX])
@pytest.mark.parametrize("event", ["menu", "brief"])
async def test_customer_menu_and_unconfirmed_brief_record_native_identity(
    channel, event
):
    user_id = uuid4()
    incoming = IncomingCallback(
        "cb",
        "12",
        IncomingUser("12", channel),
        data="role:advertiser" if event == "menu" else "profile:menu:order",
    )
    followup = NS(record_activity=AsyncMock())
    deps = dict(
        user_role_service=NS(
            get_user=AsyncMock(
                return_value=NS(user_id=user_id, status="active")
            )
        ),
        profile_service=NS(
            get_advertiser_profile=AsyncMock(
                return_value=NS(agreement_confirmed_at=None)
            )
        ),
        client_followup_service=followup,
    )
    await record_customer_visit(incoming, deps)
    followup.record_activity.assert_awaited_once()
    assert followup.record_activity.call_args.args == (
        user_id,
        "menu" if event == "menu" else "brief_opened",
    )
    assert (
        followup.record_activity.call_args.kwargs["principal"].platform
        == channel.value
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "unknown",
        "blocked",
        "creator",
        "unrelated",
        "confirmed_brief",
        "disabled",
    ],
)
async def test_non_customer_and_irrelevant_actions_do_not_record(case):
    followup = NS(record_activity=AsyncMock())
    user = NS(
        user_id=uuid4(), status="blocked" if case == "blocked" else "active"
    )
    profile = NS(
        agreement_confirmed_at=datetime.now(UTC)
        if case == "confirmed_brief"
        else None
    )
    incoming = IncomingMessage(
        "12",
        IncomingUser("12", MessengerType.TELEGRAM),
        text="/create_order"
        if case == "confirmed_brief"
        else ("hi" if case == "unrelated" else "/advertiser"),
    )
    deps = dict(
        user_role_service=NS(
            get_user=AsyncMock(return_value=None if case == "unknown" else user)
        ),
        profile_service=NS(
            get_advertiser_profile=AsyncMock(
                return_value=None if case == "creator" else profile
            )
        ),
        client_followup_service=None if case == "disabled" else followup,
    )
    await record_customer_visit(incoming, deps)
    followup.record_activity.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("callback_visit", [False, True])
async def test_actual_telegram_update_middleware_records_customer_visit(
    callback_visit,
):
    from aiogram.types import CallbackQuery, Chat, Message, Update, User

    from ugc_bot.bot.telegram.middleware.locale import LocaleMiddleware

    native_user = User(id=12, is_bot=False, first_name="Client")
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=12, type="private"),
        from_user=native_user,
        text="/advertiser",
    )
    update = (
        Update(
            update_id=1,
            callback_query=CallbackQuery(
                id="cb",
                from_user=native_user,
                chat_instance="chat",
                message=message,
                data="role:advertiser",
            ),
        )
        if callback_visit
        else Update(update_id=1, message=message)
    )
    user = NS(user_id=uuid4(), status="active", language="en", country="RU")
    roles = NS(
        get_user=AsyncMock(return_value=user), update_telegram=AsyncMock()
    )
    followup = NS(record_activity=AsyncMock())
    data = dict(
        event_from_user=native_user,
        user_role_service=roles,
        profile_service=NS(
            get_advertiser_profile=AsyncMock(
                return_value=NS(agreement_confirmed_at=datetime.now(UTC))
            )
        ),
        client_followup_service=followup,
    )
    handler = AsyncMock(return_value="menu delivered")
    assert await LocaleMiddleware()(handler, update, data) == "menu delivered"
    followup.record_activity.assert_awaited_once()
    assert (
        followup.record_activity.call_args.kwargs["principal"].external_id
        == "12"
    )
    handler.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("callback_visit", [False, True])
async def test_actual_max_router_records_valid_customer_visit(callback_visit):
    from ugc_bot.bot.max.router import MaxRouter

    router = MaxRouter()
    handled = AsyncMock()

    @router.message(lambda incoming: incoming.text == "/advertiser")
    async def menu_message(incoming, deps):
        await handled()

    @router.callback(lambda incoming: incoming.data == "role:advertiser")
    async def menu_callback(incoming, deps):
        await handled()

    followup = NS(record_activity=AsyncMock())
    deps = dict(
        user_role_service=NS(
            get_user=AsyncMock(
                return_value=NS(user_id=uuid4(), status="active")
            )
        ),
        profile_service=NS(
            get_advertiser_profile=AsyncMock(
                return_value=NS(agreement_confirmed_at=None)
            )
        ),
        client_followup_service=followup,
    )
    user = IncomingUser("12", MessengerType.MAX)
    if callback_visit:
        await router.route_callback(
            IncomingCallback("cb", "12", user, data="role:advertiser"), deps
        )
    else:
        await router.route_message(
            IncomingMessage("12", user, text="/advertiser"), deps
        )
    followup.record_activity.assert_awaited_once()
    handled.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [False, True])
async def test_agreement_acceptance_only_records_real_brief_state(valid):
    incoming = IncomingCallback(
        "cb",
        "12",
        IncomingUser("12", MessengerType.TELEGRAM),
        data="order:agree",
    )
    followup = NS(record_activity=AsyncMock())
    state = NS(
        get_state=AsyncMock(
            return_value="AdvertiserRegistrationStates:agreements"
            if valid
            else "other"
        ),
        get_data=AsyncMock(return_value={"flow_type": "order_creation"}),
    )
    deps = dict(
        user_role_service=NS(
            get_user=AsyncMock(
                return_value=NS(user_id=uuid4(), status="active")
            )
        ),
        profile_service=NS(
            get_advertiser_profile=AsyncMock(
                return_value=NS(agreement_confirmed_at=None)
            )
        ),
        client_followup_service=followup,
        state=state,
    )
    await record_customer_visit(incoming, deps)
    assert followup.record_activity.await_count == int(valid)


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", ["ru", "en", "kk", "be", "uz"])
async def test_localized_menu_button_is_customer_activity(locale):
    from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS

    incoming = IncomingMessage(
        "12",
        IncomingUser("12", MessengerType.TELEGRAM),
        text=DEFAULT_TEXTS[locale]["btn_advertiser"],
    )
    followup = NS(record_activity=AsyncMock())
    deps = dict(
        user_role_service=NS(
            get_user=AsyncMock(
                return_value=NS(user_id=uuid4(), status="active")
            )
        ),
        profile_service=NS(
            get_advertiser_profile=AsyncMock(
                return_value=NS(agreement_confirmed_at=None)
            )
        ),
        client_followup_service=followup,
    )
    await record_customer_visit(incoming, deps)
    followup.record_activity.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "callback_data", ["profile:menu:profile", "profile:menu:orders", "support"]
)
async def test_generic_multirole_callbacks_do_not_start_purchase_followup(
    callback_data,
):
    followup = NS(record_activity=AsyncMock())
    deps = dict(
        user_role_service=NS(
            get_user=AsyncMock(
                return_value=NS(user_id=uuid4(), status="active")
            )
        ),
        profile_service=NS(
            get_advertiser_profile=AsyncMock(
                return_value=NS(agreement_confirmed_at=None)
            )
        ),
        client_followup_service=followup,
    )
    await record_customer_visit(
        IncomingCallback(
            "cb",
            "12",
            IncomingUser("12", MessengerType.TELEGRAM),
            data=callback_data,
        ),
        deps,
    )
    followup.record_activity.assert_not_awaited()
    deps["profile_service"].get_advertiser_profile.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["/profile", "/support", "/my_orders"])
async def test_generic_multirole_commands_do_not_start_purchase_followup(text):
    followup = NS(record_activity=AsyncMock())
    deps = dict(
        user_role_service=NS(
            get_user=AsyncMock(
                return_value=NS(user_id=uuid4(), status="active")
            )
        ),
        profile_service=NS(
            get_advertiser_profile=AsyncMock(
                return_value=NS(agreement_confirmed_at=None)
            )
        ),
        client_followup_service=followup,
    )
    await record_customer_visit(
        IncomingMessage(
            "12", IncomingUser("12", MessengerType.TELEGRAM), text=text
        ),
        deps,
    )
    followup.record_activity.assert_not_awaited()
    deps["profile_service"].get_advertiser_profile.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["telegram", "max"])
@pytest.mark.parametrize(
    "failure",
    [PermissionError("secret-contact"), RuntimeError("secret-contact")],
)
async def test_auxiliary_activity_error_does_not_block_menu(
    channel, failure, caplog
):
    from aiogram.types import Chat, Message, Update, User

    from ugc_bot.bot.max.router import MaxRouter
    from ugc_bot.bot.telegram.middleware.locale import LocaleMiddleware

    followup = NS(record_activity=AsyncMock(side_effect=failure))
    user = NS(user_id=uuid4(), status="active", language="en", country="RU")
    roles = NS(
        get_user=AsyncMock(return_value=user), update_telegram=AsyncMock()
    )
    deps = dict(
        user_role_service=roles,
        profile_service=NS(
            get_advertiser_profile=AsyncMock(
                return_value=NS(agreement_confirmed_at=None)
            )
        ),
        client_followup_service=followup,
    )
    handled = AsyncMock(return_value="delivered")
    if channel == "max":
        router = MaxRouter()

        @router.message(lambda incoming: incoming.text == "/advertiser")
        async def menu(incoming, deps):
            await handled()

        await router.route_message(
            IncomingMessage(
                "12", IncomingUser("12", MessengerType.MAX), text="/advertiser"
            ),
            deps,
        )
    else:
        native_user = User(id=12, is_bot=False, first_name="Client")
        native = Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=Chat(id=12, type="private"),
            from_user=native_user,
            text="/advertiser",
        )
        deps["event_from_user"] = native_user
        assert (
            await LocaleMiddleware()(
                handled, Update(update_id=1, message=native), deps
            )
            == "delivered"
        )
    handled.assert_awaited_once()
    assert "Customer activity unavailable" in caplog.text
    assert "secret-contact" not in caplog.text

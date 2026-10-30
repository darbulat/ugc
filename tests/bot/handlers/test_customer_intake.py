"""Authenticated bot intake and customer actions on both channels."""

from datetime import UTC, datetime
from decimal import localcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from tests.helpers.fakes import FakeFSMContext
from ugc_bot.application.messenger.dto import IncomingMessage, IncomingUser
from ugc_bot.bot.customer_intake import (
    ask_platforms,
    choose_platforms,
    complete_intake,
    record_activity,
)
from ugc_bot.bot.telegram.handlers.order_creation_states import (
    OrderCreationStates,
)
from ugc_bot.domain.enums import MessengerType
from ugc_bot.domain.order_intake import (
    EligibleOrderPolicies,
    EligibleOrderPolicy,
)


@pytest.fixture
def flow():
    user_id = uuid4()
    incoming = IncomingMessage(
        "12", IncomingUser("12", MessengerType.TELEGRAM), text="2"
    )
    state = FakeFSMContext()
    state._data.update(
        user_id=str(user_id),
        bloggers_needed=10,
        order_type="stories",
        offer_text="A sufficiently detailed campaign brief",
        price=300,
        product_link="https://example.com",
        geography="Москва",
    )
    service = SimpleNamespace(
        eligible_policies=AsyncMock(
            return_value=EligibleOrderPolicies(
                "RUB",
                False,
                (
                    EligibleOrderPolicy(
                        "v1", "terms", datetime.now(UTC), 3600, 50000, 170000
                    ),
                ),
            )
        ),
        create=AsyncMock(),
    )
    messenger = SimpleNamespace(send_text=AsyncMock())
    return user_id, incoming, state, service, messenger


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event", ["brief_opened", "brief_changed", "order_created"]
)
async def test_activity_failure_does_not_block_customer_intake(
    flow, event, caplog
):
    user_id, incoming, _, _, _ = flow
    followup = SimpleNamespace(
        record_activity=AsyncMock(side_effect=RuntimeError("private details"))
    )
    await record_activity(incoming, user_id, followup, event)
    followup.record_activity.assert_awaited_once()
    assert "private details" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "platform", [MessengerType.TELEGRAM, MessengerType.MAX]
)
async def test_bot_order_and_followup_share_brief_intent(flow, platform):
    _, incoming, state, service, messenger = flow
    intent = uuid4()
    state._data["intake_funnel_id"] = str(intent)
    incoming = IncomingMessage(
        "12", IncomingUser("12", platform), text="telegram"
    )
    await ask_platforms(incoming, state, messenger, service)
    await choose_platforms(incoming, state, messenger, service)
    service.create.return_value = SimpleNamespace(
        order_id=uuid4(), selection_base_minor=500000, total_minor=500000
    )
    followup = SimpleNamespace(
        register_brief=AsyncMock(return_value=uuid4()),
        record_activity=AsyncMock(),
    )
    await complete_intake(
        IncomingMessage("12", incoming.user, text="0"),
        state,
        messenger,
        service,
        followup,
    )
    assert service.create.call_args.args[0].funnel_id == intent
    assert followup.record_activity.call_args.kwargs["intent_id"] == intent


@pytest.mark.asyncio
async def test_platform_then_offer_uses_server_quote(flow):
    user_id, incoming, state, service, messenger = flow
    await ask_platforms(incoming, state, messenger, service)
    assert state.state == OrderCreationStates.platforms.state
    incoming = IncomingMessage(
        incoming.chat_id, incoming.user, text="telegram, vk"
    )
    await choose_platforms(incoming, state, messenger, service)
    assert state.state == OrderCreationStates.accompaniment.state
    assert "1700" in messenger.send_text.call_args.kwargs["text"]
    assert (
        "оплачиваются вместе в одном счёте"
        in (messenger.send_text.call_args.kwargs["text"])
    )
    assert (
        service.eligible_policies.call_args.kwargs["principal"].user_id
        == user_id
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "platform", [MessengerType.TELEGRAM, MessengerType.MAX]
)
@pytest.mark.parametrize(
    "locale,statement",
    [
        ("ru", "оплачиваются вместе в одном счёте"),
        ("en", "paid together in one invoice"),
        ("kk", "бір шотпен бірге төленеді"),
        ("be", "аплачваюцца разам у адным рахунку"),
        ("uz", "bitta hisobda birga to‘lanadi"),
    ],
)
async def test_payment_timing_is_localized_in_both_bots(
    flow, platform, locale, statement
):
    _, incoming, state, service, messenger = flow
    state._data["locale"] = locale
    incoming = IncomingMessage(
        incoming.chat_id, IncomingUser("12", platform), text="telegram"
    )
    await ask_platforms(incoming, state, messenger, service)
    await choose_platforms(incoming, state, messenger, service)
    assert statement in messenger.send_text.call_args.kwargs["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "platform", [MessengerType.TELEGRAM, MessengerType.MAX]
)
@pytest.mark.parametrize("locale", ["ru", "en", "kk", "be", "uz"])
@pytest.mark.parametrize(
    "count,selection_minor,unit_minor,selection,unit,accompaniment,total",
    [
        (10, 1, 60000, "0.10", "600.00", "1200.00", "1200.10"),
        (
            10,
            1234567,
            17000001,
            "123456.70",
            "170000.01",
            "340000.02",
            "463456.72",
        ),
        (
            200,
            49399999,
            60001,
            "98799998.00",
            "600.01",
            "1200.02",
            "98801198.02",
        ),
    ],
)
async def test_custom_prices_show_exact_cents_in_offer_and_receipt(
    flow,
    platform,
    locale,
    count,
    selection_minor,
    unit_minor,
    selection,
    unit,
    accompaniment,
    total,
):
    _, incoming, state, service, messenger = flow
    state._data.update(locale=locale, bloggers_needed=count, price=1)
    service.eligible_policies.return_value = EligibleOrderPolicies(
        "RUB",
        False,
        (
            EligibleOrderPolicy(
                "v1",
                "terms",
                datetime.now(UTC),
                3600,
                selection_minor,
                unit_minor,
            ),
        ),
    )
    incoming = IncomingMessage(
        incoming.chat_id, IncomingUser("12", platform), text="telegram"
    )
    with localcontext() as context:
        context.prec = 4
        await ask_platforms(incoming, state, messenger, service)
        await choose_platforms(incoming, state, messenger, service)
        offer = messenger.send_text.call_args.kwargs["text"]
        assert selection in offer and unit in offer

        service.create.return_value = SimpleNamespace(
            order_id=uuid4(),
            selection_base_minor=selection_minor * count,
            total_minor=selection_minor * count + unit_minor * 2,
        )
        await complete_intake(
            IncomingMessage(incoming.chat_id, incoming.user, text="2"),
            state,
            messenger,
            service,
        )
        receipt = messenger.send_text.call_args.kwargs["text"]
        assert selection in receipt
        assert accompaniment in receipt
        assert total in receipt


@pytest.mark.asyncio
async def test_complete_persists_retry_snapshot_and_subset_before_failure(flow):
    _, incoming, state, service, messenger = flow
    await ask_platforms(incoming, state, messenger, service)
    await choose_platforms(
        IncomingMessage("12", incoming.user, text="telegram"),
        state,
        messenger,
        service,
    )
    service.create.side_effect = ValueError("network")
    await complete_intake(incoming, state, messenger, service)
    first = service.create.call_args.args[0]
    assert first.accompaniment_ordinals == frozenset({1, 2})
    assert first.position_count == 10
    assert first.order_type.value == "stories"
    assert first.targeting.platforms == ("telegram",)
    assert state._data["intake_operation_key"]
    await complete_intake(incoming, state, messenger, service)
    assert service.create.call_args.args[0] == first


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [3, 7, 14])
async def test_native_preview_deadline_is_preserved_in_intake(flow, days):
    _, incoming, state, service, messenger = flow
    deadline = f"превью в течение {days} дней после согласования"
    state._data["deadlines"] = deadline
    await ask_platforms(incoming, state, messenger, service)
    await choose_platforms(
        IncomingMessage("12", incoming.user, text="telegram"),
        state,
        messenger,
        service,
    )
    service.create.side_effect = ValueError("synthetic")
    await complete_intake(incoming, state, messenger, service)
    command = service.create.call_args.args[0]
    assert command.targeting.order_fields()["deadlines"] == deadline
    assert command.targeting.payload()["deadlines"] == deadline


@pytest.mark.asyncio
async def test_success_leaves_input_state_but_keeps_saved_order(flow):
    _, incoming, state, service, messenger = flow
    await ask_platforms(incoming, state, messenger, service)
    await choose_platforms(
        IncomingMessage("12", incoming.user, text="telegram"),
        state,
        messenger,
        service,
    )
    order_id = uuid4()
    service.create.return_value = SimpleNamespace(
        order_id=order_id, total_minor=740000, selection_base_minor=500000
    )
    await complete_intake(incoming, state, messenger, service)
    assert state.state == OrderCreationStates.accompaniment.state
    assert state._data["saved_order_id"] == str(order_id)
    assert state._data["intake_operation_key"]
    assert (
        "оплачиваются вместе в одном счёте"
        in (messenger.send_text.call_args.kwargs["text"])
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("/stop_reminders", "handle_stop_reminders"),
        ("/support_order", "handle_customer_help"),
        ("/services", "handle_customer_services"),
    ],
)
async def test_customer_commands_take_priority_over_active_flows(
    command, expected
):
    from aiogram.types import Chat, Message, MessageEntity
    from aiogram.types import User as TelegramUser

    from ugc_bot.bot.telegram.handlers.order_creation import router

    event = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=1, type="private"),
        from_user=TelegramUser(id=1, is_bot=False, first_name="Test"),
        text=command,
        entities=[
            MessageEntity(type="bot_command", offset=0, length=len(command))
        ],
    )
    bot = SimpleNamespace(me=SimpleNamespace(username="synthetic_bot"))
    states = [s.state for s in OrderCreationStates.__all_states__] + [
        "CustomerSupport:reason",
        "CustomerSupport:contact",
    ]
    for state in states:
        for handler in router.message.handlers:
            matches, _ = await handler.check(event, bot=bot, raw_state=state)
            if matches:
                assert handler.callback.__name__ == expected, state
                break
        else:
            pytest.fail(f"No handler for {command} in {state}")


@pytest.mark.asyncio
async def test_unavailable_policy_never_creates(flow):
    _, incoming, state, service, messenger = flow
    service.eligible_policies.return_value = EligibleOrderPolicies(
        "RUB", True, ()
    )
    await ask_platforms(incoming, state, messenger, service)
    service.create.assert_not_awaited()
    assert "поддерж" in messenger.send_text.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_invalid_platform_and_accompaniment_do_not_create(flow):
    _, incoming, state, service, messenger = flow
    await ask_platforms(incoming, state, messenger, service)
    await choose_platforms(
        IncomingMessage("12", incoming.user, text="evil"),
        state,
        messenger,
        service,
    )
    assert state.state == OrderCreationStates.platforms.state
    await complete_intake(
        IncomingMessage("12", incoming.user, text="11"),
        state,
        messenger,
        service,
    )
    service.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_document_upload_keeps_only_trusted_token(flow):
    from io import BytesIO

    from ugc_bot.bot.customer_intake import upload_telegram_image

    user_id, incoming, state, service, messenger = flow
    token = uuid4()
    bot = SimpleNamespace(
        download=AsyncMock(return_value=BytesIO(b"jpeg bytes"))
    )
    image = SimpleNamespace(
        upload=AsyncMock(return_value=SimpleNamespace(token=token))
    )
    message = SimpleNamespace(
        bot=bot,
        document=SimpleNamespace(file_id="untrusted-file-id", file_size=100),
        photo=None,
    )
    assert await upload_telegram_image(
        message, incoming, state, messenger, image
    )
    assert state._data["image_token"] == str(token)
    assert state._data.get("product_photo_file_id") is None
    assert image.upload.call_args.args == (user_id, b"jpeg bytes")
    image.upload.side_effect = ValueError("image_dimensions")
    assert not await upload_telegram_image(
        message, incoming, state, messenger, image
    )
    assert "1080" in messenger.send_text.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_support_uses_owner_and_retry_key(flow):
    from ugc_bot.bot.customer_actions import send_support

    user_id, incoming, state, _, messenger = flow
    order_id = uuid4()
    state._data.update(
        support_order_id=str(order_id),
        support_reason="The creator missed the deadline",
        support_operation_key="support-op",
    )
    service = SimpleNamespace(create=AsyncMock(return_value={"number": "S-12"}))
    user = SimpleNamespace(user_id=user_id)
    roles = SimpleNamespace(get_user=AsyncMock(return_value=user))
    await send_support(
        IncomingMessage("12", incoming.user, text="@contact"),
        state,
        messenger,
        roles,
        service,
    )
    call = service.create.call_args
    assert call.args[0] == user_id
    assert call.args[1].reason == "The creator missed the deadline"
    assert call.args[1].contact_reference == "@contact"
    assert call.args[1].operation_key == "support-op"
    assert call.kwargs["principal"].external_id == "12"
    assert "S-12" in messenger.send_text.call_args.kwargs["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", [MessengerType.TELEGRAM, MessengerType.MAX])
@pytest.mark.parametrize("count", [0, 1, 10])
async def test_saved_quote_success_has_no_uuid_and_activity(
    flow, channel, count
):
    from ugc_bot.domain.order_intake import IntakeItem, OrderIntakeResult

    user_id, incoming, state, service, messenger = flow
    incoming = IncomingMessage(
        "12", IncomingUser("12", channel), text=str(count)
    )
    await ask_platforms(incoming, state, messenger, service)
    await choose_platforms(
        IncomingMessage("12", incoming.user, text="vk"),
        state,
        messenger,
        service,
    )
    command_id = uuid4()
    service.create.return_value = OrderIntakeResult(
        uuid4(),
        command_id,
        datetime.now(UTC),
        "RUB",
        "v1",
        datetime.now(UTC),
        "terms",
        tuple(
            IntakeItem(uuid4(), n, 50000, 170000 if n <= count else 0)
            for n in range(1, 11)
        ),
        None,
    )
    followup = SimpleNamespace(record_activity=AsyncMock())
    result = await complete_intake(
        incoming, state, messenger, service, followup
    )
    assert result.order_id == command_id
    text = messenger.send_text.call_args.kwargs["text"]
    assert str(command_id) not in text
    assert str(command_id).replace("-", "")[:8].upper() in text
    followup.record_activity.assert_awaited_once()
    assert (
        followup.record_activity.call_args.kwargs["principal"].platform
        == channel.value
    )
    assert service.create.call_args.args[0].service_mode == (
        "with_manager" if count else "self_service"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "policy_error",
    [
        ValueError("missing"),
        PermissionError("forbidden"),
        LookupError("policy"),
    ],
)
async def test_policy_authorization_failure_keeps_brief(flow, policy_error):
    _, incoming, state, service, messenger = flow
    service.eligible_policies.side_effect = policy_error
    await ask_platforms(incoming, state, messenger, service)
    service.create.assert_not_awaited()
    assert state._data["offer_text"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["none", "service", "large", "missing", "format", "forbidden"]
)
async def test_image_failure_preserves_previous_token(flow, case):
    from io import BytesIO

    from ugc_bot.bot.customer_intake import upload_telegram_image

    _, incoming, state, _, messenger = flow
    state._data["image_token"] = "previous"
    media = SimpleNamespace(
        file_id="a", file_size=5_000_001 if case == "large" else 10
    )
    bot = SimpleNamespace(
        download=AsyncMock(
            return_value=None if case == "missing" else BytesIO(b"x")
        )
    )
    image = SimpleNamespace(
        upload=AsyncMock(
            side_effect=ValueError("image_jpeg_required")
            if case == "format"
            else PermissionError("forbidden")
        )
    )
    message = SimpleNamespace(
        bot=bot, document=None if case == "none" else media, photo=[]
    )
    assert not await upload_telegram_image(
        message,
        incoming,
        state,
        messenger,
        None if case == "service" else image,
    )
    assert state._data["image_token"] == "previous"


@pytest.mark.asyncio
async def test_help_lists_only_owned_and_support_rejects_forgery(flow):
    from ugc_bot.application.messenger.dto import IncomingCallback
    from ugc_bot.bot import customer_actions as actions

    user_id, incoming, state, _, messenger = flow
    user = SimpleNamespace(user_id=user_id, language="en")
    roles = SimpleNamespace(get_user=AsyncMock(return_value=user))
    order = SimpleNamespace(
        order_id=uuid4(),
        advertiser_id=user_id,
        offer_text="Test",
        created_at=datetime.now(UTC),
    )
    orders = SimpleNamespace(
        list_by_advertiser=AsyncMock(return_value=[order]),
        get_order=AsyncMock(return_value=order),
    )
    await actions.show_help(incoming, messenger, roles, orders)
    assert messenger.send_text.call_args.kwargs["keyboard"].rows
    cb = IncomingCallback(
        "cb",
        "12",
        incoming.user,
        data=f"{actions.SUPPORT_PREFIX}{order.order_id}",
    )
    await actions.begin_support(cb, state, messenger, roles, orders)
    assert state.state == actions.SUPPORT_REASON
    await actions.support_reason(
        IncomingMessage("12", incoming.user, text=""), state, messenger
    )
    assert state.state == actions.SUPPORT_REASON
    await actions.support_reason(
        IncomingMessage("12", incoming.user, text="Missing creator"),
        state,
        messenger,
    )
    assert state.state == actions.SUPPORT_CONTACT
    order.advertiser_id = uuid4()
    await actions.begin_support(cb, state, messenger, roles, orders)
    assert "unavailable" in messenger.send_text.call_args.kwargs["text"]
    orders.list_by_advertiser.return_value = []
    await actions.show_help(incoming, messenger, roles, orders)
    assert messenger.send_text.call_args.kwargs["keyboard"] is None
    roles.get_user.return_value = None
    await actions.show_help(incoming, messenger, roles, orders)


@pytest.mark.asyncio
async def test_support_failure_retry_and_optout(flow):
    from ugc_bot.bot import customer_actions as actions

    user_id, incoming, state, _, messenger = flow
    state._data.update(
        support_order_id=str(uuid4()),
        support_reason="Issue",
        support_operation_key="op",
    )
    roles = SimpleNamespace(
        get_user=AsyncMock(
            return_value=SimpleNamespace(user_id=user_id, language="ru")
        )
    )
    support = SimpleNamespace(
        create=AsyncMock(side_effect=PermissionError("owner"))
    )
    await actions.send_support(incoming, state, messenger, roles, None)
    await actions.send_support(incoming, state, messenger, roles, support)
    assert state._data["support_operation_key"] == "op"
    support.create.side_effect = None
    support.create.return_value = {"request_id": uuid4()}
    await actions.send_support(incoming, state, messenger, roles, support)
    followup = SimpleNamespace(optout=AsyncMock())
    await actions.stop_reminders(incoming, messenger, roles, followup)
    followup.optout.assert_awaited_once()
    await actions.stop_reminders(incoming, messenger, roles, None)
    roles.get_user.return_value = None
    await actions.send_support(incoming, state, messenger, roles, support)
    await actions.stop_reminders(incoming, messenger, roles, followup)


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", [MessengerType.TELEGRAM, MessengerType.MAX])
@pytest.mark.parametrize("base", ["", "https://bot.example"])
async def test_service_link_uses_channel_and_locale(flow, channel, base):
    from ugc_bot.bot.customer_actions import show_services

    _, incoming, _, _, messenger = flow
    await show_services(
        IncomingMessage("12", IncomingUser("12", channel)),
        messenger,
        SimpleNamespace(webhook=SimpleNamespace(webhook_base_url=base)),
        "en",
    )
    result = messenger.send_text.call_args.kwargs
    if base:
        assert (
            "max_app" if channel == MessengerType.MAX else "/app"
        ) in result["keyboard"].rows[0][0].web_app_url
        assert result["keyboard"].rows[0][0].web_app_url.endswith("#services")
    else:
        assert result["keyboard"] is None


@pytest.mark.asyncio
async def test_telegram_canonical_geography_does_not_call_legacy(flow):
    from tests.helpers.fakes import FakeMessage, FakeUser
    from ugc_bot.bot.telegram.handlers import order_creation as tg
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    _, incoming, state, intake, messenger = flow
    legacy = SimpleNamespace(create_order=AsyncMock())
    texts = SimpleNamespace(get_many=AsyncMock(return_value={}))
    await tg.handle_geography(
        FakeMessage("Москва", FakeUser(12)),
        state,
        legacy,
        None,
        None,
        None,
        texts,
        None,
        None,
        None,
        messenger_client=messenger,
        event_adapter=TelegramEventAdapter(),
        order_intake_service=intake,
    )
    legacy.create_order.assert_not_awaited()
    assert state.state == OrderCreationStates.platforms.state


@pytest.mark.asyncio
async def test_max_canonical_geography_and_checkout(flow):
    from ugc_bot.bot.max.handlers import order_creation as mx

    _, incoming, state, intake, messenger = flow
    incoming = IncomingMessage(
        "12", IncomingUser("12", MessengerType.MAX), text="Москва"
    )
    deps = dict(
        messenger_client=messenger,
        bot_texts_service=SimpleNamespace(get_many=AsyncMock(return_value={})),
        state_store=state,
        order_service=SimpleNamespace(create_order=AsyncMock()),
        user_role_service=None,
        profile_service=None,
        content_moderation_service=None,
        config=SimpleNamespace(bot=SimpleNamespace(bot_username="umc_bot")),
        order_intake_service=intake,
    )
    await mx.handle_geography(incoming, deps)
    deps["order_service"].create_order.assert_not_awaited()
    assert state.state == OrderCreationStates.platforms.state
    await mx.handle_platforms(
        IncomingMessage("12", incoming.user, text="telegram"), deps
    )
    intake.create.return_value = SimpleNamespace(
        order_id=uuid4(), total_minor=500000, selection_base_minor=500000
    )
    await mx.handle_accompaniment(
        IncomingMessage("12", incoming.user, text="0"), deps
    )
    assert (
        messenger.send_text.call_args.kwargs["keyboard"]
        .rows[0][0]
        .url.startswith("https://t.me/umc_bot?start=pay_")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["telegram", "max"])
async def test_actions_transport_wrappers(flow, channel):
    import importlib

    from tests.helpers.fakes import FakeCallback, FakeMessage, FakeUser
    from ugc_bot.application.messenger.dto import IncomingCallback
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    module = importlib.import_module(
        f"ugc_bot.bot.{channel}.handlers.order_creation"
    )
    user_id, incoming, state, _, messenger = flow
    messenger.answer_callback = AsyncMock()
    user = SimpleNamespace(user_id=user_id, language="en")
    roles = SimpleNamespace(get_user=AsyncMock(return_value=user))
    order = SimpleNamespace(
        order_id=uuid4(),
        advertiser_id=user_id,
        offer_text="Test order",
        created_at=datetime.now(UTC),
    )
    orders = SimpleNamespace(
        list_by_advertiser=AsyncMock(return_value=[order]),
        get_order=AsyncMock(return_value=order),
    )
    followup = SimpleNamespace(optout=AsyncMock())
    support = SimpleNamespace(
        create=AsyncMock(return_value={"request_id": uuid4()})
    )
    config = SimpleNamespace(
        webhook=SimpleNamespace(webhook_base_url="https://example.com")
    )
    funcs = [
        ("handle_stop_reminders", {}),
        ("handle_customer_help", {}),
        (
            "handle_customer_help_callback",
            {"callback": True, "data": "customer:help"},
        ),
        (
            "handle_customer_problem",
            {"callback": True, "data": f"customer:problem:{order.order_id}"},
        ),
        ("handle_customer_problem_reason", {}),
        ("handle_customer_problem_contact", {}),
        ("handle_customer_services", {}),
        (
            "handle_customer_services_callback",
            {"callback": True, "data": "customer:services"},
        ),
    ]
    if channel == "max":
        incoming = IncomingMessage(
            "12",
            IncomingUser("12", MessengerType.MAX),
            text="Contact and reason",
        )
        deps = dict(
            messenger_client=messenger,
            user_role_service=roles,
            order_service=orders,
            client_followup_service=followup,
            order_support_service=support,
            state_store=state,
            config=config,
            locale="en",
        )
        for name, opts in funcs:
            event = (
                IncomingCallback(
                    "cb", "12", incoming.user, data=opts.get("data")
                )
                if opts.get("callback")
                else incoming
            )
            await getattr(module, name)(event, deps)
    else:
        import inspect

        message = FakeMessage("Contact and reason", FakeUser(12))
        params = dict(
            message=message,
            state=state,
            user_role_service=roles,
            order_service=orders,
            client_followup_service=followup,
            order_support_service=support,
            config=config,
            messenger_client=messenger,
            event_adapter=TelegramEventAdapter(),
            user_locale="en",
        )
        for name, opts in funcs:
            if opts.get("callback"):
                params["callback"] = FakeCallback(
                    opts["data"], FakeUser(12), message
                )
            func = getattr(module, name)
            await func(
                **{
                    key: params[key]
                    for key in inspect.signature(func).parameters
                }
            )
    followup.optout.assert_awaited_once()
    support.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_telegram_save_reuses_native_checkout_and_image_handler(
    flow, monkeypatch
):
    from io import BytesIO

    from tests.helpers.fakes import FakeMessage, FakeUser
    from ugc_bot.bot.telegram.handlers import order_creation as tg
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    user_id, incoming, state, intake, messenger = flow
    texts = SimpleNamespace(
        get=AsyncMock(return_value="prompt"),
        get_many=AsyncMock(return_value={}),
    )
    message = FakeMessage(user=FakeUser(12))
    message.document = SimpleNamespace(file_id="document", file_size=100)
    message.bot = SimpleNamespace(
        download=AsyncMock(return_value=BytesIO(b"data"))
    )
    images = SimpleNamespace(
        upload=AsyncMock(return_value=SimpleNamespace(token=uuid4()))
    )
    await tg.handle_order_photo(
        message,
        state,
        None,
        texts,
        messenger_client=messenger,
        event_adapter=TelegramEventAdapter(),
        order_intake_service=intake,
        order_image_service=images,
    )
    assert state._data["image_token"]
    assert state.state == OrderCreationStates.content_usage.state
    images.upload.side_effect = ValueError("image_dimensions")
    await state.set_state(OrderCreationStates.order_photo.state)
    await tg.handle_order_photo(
        message,
        state,
        None,
        texts,
        messenger_client=messenger,
        event_adapter=TelegramEventAdapter(),
        order_intake_service=intake,
        order_image_service=images,
    )
    assert state.state == OrderCreationStates.order_photo.state
    await ask_platforms(incoming, state, messenger, intake)
    await tg.handle_platforms(
        FakeMessage("youtube", FakeUser(12)),
        state,
        intake,
        messenger_client=messenger,
        event_adapter=TelegramEventAdapter(),
    )
    roles = SimpleNamespace(
        get_user_by_id=AsyncMock(return_value=SimpleNamespace(user_id=user_id))
    )
    checkout = AsyncMock()
    monkeypatch.setattr(tg, "send_checkout_if_v1", checkout)
    intake.create.return_value = SimpleNamespace(
        order_id=uuid4(), total_minor=500000, selection_base_minor=500000
    )
    await tg.handle_accompaniment(
        FakeMessage("0", FakeUser(12)),
        state,
        intake,
        roles,
        None,
        None,
        texts,
        messenger_client=messenger,
        event_adapter=TelegramEventAdapter(),
    )
    assert state.state is None
    assert state._data["saved_order_id"]
    checkout.assert_awaited_once()
    assert checkout.call_args.args[0] == intake.create.return_value.order_id
    intake.create.side_effect = ValueError("unavailable")
    await tg.handle_accompaniment(
        FakeMessage("0", FakeUser(12)),
        state,
        intake,
        roles,
        None,
        None,
        texts,
        messenger_client=messenger,
        event_adapter=TelegramEventAdapter(),
    )
    assert checkout.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["telegram", "max"])
@pytest.mark.parametrize("count", ["9", "10", "17", "200", "201"])
async def test_canonical_count_boundaries_use_domain_range(
    flow, channel, count
):
    from tests.helpers.fakes import FakeMessage, FakeUser
    from ugc_bot.bot.max.handlers import order_creation as mx
    from ugc_bot.bot.telegram.handlers import order_creation as tg
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    _, incoming, state, intake, messenger = flow
    state._data["canonical_intake"] = True
    texts = SimpleNamespace(
        get=AsyncMock(return_value="{counts}"),
        get_many=AsyncMock(return_value={}),
    )
    if channel == "telegram":
        await tg.handle_bloggers_needed(
            FakeMessage(count, FakeUser(12)),
            state,
            None,
            texts,
            frozenset({1, 3, 5}),
            messenger_client=messenger,
            event_adapter=TelegramEventAdapter(),
        )
    else:
        await mx.handle_bloggers_needed_text(
            IncomingMessage(
                "12", IncomingUser("12", MessengerType.MAX), text=count
            ),
            dict(
                messenger_client=messenger,
                bot_texts_service=texts,
                state_store=state,
                order_intake_service=intake,
            ),
        )
    if 10 <= int(count) <= 200:
        assert state.state == OrderCreationStates.product_link.state
        assert state._data["bloggers_needed"] == int(count)
    else:
        assert state.state is None


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["telegram", "max"])
async def test_stories_callback_is_separate_format(flow, channel):
    from tests.helpers.fakes import FakeCallback, FakeMessage, FakeUser
    from ugc_bot.application.messenger.dto import IncomingCallback
    from ugc_bot.bot.max.handlers import order_creation as mx
    from ugc_bot.bot.telegram.handlers import order_creation as tg
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    _, incoming, state, _, messenger = flow
    state.state = OrderCreationStates.order_type.state
    messenger.answer_callback = AsyncMock()
    messenger.edit_reply_markup = AsyncMock()
    texts = SimpleNamespace(
        get=AsyncMock(return_value="Brief"),
        get_many=AsyncMock(return_value={"order_type_stories": "Stories"}),
    )
    if channel == "telegram":
        await tg.handle_order_type_callback(
            FakeCallback("order:type:stories", FakeUser(12), FakeMessage()),
            state,
            None,
            texts,
            messenger_client=messenger,
            event_adapter=TelegramEventAdapter(),
        )
    else:
        await mx.handle_order_type_callback(
            IncomingCallback(
                "cb", "12", incoming.user, data="order:type:stories"
            ),
            dict(
                messenger_client=messenger,
                bot_texts_service=texts,
                state_store=state,
            ),
        )
    assert state._data["order_type"] == "stories"
    assert state.state == OrderCreationStates.offer_text.state


def test_customer_copy_covers_supported_locales_and_followup_keys():
    from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
    from ugc_bot.bot.texts.defaults.customer import CUSTOMER_TEXTS

    for locale in ("ru", "en", "kk", "be", "uz"):
        assert set(CUSTOMER_TEXTS[locale]) == set(CUSTOMER_TEXTS["ru"])
        assert DEFAULT_TEXTS[locale]["customer_followup_1"]
        assert DEFAULT_TEXTS[locale]["order_type_stories"]


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["telegram", "max"])
@pytest.mark.parametrize("entry", ["command", "profile", "agreement"])
async def test_new_canonical_brief_clears_previous_operation(
    flow, channel, entry
):
    from tests.helpers.fakes import FakeCallback, FakeMessage, FakeUser
    from ugc_bot.application.messenger.dto import IncomingCallback
    from ugc_bot.bot.max.handlers import order_creation as mx
    from ugc_bot.bot.telegram.handlers import order_creation as tg
    from ugc_bot.bot.telegram.handlers.keyboards import (
        CALLBACK_ORDER_AGREE,
        CALLBACK_PROFILE_MENU_CREATE_ORDER,
    )
    from ugc_bot.bot.telegram.handlers.profile import (
        _ADVERTISER_AGREEMENTS_STATE,
    )
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    user_id, incoming, state, intake, messenger = flow
    state._data.update(
        intake_operation_key="previous-operation", flow_type="order_creation"
    )
    state.state = _ADVERTISER_AGREEMENTS_STATE
    user = SimpleNamespace(user_id=user_id, status="active", country="RU")
    roles = SimpleNamespace(get_user=AsyncMock(return_value=user))
    profile = SimpleNamespace(
        get_advertiser_profile=AsyncMock(
            return_value=SimpleNamespace(
                agreement_confirmed_at=datetime.now(UTC)
            )
        )
    )
    registration = SimpleNamespace(confirm_advertiser_agreement=AsyncMock())
    followup = SimpleNamespace(
        register_brief=AsyncMock(return_value=uuid4()),
        record_activity=AsyncMock(),
    )
    texts = SimpleNamespace(
        get=AsyncMock(return_value="Brief"), get_many=AsyncMock(return_value={})
    )
    messenger.answer_callback = AsyncMock()
    messenger.edit_reply_markup = AsyncMock()
    if channel == "max":
        incoming = IncomingMessage("12", IncomingUser("12", MessengerType.MAX))
        deps = dict(
            messenger_client=messenger,
            user_role_service=roles,
            profile_service=profile,
            state_store=state,
            order_intake_service=intake,
            config=None,
            bot_texts_service=texts,
            advertiser_registration_service=registration,
            client_followup_service=followup,
            locale="en",
        )
        if entry == "command":
            await mx.start_order_creation(incoming, deps)
        elif entry == "profile":
            await mx.start_order_creation_from_profile_callback(
                IncomingCallback(
                    "cb",
                    "12",
                    incoming.user,
                    data=CALLBACK_PROFILE_MENU_CREATE_ORDER,
                ),
                deps,
            )
        else:
            await mx.handle_order_agree_callback(
                IncomingCallback(
                    "cb", "12", incoming.user, data=CALLBACK_ORDER_AGREE
                ),
                deps,
            )
    else:
        message = FakeMessage(user=FakeUser(12))
        kwargs = dict(
            state=state,
            messenger_client=messenger,
            event_adapter=TelegramEventAdapter(),
            order_intake_service=intake,
            client_followup_service=followup,
            user_locale="en",
        )
        if entry == "command":
            await tg.start_order_creation(
                message,
                user_role_service=roles,
                profile_service=profile,
                order_service=None,
                config=None,
                bot_texts_service=texts,
                **kwargs,
            )
        elif entry == "profile":
            await tg.start_order_creation_from_profile_callback(
                FakeCallback(
                    CALLBACK_PROFILE_MENU_CREATE_ORDER, FakeUser(12), message
                ),
                user_role_service=roles,
                profile_service=profile,
                order_service=None,
                config=None,
                bot_texts_service=texts,
                **kwargs,
            )
        else:
            await tg.handle_order_agree_callback(
                FakeCallback(CALLBACK_ORDER_AGREE, FakeUser(12), message),
                config=None,
                bot_texts_service=texts,
                advertiser_registration_service=registration,
                **kwargs,
            )
    assert "intake_operation_key" not in state._data
    assert state._data["locale"] == "en"
    assert state.state == OrderCreationStates.order_type.state
    intent_id = UUID(state._data["intake_funnel_id"])
    assert followup.register_brief.call_args.args == (user_id,)
    assert (
        followup.register_brief.call_args.kwargs["principal"].user_id == user_id
    )
    assert followup.record_activity.call_args.kwargs["intent_id"] == intent_id

"""Customer help, rich services entry and reminder consent on both channels."""

from uuid import UUID, uuid4

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.bot.customer_intake import principal_for
from ugc_bot.bot.texts.defaults.customer import customer_text
from ugc_bot.domain.customer_workflows import SupportInput

SUPPORT_REASON = "CustomerSupport:reason"
SUPPORT_CONTACT = "CustomerSupport:contact"
SUPPORT_PREFIX = "customer:problem:"


async def resolve_customer(incoming, roles):
    return await roles.get_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
    )


async def show_help(incoming, messenger, roles, orders):
    user = await resolve_customer(incoming, roles)
    if user is None:
        return
    owned = await orders.list_by_advertiser(user.user_id)
    buttons = [
        [
            Button(
                text=(
                    f"№{str(order.order_id).replace('-', '')[:8].upper()}"
                    f" — {order.offer_text[:50]}"
                ),
                callback_data=f"{SUPPORT_PREFIX}{order.order_id}",
            )
        ]
        for order in sorted(
            owned, key=lambda order: order.created_at, reverse=True
        )
    ]
    await messenger.send_text(
        chat_id=incoming.chat_id,
        text=customer_text(
            getattr(user, "language", "ru"),
            "customer_help" if buttons else "customer_no_orders",
        ),
        keyboard=Keyboard(kind=KeyboardKind.INLINE, rows=buttons)
        if buttons
        else None,
    )


async def begin_support(incoming, state, messenger, roles, orders):
    user = await resolve_customer(incoming, roles)
    try:
        order_id = UUID((incoming.data or "")[len(SUPPORT_PREFIX) :])
        order = await orders.get_order(order_id)
        if user is None or order is None or order.advertiser_id != user.user_id:
            raise PermissionError("order_owner_required")
    except (ValueError, PermissionError):
        await messenger.send_text(
            chat_id=incoming.chat_id,
            text=customer_text(
                getattr(user, "language", "ru"), "customer_unavailable"
            ),
        )
        return
    await state.update_data(
        support_order_id=str(order_id),
        support_operation_key=str(uuid4()),
        support_reason=None,
        support_locale=getattr(user, "language", "ru"),
    )
    await state.set_state(SUPPORT_REASON)
    await messenger.send_text(
        chat_id=incoming.chat_id,
        text=customer_text(getattr(user, "language", "ru"), "customer_reason"),
    )


async def support_reason(incoming, state, messenger):
    data = await state.get_data()
    reason = (incoming.text or "").strip()
    if not 1 <= len(reason) <= 4000:
        await messenger.send_text(
            chat_id=incoming.chat_id,
            text=customer_text(
                data.get("support_locale", "ru"), "customer_reason_invalid"
            ),
        )
        return
    await state.update_data(support_reason=reason)
    await state.set_state(SUPPORT_CONTACT)
    await messenger.send_text(
        chat_id=incoming.chat_id,
        text=customer_text(
            data.get("support_locale", "ru"), "customer_contact"
        ),
    )


async def send_support(incoming, state, messenger, roles, service):
    user = await resolve_customer(incoming, roles)
    if user is None:
        return
    data = await state.get_data()
    try:
        if service is None:
            raise ValueError("support_unavailable")
        result = await service.create(
            user.user_id,
            SupportInput(
                order_id=UUID(data["support_order_id"]),
                operation_key=data["support_operation_key"],
                reason=data["support_reason"],
                contact_reference=(incoming.text or "").strip(),
            ),
            principal=principal_for(incoming, user.user_id),
        )
    except (ValueError, PermissionError, LookupError):
        await messenger.send_text(
            chat_id=incoming.chat_id,
            text=customer_text(
                getattr(user, "language", "ru"), "customer_unavailable"
            ),
        )
        return
    number = (
        result.get("number")
        or str(result["request_id"]).replace("-", "")[:8].upper()
    )
    await state.set_state(None)
    await messenger.send_text(
        chat_id=incoming.chat_id,
        text=customer_text(
            getattr(user, "language", "ru"),
            "customer_support_saved",
            number=number,
        ),
    )


async def stop_reminders(incoming, messenger, roles, service):
    user = await resolve_customer(incoming, roles)
    if user is None or service is None:
        return
    await service.optout(
        user.user_id, principal=principal_for(incoming, user.user_id)
    )
    await messenger.send_text(
        chat_id=incoming.chat_id,
        text=customer_text(getattr(user, "language", "ru"), "customer_optout"),
    )


async def show_services(incoming, messenger, config, locale="ru"):
    base = config.webhook.webhook_base_url.strip().rstrip("/")
    platform = incoming.user.messenger_type.value
    username = (
        (config.referral.max_referral_bot_username or "").strip().lstrip("@")
        if platform == "max"
        else ""
    )
    app_target = (
        username if platform == "max" else f"{base}/miniapp/app.html#services"
    )
    keyboard = (
        Keyboard(
            kind=KeyboardKind.INLINE,
            rows=[
                [
                    Button(
                        text=customer_text(locale, "btn_all_services"),
                        web_app_url=app_target,
                        max_app_payload=(
                            "services" if platform == "max" else None
                        ),
                    )
                ]
            ],
        )
        if base and (platform != "max" or username)
        else None
    )
    await messenger.send_text(
        chat_id=incoming.chat_id,
        text=customer_text(locale, "customer_services"),
        keyboard=keyboard,
    )

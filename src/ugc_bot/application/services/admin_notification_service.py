"""Service for notifying admins about new complaints and orders via Telegram."""

import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.application.messenger.ports import MessengerClient
from ugc_bot.application.ports import CountryRepository
from ugc_bot.application.services.business_order_card import (
    order_card_url,
    render_business_order_card,
)
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import AdvertiserProfile, Complaint, Order, User
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus

logger = logging.getLogger(__name__)

MOD_ACTIVATE_CALLBACK_PREFIX = "mod_activate:"


def order_admin_url(admin_base_url: str, order: Order) -> str | None:
    """Use one concrete editable order card for every notification."""
    base = order_card_url(admin_base_url.strip().rstrip("/"))
    if not base:
        return None
    if not urlsplit(base).path:
        base += "/admin"
    return f"{base}/order-model/edit/{order.order_id}"


def _unique_admin_recipients(admins: list[User]) -> list[User]:
    seen: set[str] = set()
    result = []
    for admin in admins:
        address = (admin.telegram_id or admin.max_chat_id or "").strip()
        if address and address not in seen:
            seen.add(address)
            result.append(admin)
    return result


async def _send_admin_text(
    messenger_client: Any,
    *,
    chat_id: str,
    text: str,
    keyboard: Keyboard | None = None,
    parse_mode: str | None = None,
    disable_preview: bool | None = None,
) -> None:
    """Send text using messenger client or raw bot."""
    if hasattr(messenger_client, "send_text"):
        await messenger_client.send_text(
            chat_id=chat_id,
            text=text,
            keyboard=keyboard,
            parse_mode=parse_mode,
            disable_preview=disable_preview,
        )
        return
    if hasattr(messenger_client, "send_message"):
        await messenger_client.send_message(
            chat_id=int(chat_id),
            text=text,
            reply_markup=keyboard,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_preview,
        )
        return
    raise AttributeError("Messenger client lacks send methods")


async def _send_admin_photo(
    messenger_client: Any,
    *,
    chat_id: str,
    file_id: str,
    caption: str | None,
    keyboard: Keyboard | None = None,
    parse_mode: str | None = None,
) -> None:
    """Send photo using messenger client or raw bot."""
    if hasattr(messenger_client, "send_text"):
        await messenger_client.send_photo(
            chat_id=chat_id,
            file_id=file_id,
            caption=caption,
            parse_mode=parse_mode,
            keyboard=keyboard,
        )
        return
    if hasattr(messenger_client, "send_photo"):
        await messenger_client.send_photo(
            chat_id=int(chat_id),
            photo=file_id,
            caption=caption,
            reply_markup=keyboard,
            parse_mode=parse_mode,
        )
        return
    raise AttributeError("Messenger client lacks send_photo")


async def notify_admins_about_complaint(
    complaint: Complaint,
    messenger_client: MessengerClient,
    user_role_service: UserRoleService,
) -> None:
    """Send complaint details to all Telegram admins.

    Args:
        complaint: The created complaint.
        messenger_client: Messenger client for sending messages.
        user_role_service: Service to fetch admin list and usernames.
    """
    admins = await user_role_service.list_admins(
        messenger_type=MessengerType.TELEGRAM
    )
    if not admins:
        logger.debug("No Telegram admins to notify about complaint")
        return

    reporter = await user_role_service.get_user_by_id(complaint.reporter_id)
    reported = await user_role_service.get_user_by_id(complaint.reported_id)
    reporter_name = (
        reporter.username if reporter else str(complaint.reporter_id)
    )
    reported_name = (
        reported.username if reported else str(complaint.reported_id)
    )

    text = (
        "🔔 *Новая жалоба*\n\n"
        f"*ID жалобы:* `{complaint.complaint_id}`\n"
        f"*Жалобу подал:* {reporter_name}\n"
        f"*На пользователя:* {reported_name}\n"
        f"*Заказ:* `{complaint.order_id}`\n"
        f"*Причина:* {complaint.reason}"
    )
    if complaint.file_ids:
        text += f"\n*Фото:* {len(complaint.file_ids)} шт."

    for admin in _unique_admin_recipients(admins):
        try:
            chat_id = admin.telegram_id or admin.max_chat_id or ""
            if complaint.file_ids:
                await _send_admin_photo(
                    messenger_client,
                    chat_id=chat_id,
                    file_id=complaint.file_ids[0],
                    caption=text,
                    parse_mode="Markdown",
                )
                for file_id in complaint.file_ids[1:]:
                    await _send_admin_photo(
                        messenger_client,
                        chat_id=chat_id,
                        file_id=file_id,
                        caption=None,
                    )
            else:
                await _send_admin_text(
                    messenger_client,
                    chat_id=chat_id,
                    text=text,
                    parse_mode="Markdown",
                )
        except Exception as exc:
            logger.error(
                "Failed to notify admin about complaint",
                extra={
                    "admin_id": str(admin.user_id),
                    "complaint_id": str(complaint.complaint_id),
                    "error": str(exc),
                },
            )


async def _resolve_order_currency_symbol(
    order: Order,
    country_repo: CountryRepository | None,
    fallback: str,
) -> str:
    if country_repo is None:
        return fallback
    country = await country_repo.get_by_currency_code(order.currency)
    return country.currency_symbol if country is not None else fallback


async def business_order_admins(
    roles: UserRoleService, recipient_ids: frozenset[str]
) -> list[User]:
    if not recipient_ids:
        return []
    admins = await roles.list_admins(messenger_type=MessengerType.TELEGRAM)
    return _unique_admin_recipients(
        [
            user
            for user in admins
            if user.status == UserStatus.ACTIVE
            and (address := (user.telegram_id or "").strip())
            and address.isascii()
            and address.isdecimal()
            and address[0] != "0"
            and address in recipient_ids
        ]
    )


async def _notify_about_business_order(
    order: Order,
    messenger_client: MessengerClient,
    roles: UserRoleService,
    moderation: ContentModerationService,
    *,
    admin_base_url: str,
    webhook_base_url: str,
    symbol: str,
    country_repo: CountryRepository | None,
    profile: AdvertiserProfile | None,
    details: Mapping[str, Any] | None,
    recipient_ids: frozenset[str],
    paid_event: bool,
    payment_confirmed: bool | None,
    eligible_count: int | None,
    raise_on_error: bool,
) -> None:
    admins = await business_order_admins(roles, recipient_ids)
    if not admins:
        return
    symbol = await _resolve_order_currency_symbol(order, country_repo, symbol)
    advertiser = await roles.get_user_by_id(order.advertiser_id)
    text = render_business_order_card(
        order,
        advertiser=advertiser,
        profile=profile,
        symbol=symbol,
        details=details,
        paid_event=paid_event,
        payment_confirmed=payment_confirmed,
        eligible_count=eligible_count,
        flagged=moderation.order_contains_banned_content(
            product_link=order.product_link,
            offer_text=order.offer_text,
            barter_description=order.barter_description,
            content_usage=order.content_usage,
            geography=order.geography,
        ),
    )

    buttons: list[list[Button]] = []
    if link := order_admin_url(admin_base_url, order):
        buttons.append([Button(text="Открыть в админке", url=link)])
    resources = [
        Button(text=label, url=url)
        for label, value in (
            ("Продукт", order.product_link),
            ("ТЗ", order.brief_link),
        )
        if (url := order_card_url(value))
    ]
    if resources:
        buttons.append(resources)
    base = order_card_url(webhook_base_url)
    if base and urlsplit(base).scheme == "https":
        buttons.append(
            [
                Button(
                    text="Скопировать для GPT",
                    web_app_url=f"{base.rstrip('/')}/miniapp/order-gpt-copy.html?order={order.order_id}",
                )
            ]
        )
    if paid_event and order.status == OrderStatus.PENDING_MODERATION:
        buttons.append(
            [
                Button(
                    text="Активировать",
                    callback_data=f"{MOD_ACTIVATE_CALLBACK_PREFIX}{order.order_id.hex}",
                )
            ]
        )
    keyboard = (
        Keyboard(kind=KeyboardKind.INLINE, rows=buttons) if buttons else None
    )

    for admin in admins:
        chat_id = (admin.telegram_id or "").strip()
        try:
            if order.product_photo_file_id:
                await _send_admin_photo(
                    messenger_client,
                    chat_id=chat_id,
                    file_id=order.product_photo_file_id,
                    caption=text,
                    parse_mode="HTML",
                    keyboard=keyboard,
                )
            else:
                await _send_admin_text(
                    messenger_client,
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    keyboard=keyboard,
                    disable_preview=True,
                )
        except Exception as exc:
            logger.error(
                "Failed to notify admin about business order",
                extra={
                    "admin_id": str(admin.user_id),
                    "order_id": str(order.order_id),
                    "error_type": type(exc).__name__,
                },
            )
            if raise_on_error:
                raise


async def notify_admins_about_order_created(
    order: Order,
    messenger_client: MessengerClient,
    user_role_service: UserRoleService,
    content_moderation: ContentModerationService,
    admin_base_url: str = "",
    currency_symbol: str = "₽",
    country_repo: CountryRepository | None = None,
    advertiser_profile: AdvertiserProfile | None = None,
    order_details: Mapping[str, Any] | None = None,
    raise_on_error: bool = False,
    *,
    recipient_ids: frozenset[str],
    webhook_base_url: str = "",
    payment_confirmed: bool | None = None,
    eligible_count: int | None = None,
) -> None:
    """Send the new business order card without an activation action."""
    await _notify_about_business_order(
        order,
        messenger_client,
        user_role_service,
        content_moderation,
        admin_base_url=admin_base_url,
        webhook_base_url=webhook_base_url,
        symbol=currency_symbol,
        country_repo=country_repo,
        profile=advertiser_profile,
        details=order_details,
        recipient_ids=recipient_ids,
        paid_event=False,
        payment_confirmed=payment_confirmed,
        eligible_count=eligible_count,
        raise_on_error=raise_on_error,
    )


async def notify_admins_about_order_paid(
    order: Order,
    messenger_client: MessengerClient,
    user_role_service: UserRoleService,
    content_moderation: ContentModerationService,
    admin_base_url: str = "",
    currency_symbol: str = "₽",
    advertiser_profile: AdvertiserProfile | None = None,
    order_details: Mapping[str, Any] | None = None,
    raise_on_error: bool = False,
    *,
    recipient_ids: frozenset[str],
    webhook_base_url: str = "",
    payment_confirmed: bool | None = None,
    eligible_count: int | None = None,
) -> None:
    """Send the paid business order card with the existing moderation action."""
    await _notify_about_business_order(
        order,
        messenger_client,
        user_role_service,
        content_moderation,
        admin_base_url=admin_base_url,
        webhook_base_url=webhook_base_url,
        symbol=currency_symbol,
        country_repo=None,
        profile=advertiser_profile,
        details=order_details,
        recipient_ids=recipient_ids,
        paid_event=True,
        payment_confirmed=payment_confirmed,
        eligible_count=eligible_count,
        raise_on_error=raise_on_error,
    )

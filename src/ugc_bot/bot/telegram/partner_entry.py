"""Own-only partner terms and personal link, readable without the Mini App."""

import logging

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.bot.customer_intake import principal_for
from ugc_bot.bot.partner_entry import _url
from ugc_bot.bot.telegram.navigation import HOME
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
from ugc_bot.domain.enums import UserStatus

logger = logging.getLogger(__name__)


def _percent(bps):
    return f"{bps / 100:g}"


async def send_telegram_partner_entry(
    incoming,
    client,
    config,
    locale,
    user_role_service,
    partner_view_service,
    transaction_manager,
    bot_texts_service=None,
):
    # Native Telegram sender identity is trusted; chat IDs and callback payloads
    # must never select a different account or publish a link to a group.
    if str(incoming.chat_id) != incoming.user.external_id:
        return
    words = DEFAULT_TEXTS.get(locale, DEFAULT_TEXTS["ru"]).copy()
    if bot_texts_service:
        words.update(
            await bot_texts_service.get_many(
                [
                    key
                    for key in words
                    if key.startswith(("msg_partner_", "btn_partner_"))
                ]
                + ["btn_copy_referral_link", "btn_main_menu"],
                locale,
            )
        )
    url = _url(config, "telegram")
    rows = []
    if url:
        rows.append([Button(words["btn_partner_cabinet"], web_app_url=url)])
    text = words["msg_partner_chat_unavailable"]
    if user_role_service and partner_view_service and transaction_manager:
        try:
            user = await user_role_service.get_user(
                external_id=incoming.user.external_id,
                messenger_type=incoming.user.messenger_type,
            )
            if user is None:
                user = await user_role_service.set_user(
                    external_id=incoming.user.external_id,
                    messenger_type=incoming.user.messenger_type,
                    username="",
                    telegram_username=incoming.user.username,
                )
            if user.status == UserStatus.BLOCKED:
                raise PermissionError("partner_account_unavailable")
            async with transaction_manager.transaction() as session:
                view = await partner_view_service.view(
                    user.user_id,
                    platform="telegram",
                    writes_paused=not config.financial.core_enabled,
                    session=session,
                    principal=principal_for(incoming, user.user_id),
                )
            standards = view["standards"]
            link = view["referral"]["link"]
            text = words["msg_partner_chat"].format(
                client=_percent(standards["client_first_year_bps"]),
                creator=_percent(view["grade"]["tier_rate_bps"]),
                after=_percent(standards["after_year_bps"]),
                count=view["grade"]["verified_creators"],
                tiers="; ".join(
                    words["msg_partner_tier"].format(
                        threshold=tier["threshold"],
                        rate=_percent(tier["rate_bps"]),
                    )
                    for tier in standards["creator_tiers"]
                ),
                link=link or words["msg_partner_link_unavailable"],
            )
            if link:
                rows.insert(
                    0, [Button(words["btn_copy_referral_link"], copy_text=link)]
                )
        except Exception as exc:
            # Do not log personal links, financial facts, credentials or SQL.
            logger.warning(
                "Telegram partner entry unavailable",
                extra={"error_type": type(exc).__name__},
            )
    rows.append([Button(words["btn_main_menu"], callback_data=HOME)])
    await client.send_text(
        chat_id=incoming.chat_id,
        text=text,
        keyboard=Keyboard(kind=KeyboardKind.INLINE, rows=rows),
        disable_preview=True,
    )

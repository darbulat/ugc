"""Max support chat handlers — forward messages to TG group."""

import logging

from ugc_bot.application.messenger.dto import (
    Button,
    IncomingCallback,
    IncomingMessage,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.bot.max.middleware import resolve_locale
from ugc_bot.bot.max.router import MaxRouter

logger = logging.getLogger(__name__)

router = MaxRouter()

CALLBACK_SUPPORT_START_CHAT = "support:chat"
CALLBACK_SUPPORT_EXIT = "support:exit"
SUPPORT_STATE = "support:conversation"


def _exit_keyboard(btn_text: str) -> Keyboard:
    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [Button(text=btn_text, callback_data=CALLBACK_SUPPORT_EXIT)],
        ],
    )


@router.callback(lambda c: c.data == CALLBACK_SUPPORT_START_CHAT)
async def start_support_chat(incoming: IncomingCallback, deps: dict) -> None:
    """Enter support conversation mode."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    user_role_service = deps["user_role_service"]
    config = deps["config"]
    state_store = deps["state_store"]

    locale = await resolve_locale(
        incoming, user_role_service, config.market.default_locale
    )

    await messenger_client.answer_callback(callback_id=incoming.callback_id)

    support_chat_id = (config.market.support_chat_id or "").strip()
    if not support_chat_id:
        msg = await bot_texts_service.get("support_chat_not_configured", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg or "Чат поддержки временно недоступен.",
        )
        return

    await state_store.set_state(SUPPORT_STATE)

    prompt = await bot_texts_service.get("support_chat_prompt", locale)
    btn_exit = await bot_texts_service.get("btn_support_exit", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=prompt
        or "Напишите ваше сообщение, и мы ответим в ближайшее время.",
        keyboard=_exit_keyboard(btn_exit or "❌ Завершить диалог"),
    )


@router.message_in_state(SUPPORT_STATE)
async def handle_user_support_message(
    incoming: IncomingMessage, deps: dict
) -> None:
    """Forward user message to Telegram support group."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    user_role_service = deps["user_role_service"]
    support_service = deps["support_service"]
    config = deps["config"]

    locale = await resolve_locale(
        incoming, user_role_service, config.market.default_locale
    )

    support_chat_id = (config.market.support_chat_id or "").strip()
    if not support_chat_id:
        msg = await bot_texts_service.get("support_chat_not_configured", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg or "Чат поддержки временно недоступен.",
        )
        return

    text = (incoming.text or "").strip()
    if not text:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Пожалуйста, отправьте текстовое сообщение.",
        )
        return

    # Build header for support group
    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
    )
    username = user.username if user else incoming.user.username or "—"
    header = (
        f"💬 Max Support\nUser: {username} (chat: {incoming.chat_id})\n\n{text}"
    )

    # Send to Telegram support group via the Telegram messenger client
    telegram_client = deps.get("telegram_messenger_client")
    if telegram_client is None:
        logger.error("telegram_messenger_client not available in deps")
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Чат поддержки временно недоступен.",
        )
        return

    try:
        # Use the underlying aiogram Bot to get the returned message ID
        sent_message = await telegram_client._bot.send_message(
            chat_id=int(support_chat_id),
            text=header,
        )
        await support_service.record_forwarded_message(
            user_chat_id=incoming.chat_id,
            support_chat_message_id=sent_message.message_id,
            user_text=text,
        )
    except Exception:
        logger.exception("Failed to forward support message to Telegram group")
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Не удалось отправить сообщение. Попробуйте позже.",
        )
        return

    sent_text = await bot_texts_service.get("support_chat_sent", locale)
    btn_exit = await bot_texts_service.get("btn_support_exit", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=sent_text or "Сообщение отправлено в поддержку.",
        keyboard=_exit_keyboard(btn_exit or "❌ Завершить диалог"),
    )


@router.callback_in_state(
    SUPPORT_STATE, lambda c: c.data == CALLBACK_SUPPORT_EXIT
)
async def exit_support_chat_in_state(
    incoming: IncomingCallback, deps: dict
) -> None:
    """Exit support conversation (while in state)."""
    await _do_exit(incoming, deps)


@router.callback(lambda c: c.data == CALLBACK_SUPPORT_EXIT)
async def exit_support_chat(incoming: IncomingCallback, deps: dict) -> None:
    """Exit support conversation (outside state, e.g. stale button)."""
    await _do_exit(incoming, deps)


async def _do_exit(incoming: IncomingCallback, deps: dict) -> None:
    """Clear FSM and send exit confirmation."""
    messenger_client = deps["messenger_client"]
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    bot_texts_service = deps["bot_texts_service"]
    user_role_service = deps["user_role_service"]
    config = deps["config"]
    state_store = deps["state_store"]

    locale = await resolve_locale(
        incoming, user_role_service, config.market.default_locale
    )
    await state_store.clear()

    exit_text = await bot_texts_service.get("support_chat_exit", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=exit_text or "Вы вышли из чата с поддержкой.",
    )

"""Start and role selection handlers for Max messenger.

Max messenger is Russia-only: country is always "RU", language "ru".
Country/language selection screens are skipped.
"""

from urllib.parse import urlparse

from ugc_bot.application.errors import UserNotFoundError
from ugc_bot.application.messenger.dto import (
    Button,
    IncomingCallback,
    IncomingMessage,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.bot.max.handlers.support_chat import CALLBACK_SUPPORT_START_CHAT
from ugc_bot.bot.max.middleware import resolve_locale
from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_CHANGE_COUNTRY_PREFIX,
    CALLBACK_CHANGE_ROLE,
    CALLBACK_COUNTRY_PREFIX,
    CALLBACK_LANG_PREFIX,
    CALLBACK_SUPPORT,
    country_change_inline_keyboard,
    country_inline_keyboard,
    language_inline_keyboard,
    miniapp_open_inline_keyboard,
    role_inline_keyboard,
)
from ugc_bot.bot.telegram.handlers.start import (
    _change_role_button,
    _start_command,
)

router = MaxRouter()


@router.message(lambda m: bool(m.text and m.text.startswith("/start")))
async def start_handler(incoming: IncomingMessage, deps: dict) -> None:
    """Handle /start — auto-set RU/ru, show role selection."""
    user_role_service = deps["user_role_service"]
    referral_service = deps["referral_service"]
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    config = deps["config"]
    state_store = deps["state_store"]

    locale = "ru"

    start_text = (
        (await bot_texts_service.get("start_message", locale)).strip()
        or (config.market.start_text or "").strip()
        or ""
    )
    if not start_text:
        start_text = (
            "UMC — сервис для UGC.\n"
            "Бизнесу — подбор креаторов, креаторам — заказы."
        )
    texts = await bot_texts_service.get_many(
        ["btn_creator", "btn_advertiser", "btn_support"], locale
    )

    # Max is Russia-only: skip country/language selection
    await _start_command(
        incoming=incoming,
        state_store=state_store,
        messenger_client=messenger_client,
        user_role_service=user_role_service,
        referral_service=referral_service,
        start_text=start_text,
        role_kb=role_inline_keyboard(texts),
        country_kb=None,
        tg_language_code="ru",
        max_chat_id=incoming.chat_id,
    )
    # Auto-set country for new Max users
    await user_role_service.set_country(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
        country_code="ru",
    )


@router.callback(
    lambda c: bool(c.data and c.data.startswith(CALLBACK_COUNTRY_PREFIX))
)
async def country_selected(incoming: IncomingCallback, deps: dict) -> None:
    """Handle country selection — save country, show role keyboard."""
    user_role_service = deps["user_role_service"]
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    country_repo = deps.get("country_repo")
    config = deps["config"]
    state_store = deps["state_store"]

    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    existing_user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
    )
    if existing_user and existing_user.country is not None:
        return
    country_code = (incoming.data or "").removeprefix(CALLBACK_COUNTRY_PREFIX)
    if not country_code:
        return
    if country_repo:
        country = await country_repo.get_by_code(country_code)
        if country is None:
            return
    await user_role_service.set_country(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
        country_code=country_code,
    )
    if incoming.message_id:
        await messenger_client.edit_reply_markup(
            chat_id=incoming.chat_id,
            message_id=incoming.message_id,
            keyboard=None,
        )
    locale = await resolve_locale(
        incoming, user_role_service, config.market.default_locale
    )
    start_text = (
        (await bot_texts_service.get("start_message", locale)).strip()
        or (config.market.start_text or "").strip()
        or ""
    )
    if not start_text:
        start_text = (
            "UMC — сервис для UGC.\n"
            "Бизнесу — подбор креаторов, креаторам — заказы."
        )
    texts = await bot_texts_service.get_many(
        ["btn_creator", "btn_advertiser", "btn_support"], locale
    )
    await state_store.clear()
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=start_text,
        keyboard=role_inline_keyboard(texts),
    )


@router.callback(
    lambda c: bool(c.data and c.data.startswith(CALLBACK_LANG_PREFIX))
)
async def language_selected(incoming: IncomingCallback, deps: dict) -> None:
    """Handle language selection — save language, proceed to country or role."""
    user_role_service = deps["user_role_service"]
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    country_repo = deps.get("country_repo")
    language_repo = deps.get("language_repo")

    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    language_code = (incoming.data or "").removeprefix(CALLBACK_LANG_PREFIX)
    if not language_code:
        return
    if language_repo is not None:
        valid_language = await language_repo.get_by_code(language_code)
        if valid_language is None:
            return
    try:
        user = await user_role_service.set_language(
            external_id=incoming.user.external_id,
            messenger_type=incoming.user.messenger_type,
            language_code=language_code,
        )
    except UserNotFoundError:
        return
    new_locale = language_code
    if incoming.message_id:
        await messenger_client.edit_reply_markup(
            chat_id=incoming.chat_id,
            message_id=incoming.message_id,
            keyboard=None,
        )
    if user and user.country is None and country_repo:
        countries = await country_repo.list_enabled()
        country_prompt = (
            await bot_texts_service.get("country_prompt", new_locale)
        ).strip() or "Выберите вашу страну:"
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=country_prompt,
            keyboard=country_inline_keyboard(countries),
        )
        return
    start_text = (
        await bot_texts_service.get("start_message", new_locale)
    ).strip() or "UGC — сервис для UGC."
    texts = await bot_texts_service.get_many(
        ["btn_creator", "btn_advertiser", "btn_support"], new_locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=start_text,
        keyboard=role_inline_keyboard(texts),
    )


@router.message(lambda m: bool(m.text and m.text.startswith("/language")))
async def language_command(incoming: IncomingMessage, deps: dict) -> None:
    """Handle /language — show language selection keyboard."""
    user_role_service = deps["user_role_service"]
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    language_repo = deps.get("language_repo")
    config = deps["config"]

    locale = await resolve_locale(
        incoming, user_role_service, config.market.default_locale
    )
    languages = await language_repo.list_enabled() if language_repo else []
    language_prompt = (
        await bot_texts_service.get("language_prompt", locale)
    ).strip() or "Выберите язык / Choose language:"
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=language_prompt,
        keyboard=language_inline_keyboard(languages),
    )


@router.message(lambda m: bool(m.text and m.text.startswith("/country")))
async def country_command(incoming: IncomingMessage, deps: dict) -> None:
    """Handle /country — show country selection keyboard."""
    user_role_service = deps["user_role_service"]
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    country_repo = deps.get("country_repo")
    config = deps["config"]

    locale = await resolve_locale(
        incoming, user_role_service, config.market.default_locale
    )
    countries = await country_repo.list_enabled() if country_repo else []
    country_prompt = (
        await bot_texts_service.get("country_prompt", locale)
    ).strip() or "Выберите вашу страну:"
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=country_prompt,
        keyboard=country_change_inline_keyboard(countries),
    )


@router.callback(
    lambda c: bool(c.data and c.data.startswith(CALLBACK_CHANGE_COUNTRY_PREFIX))
)
async def country_change_selected(
    incoming: IncomingCallback, deps: dict
) -> None:
    """Handle country change from /country — save new country."""
    user_role_service = deps["user_role_service"]
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    country_repo = deps.get("country_repo")
    config = deps["config"]

    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    country_code = (incoming.data or "").removeprefix(
        CALLBACK_CHANGE_COUNTRY_PREFIX
    )
    if not country_code:
        return
    if country_repo:
        country = await country_repo.get_by_code(country_code)
        if country is None:
            return
    try:
        await user_role_service.set_country(
            external_id=incoming.user.external_id,
            messenger_type=incoming.user.messenger_type,
            country_code=country_code,
        )
    except UserNotFoundError:
        return
    if incoming.message_id:
        await messenger_client.edit_reply_markup(
            chat_id=incoming.chat_id,
            message_id=incoming.message_id,
            keyboard=None,
        )
    locale = await resolve_locale(
        incoming, user_role_service, config.market.default_locale
    )
    country_changed_text = (
        await bot_texts_service.get("country_changed", locale)
    ).strip() or "Страна изменена."
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=country_changed_text,
    )


@router.callback(lambda c: c.data == CALLBACK_CHANGE_ROLE)
async def change_role_callback(incoming: IncomingCallback, deps: dict) -> None:
    """Handle Change role inline button — show start screen again."""
    user_role_service = deps["user_role_service"]
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    config = deps["config"]
    state_store = deps["state_store"]

    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    locale = await resolve_locale(
        incoming, user_role_service, config.market.default_locale
    )
    start_text = (
        (await bot_texts_service.get("start_message", locale)).strip()
        or (config.market.start_text or "").strip()
        or ""
    )
    if not start_text:
        start_text = (
            "UMC — сервис для UGC.\n"
            "Бизнесу — подбор креаторов, креаторам — заказы."
        )
    texts = await bot_texts_service.get_many(
        ["btn_creator", "btn_advertiser", "btn_support"], locale
    )
    await _change_role_button(
        incoming=incoming,
        state_store=state_store,
        messenger_client=messenger_client,
        start_text=start_text,
        role_kb=role_inline_keyboard(texts),
    )


@router.message(lambda m: bool(m.text and m.text.startswith("/role")))
async def change_role_command(incoming: IncomingMessage, deps: dict) -> None:
    """Handle /role — show start screen again."""
    user_role_service = deps["user_role_service"]
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    config = deps["config"]
    state_store = deps["state_store"]

    locale = await resolve_locale(
        incoming, user_role_service, config.market.default_locale
    )
    start_text = (
        (await bot_texts_service.get("start_message", locale)).strip()
        or (config.market.start_text or "").strip()
        or ""
    )
    if not start_text:
        start_text = (
            "UMC — сервис для UGC.\n"
            "Бизнесу — подбор креаторов, креаторам — заказы."
        )
    texts = await bot_texts_service.get_many(
        ["btn_creator", "btn_advertiser", "btn_support"], locale
    )
    await _change_role_button(
        incoming=incoming,
        state_store=state_store,
        messenger_client=messenger_client,
        start_text=start_text,
        role_kb=role_inline_keyboard(texts),
    )


@router.message(lambda m: bool(m.text and m.text.startswith("/app")))
async def app_miniapp_command(incoming: IncomingMessage, deps: dict) -> None:
    """Handle /app — send button to open Mini App."""
    messenger_client = deps["messenger_client"]
    config = deps["config"]

    webhook_url = config.max_bot.webhook_url if config.max_bot else ""
    if not webhook_url:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Mini App временно недоступен.",
        )
        return

    parsed = urlparse(webhook_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    keyboard = miniapp_open_inline_keyboard(base_url, platform="max")
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Откройте приложение для регистрации и работы с заказами:",
        keyboard=keyboard,
    )


@router.callback(lambda c: c.data == CALLBACK_SUPPORT)
async def support_callback(incoming: IncomingCallback, deps: dict) -> None:
    """Handle Support button — show support options."""
    user_role_service = deps["user_role_service"]
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    config = deps["config"]
    state_store = deps["state_store"]

    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    locale = await resolve_locale(
        incoming, user_role_service, config.market.default_locale
    )
    await state_store.clear()

    support_text = (
        await bot_texts_service.get("support_response", locale)
    ).strip()
    if not support_text:
        support_text = (config.market.support_response_text or "").strip()
    if not support_text:
        support_text = (
            "Служба поддержки: @usemycontent\nОбращайтесь по любым вопросам!"
        )

    texts = await bot_texts_service.get_many(
        ["btn_support_write", "btn_change_role"], locale
    )
    rows: list[list[Button]] = []
    # Add "Write to support" button if support chat is configured
    if (config.market.support_chat_id or "").strip():
        rows.append(
            [
                Button(
                    text=texts.get(
                        "btn_support_write", "✍️ Написать в поддержку"
                    ),
                    callback_data=CALLBACK_SUPPORT_START_CHAT,
                )
            ]
        )
    rows.append(
        [
            Button(
                text=texts.get("btn_change_role", "Смена роли"),
                callback_data=CALLBACK_CHANGE_ROLE,
            )
        ]
    )
    keyboard = Keyboard(kind=KeyboardKind.INLINE, rows=rows)

    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=support_text,
        keyboard=keyboard,
    )


@router.message(lambda m: bool(m.text and m.text.startswith("/support")))
async def support_command(incoming: IncomingMessage, deps: dict) -> None:
    """Handle /support — show support options."""
    user_role_service = deps["user_role_service"]
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    config = deps["config"]
    state_store = deps["state_store"]

    locale = await resolve_locale(
        incoming, user_role_service, config.market.default_locale
    )
    await state_store.clear()

    support_text = (
        await bot_texts_service.get("support_response", locale)
    ).strip()
    if not support_text:
        support_text = (config.market.support_response_text or "").strip()
    if not support_text:
        support_text = (
            "Служба поддержки: @usemycontent\nОбращайтесь по любым вопросам!"
        )

    texts = await bot_texts_service.get_many(
        ["btn_support_write", "btn_change_role"], locale
    )
    rows: list[list[Button]] = []
    if (config.market.support_chat_id or "").strip():
        rows.append(
            [
                Button(
                    text=texts.get(
                        "btn_support_write", "✍️ Написать в поддержку"
                    ),
                    callback_data=CALLBACK_SUPPORT_START_CHAT,
                )
            ]
        )
    rows.append(
        [
            Button(
                text=texts.get("btn_change_role", "Смена роли"),
                callback_data=CALLBACK_CHANGE_ROLE,
            )
        ]
    )
    keyboard = Keyboard(kind=KeyboardKind.INLINE, rows=rows)

    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=support_text,
        keyboard=keyboard,
    )

"""E2E tests with real Telegram bot via Telethon.

Requires: bot running with webhook, TELEGRAM_E2E_* env vars set.
Tests are language-agnostic: assertions accept bot replies in RU or EN.
"""

import os
import time

import pytest

from tests.e2e.telegram_client import (
    click_inline_and_get_reply,
    click_inline_by_index_and_get_reply,
    get_bot_message_containing,
    send_and_get_reply,
    send_to_bot,
)


def _has_any(text: str | None, *keywords: str) -> bool:
    """Return True if text contains any of the keywords (case-insensitive)."""
    if not text:
        return False
    lower = text.lower()
    return any(kw.lower() in lower for kw in keywords)


def _is_language_prompt(text: str | None) -> bool:
    """Return True if text looks like the language selection prompt."""
    return _has_any(
        text, "язык", "language", "Choose language", "Выберите язык"
    )


def _is_country_prompt(text: str | None) -> bool:
    """Return True if text looks like the country selection prompt."""
    return _has_any(
        text, "страну", "country", "Россия", "Беларусь", "Казахстан"
    )  # noqa: E501


async def _maybe_select_language(
    client, entity, text: str | None, timeout: float = 15.0
) -> str | None:
    """If text is a language prompt, click lang:ru and return the new reply.

    New users (no language set) see a language selection screen first.
    Existing users (language already saved) skip this step.
    Returns the next message (country prompt or role keyboard) in both cases.
    """
    if not _is_language_prompt(text):
        return text
    return await click_inline_and_get_reply(
        client, entity, "lang:ru", timeout=timeout
    )


async def _maybe_select_country(
    client, entity, text: str | None, timeout: float = 15.0
) -> str | None:
    """If text is a country prompt, click country:ru and return the new reply.

    New users see a country selection screen before the role keyboard.
    Existing users (country already saved) skip straight to the role keyboard.
    Returns the role-keyboard message text in both cases.
    """
    if not _is_country_prompt(text):
        return text
    return await click_inline_and_get_reply(
        client, entity, "country:ru", timeout=timeout
    )


async def _maybe_select_language_and_country(
    client, entity, text: str | None, timeout: float = 15.0
) -> str | None:
    """Handle the full onboarding prologue: language → country → role.

    New users see language selection then country selection before the role
    keyboard. Existing users may see one, both, or neither step depending on
    what they already have saved.
    """
    text = await _maybe_select_language(client, entity, text, timeout=timeout)
    return await _maybe_select_country(client, entity, text, timeout=timeout)


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_start_command(telegram_user_client, telegram_e2e_config) -> None:
    """Send /start and verify welcome text and role keyboard context."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)

    text = await send_and_get_reply(
        telegram_user_client, entity, bot_username, "/start", timeout=20
    )

    assert text is not None, "Bot did not reply to /start"
    # New user: language/country prompt. Existing user: profile or menu.
    assert _has_any(
        text,
        "UMC",
        "UGC",
        "профиль",
        "profile",
        "Выберите",
        "Choose",
        "действие",
        "action",
        "страну",
        "country",
        "Россия",
        "язык",
        "language",
    )


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_role_selection_creator(
    telegram_user_client, telegram_e2e_config
) -> None:
    """Choose creator role and verify next step."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)

    text = await send_and_get_reply(
        telegram_user_client, entity, bot_username, "/start", timeout=20
    )
    text = await _maybe_select_language_and_country(
        telegram_user_client, entity, text, timeout=15
    )

    text = await click_inline_and_get_reply(
        telegram_user_client, entity, "role:creator", timeout=20
    )

    assert text is not None, "Bot did not reply to role selection"
    # New creator: intro. Existing: menu or profile.
    assert _has_any(
        text,
        "UGC",
        "creator",
        "креатор",
        "Выберите",
        "Choose",
        "профиль",
        "profile",
        "Блогер",
        "blogger",
        "fill",
        "complete",
    )


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_role_selection_advertiser(
    telegram_user_client, telegram_e2e_config
) -> None:
    """Choose advertiser role and verify next step."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)

    text = await send_and_get_reply(
        telegram_user_client, entity, bot_username, "/start", timeout=20
    )
    text = await _maybe_select_language_and_country(
        telegram_user_client, entity, text, timeout=15
    )

    text = await click_inline_and_get_reply(
        telegram_user_client, entity, "role:advertiser", timeout=25
    )

    assert text is not None, "Bot did not reply to role selection"
    assert _has_any(
        text,
        "profile",
        "профиль",
        "role",
        "роль",
        "UGC",
        "Choose",
        "Выберите",
        "Start",
        "Начать",
        "create",
        "place",
        "orders",
    )


async def _send_and_wait(
    client, entity, bot_username: str, text: str
) -> str | None:
    """Send message to bot and return the bot's reply to this message."""
    return await send_and_get_reply(
        client, entity, bot_username, text, timeout=20
    )


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_blogger_registration_full_flow(
    telegram_user_client, telegram_e2e_config
) -> None:
    """E2E: register as creator (blogger) from /start to profile created."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)
    client = telegram_user_client

    text = await send_and_get_reply(
        client, entity, bot_username, "/start", timeout=20
    )
    text = await _maybe_select_language_and_country(
        client, entity, text, timeout=15
    )
    assert text and _has_any(
        text, "UGC", "профиль", "profile", "Выберите", "Choose"
    )

    text = await click_inline_and_get_reply(
        client, entity, "role:creator", timeout=15
    )
    assert text and _has_any(
        text,
        "creator",
        "креатор",
        "profile",
        "профиль",
        "Создать",
        "Fill",
        "fill",
    )

    text = await click_inline_and_get_reply(
        client, entity, "creator:create", timeout=20
    )
    assert text is not None
    if _has_any(text, "имя", "name", "зовут", "call"):
        text = await _send_and_wait(client, entity, bot_username, "E2E Креатор")
    assert text and _has_any(text, "телефон", "phone", "номер", "number")
    text = await send_and_get_reply(
        client, entity, bot_username, "89001234567", timeout=15
    )
    assert text and _has_any(text, "инстаграмм", "instagram")
    text = await send_and_get_reply(
        client,
        entity,
        bot_username,
        f"https://instagram.com/e2etest_creator_{int(time.time())}",
        timeout=15,
    )
    assert text and _has_any(text, "город", "city")

    text = await send_and_get_reply(
        client, entity, bot_username, "Казань", timeout=15
    )
    if text and _has_any(text, "регион", "region"):
        text = await click_inline_by_index_and_get_reply(
            client, entity, index=0, timeout=15
        )
    assert text and _has_any(
        text, "дату рождения", "birth", "birthday", "дд.мм", "date"
    )

    text = await send_and_get_reply(
        client, entity, bot_username, "15.05.1995", timeout=15
    )
    assert text and _has_any(text, "пол", "gender")

    text = await click_inline_and_get_reply(
        client, entity, "blogger:gender:F", timeout=15
    )
    assert text and _has_any(text, "тематик", "topic", "контент", "content")

    text = await send_and_get_reply(
        client, entity, bot_username, "бьюти, лайфстайл", timeout=15
    )
    assert text and _has_any(
        text,
        "женщин",
        "women",
        "мужчин",
        "men",
        "поровну",
        "equal",
        "смотрит",
        "контент",
        "content",
        "аудитори",
        "audience",
        "наблюдениям",
    )

    text = await click_inline_and_get_reply(
        client, entity, "blogger:aud:F", timeout=15
    )
    assert text and _has_any(text, "возраст", "age")

    text = await click_inline_and_get_reply(
        client, entity, "blogger:age:25_34", timeout=15
    )
    assert text and _has_any(text, "аудитори", "audience", "город", "city")

    text = await send_and_get_reply(
        client, entity, bot_username, "Москва", timeout=15
    )
    assert text and _has_any(text, "цен", "price", "рубл", "rub")

    text = await send_and_get_reply(
        client, entity, bot_username, "1000", timeout=15
    )
    assert text and _has_any(text, "бартер", "barter")

    text = await click_inline_and_get_reply(
        client, entity, "blogger:barter:N", timeout=15
    )
    assert text and _has_any(text, "UGC", "размещ", "place", "post")

    text = await click_inline_and_get_reply(
        client, entity, "blogger:work:ugc", timeout=15
    )
    assert text and _has_any(text, "согласи", "agree", "consent")

    text = await click_inline_and_get_reply(
        client, entity, "blogger:agree", timeout=15
    )
    assert text is not None, "Bot did not reply after agreement"
    assert _has_any(
        text,
        "Профиль создан",
        "Profile created",
        "profile created",
        "подтвердить Instagram",
        "confirm Instagram",
        "instagram",
    )


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_advertiser_registration_full_flow(
    telegram_user_client, telegram_e2e_config
) -> None:
    """E2E: register as advertiser from /start to profile created."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)
    client = telegram_user_client

    text = await send_and_get_reply(
        client, entity, bot_username, "/start", timeout=15
    )
    text = await _maybe_select_language_and_country(
        client, entity, text, timeout=15
    )

    text = await click_inline_and_get_reply(
        client, entity, "role:advertiser", timeout=25
    )
    assert text and _has_any(
        text,
        "profile",
        "профиль",
        "UGC",
        "Choose",
        "Выберите",
        "Start",
        "Начать",
        "create",
        "place",
        "orders",
    )

    text = await click_inline_and_get_reply(
        client, entity, "adv:start", timeout=20
    )
    assert text is not None
    if _has_any(text, "зовут", "name", "имя", "call"):
        text = await _send_and_wait(
            client, entity, bot_username, "E2E Рекламодатель"
        )
    assert _has_any(text or "", "телефон", "phone", "номер", "number")

    text = await send_and_get_reply(
        client, entity, bot_username, "79001112233", timeout=15
    )
    assert text and _has_any(text, "город", "city")

    text = await send_and_get_reply(
        client, entity, bot_username, "Москва", timeout=15
    )
    assert text and _has_any(text, "бренд", "brand")

    text = await send_and_get_reply(
        client, entity, bot_username, "E2E Test Brand", timeout=15
    )
    assert text and _has_any(text, "компани", "company", "занимается", "does")

    text = await send_and_get_reply(
        client, entity, bot_username, "Тестирование E2E", timeout=15
    )
    assert text and _has_any(
        text, "сайт", "site", "ссылк", "link", "url", "website"
    )

    text = await send_and_get_reply(
        client, entity, bot_username, "https://example.com", timeout=15
    )
    assert text and _has_any(text, "согласи", "agree", "consent")

    text = await click_inline_and_get_reply(
        client, entity, "adv:agree", timeout=15
    )
    assert text is not None, "Bot did not reply after agreement"
    assert _has_any(text, "разместить заказ", "place order", "заказ", "order")


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_order_creation_full_flow(
    telegram_user_client, telegram_e2e_config
) -> None:
    """E2E: ensure advertiser then create order from start to order created."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)
    client = telegram_user_client

    text = await send_and_get_reply(
        client, entity, bot_username, "/start", timeout=20
    )
    text = await _maybe_select_language_and_country(
        client, entity, text, timeout=15
    )
    text = await click_inline_and_get_reply(
        client, entity, "role:advertiser", timeout=25
    )
    # Already advertiser: menu. New: click "Начать" (inline) then registration.
    if text and _has_any(text, "Выберите действие", "Choose action", "Select"):
        pass
    else:
        text = await click_inline_and_get_reply(
            client, entity, "adv:start", timeout=20
        )
        if text and _has_any(text, "зовут", "name", "имя", "call"):
            text = await send_and_get_reply(
                client, entity, bot_username, "E2E Advertiser", timeout=20
            )
        if text and _has_any(text, "телефон", "phone", "номер", "number"):
            text = await send_and_get_reply(
                client, entity, bot_username, "79001112233", timeout=20
            )
        if text and _has_any(text, "город", "city"):
            text = await send_and_get_reply(
                client, entity, bot_username, "Москва", timeout=20
            )
        if text and _has_any(text, "бренд", "brand"):
            text = await send_and_get_reply(
                client, entity, bot_username, "E2E Brand", timeout=20
            )
        if text and _has_any(text, "компани", "company", "занимается", "does"):
            text = await send_and_get_reply(
                client, entity, bot_username, "E2E Tests", timeout=20
            )
        if text and _has_any(
            text, "сайт", "site", "ссылк", "link", "url", "website"
        ):
            text = await send_and_get_reply(
                client, entity, bot_username, "https://example.com", timeout=20
            )
        if text and _has_any(text, "согласи", "agree", "consent"):
            await click_inline_and_get_reply(
                client, entity, "adv:agree", timeout=20
            )

    text = await click_inline_and_get_reply(
        client, entity, "profile:menu:order", timeout=25
    )
    assert text is not None
    if _has_any(text, "Профиль", "profile") and _has_any(
        text, "не заполнен", "not filled", "incomplete"
    ):
        pytest.skip("Advertiser profile not filled; run test_advertiser first")
    # Bot may show order form or ask for consent first.
    if _has_any(
        text or "", "согласи", "agree", "consent", "подтвердите", "confirm"
    ):
        await click_inline_and_get_reply(
            client, entity, "order:agree", timeout=20
        )
        text = await click_inline_and_get_reply(
            client, entity, "profile:menu:order", timeout=25
        )
        assert text is not None
    assert _has_any(
        text or "",
        "нужно",
        "need",
        "вам",
        "you",
        "опис",
        "description",
        "задач",
        "task",
        "phone",
        "number",
        "order",
        "contact",
        "enter",
    ), f"Expected order form or prompt, got: {text!r}"

    text = await click_inline_and_get_reply(
        client, entity, "order:type:ugc", timeout=15
    )
    assert text and _has_any(text, "опис", "description", "задач", "task")

    text = await send_and_get_reply(
        client, entity, bot_username, "Видео с распаковкой продукта", timeout=15
    )
    assert text and _has_any(
        text,
        "формат",
        "format",
        "сотрудничеств",
        "cooperation",
        "collaboration",
    )

    text = await click_inline_and_get_reply(
        client, entity, "order:coop:payment", timeout=15
    )
    assert text and _has_any(text, "бюджет", "budget", "цен", "price")

    text = await send_and_get_reply(
        client, entity, bot_username, "1500", timeout=15
    )
    assert text and _has_any(text, "креатор", "creator")

    text = await click_inline_and_get_reply(
        client, entity, "order:bloggers:10", timeout=15
    )
    assert text and _has_any(
        text,
        "ссылк",
        "link",
        "продукт",
        "product",
        "выберите",
        "choose",
        "select",
    )

    text = await send_and_get_reply(
        client, entity, bot_username, "https://example.com/product", timeout=15
    )
    assert text and _has_any(text, "фото", "photo")

    text = await click_inline_and_get_reply(
        client, entity, "order:photo:skip", timeout=15
    )
    assert text and _has_any(text, "использовать", "use", "UGC")

    text = await click_inline_and_get_reply(
        client, entity, "order:content:social", timeout=15
    )
    assert text and _has_any(text, "срок", "deadline", "дней", "days")

    text = await click_inline_and_get_reply(
        client, entity, "order:dl:7", timeout=15
    )
    assert text and _has_any(text, "город", "city", "регион", "region")

    await send_to_bot(client, bot_username, "Москва")
    text = await get_bot_message_containing(
        client,
        entity,
        ("Заказ создан", "Order created", "order created"),
        timeout=25,
    )
    assert text is not None, "Bot did not send order created message"
    assert _has_any(text, "Заказ создан", "Order created", "order created")


async def _ensure_blogger_profile(client, entity, bot_username: str) -> None:
    """Ensure user is in blogger context (has profile or menu); skip if not."""
    text = await send_and_get_reply(
        client, entity, bot_username, "/start", timeout=20
    )
    text = await _maybe_select_language_and_country(
        client, entity, text, timeout=15
    )
    assert text and _has_any(
        text, "UGC", "профиль", "profile", "Выберите", "Choose"
    )
    text = await click_inline_and_get_reply(
        client, entity, "role:creator", timeout=15
    )
    assert text is not None
    if not _has_any(
        text or "",
        "Выберите действие",
        "Choose action",
        "Мой профиль",
        "profile",
    ):
        pytest.skip(
            "Blogger profile required for profile update e2e. "
            "Run test_blogger_registration_full_flow first or in isolation."
        )


async def _ensure_advertiser_profile(client, entity, bot_username: str) -> None:
    """Advertiser context (has profile/menu) or skip."""
    text = await send_and_get_reply(
        client, entity, bot_username, "/start", timeout=15
    )
    text = await _maybe_select_language_and_country(
        client, entity, text, timeout=15
    )
    text = await click_inline_and_get_reply(
        client, entity, "role:advertiser", timeout=25
    )
    if not text or not _has_any(
        text, "Выберите действие", "Choose action", "Select"
    ):
        pytest.skip(
            "Advertiser profile required for profile update e2e. "
            "Run test_advertiser_registration_full_flow first or in isolation."
        )


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_blogger_profile_update(
    telegram_user_client, telegram_e2e_config
) -> None:
    """E2E: My Profile -> edit blogger (e.g. city) -> assert updated."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)
    client = telegram_user_client

    await _ensure_blogger_profile(client, entity, bot_username)

    text = await click_inline_and_get_reply(
        client, entity, "profile:menu:profile", timeout=20
    )
    assert text is not None, "Bot did not reply to My Profile"
    if _has_any(
        text or "", "согласи", "agree", "consent", "подтвердите", "confirm"
    ):
        text = await click_inline_and_get_reply(
            client, entity, "profile:agree", timeout=15
        )
        assert text is not None
    assert _has_any(text or "", "профиль", "profile", "креатор", "creator")

    # Edit profile -> choose blogger -> then city field (inline).
    text = await click_inline_and_get_reply(
        client, entity, "profile:menu:edit", timeout=20
    )
    assert text is not None
    if _has_any(
        text or "", "Выберите профиль", "Choose profile", "Select profile"
    ):
        text = await click_inline_and_get_reply(
            client, entity, "profile:type:blogger", timeout=15
        )
    assert text and _has_any(text, "раздел", "section", "field")

    text = await click_inline_and_get_reply(
        client, entity, "profile:field:city", timeout=15
    )
    assert text and _has_any(text, "город", "city")

    text = await send_and_get_reply(
        client, entity, bot_username, "Нижний Новгород", timeout=15
    )
    assert text is not None, "Bot did not reply after city value"
    # Bot may reply with "Профиль обновлён" or show profile with updated city
    assert _has_any(
        text or "",
        "обновлён",
        "updated",
        "Профиль обновлён",
        "Profile updated",
        "Нижний Новгород",
    )


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_advertiser_profile_update(
    telegram_user_client, telegram_e2e_config
) -> None:
    """E2E: My Profile -> edit advertiser (e.g. city) -> assert updated."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)
    client = telegram_user_client

    await _ensure_advertiser_profile(client, entity, bot_username)

    text = await click_inline_and_get_reply(
        client, entity, "profile:menu:profile", timeout=20
    )
    assert text is not None, "Bot did not reply to My Profile"
    if _has_any(
        text or "", "согласи", "agree", "consent", "подтвердите", "confirm"
    ):
        text = await click_inline_and_get_reply(
            client, entity, "profile:agree", timeout=15
        )
        assert text is not None
    assert _has_any(
        text or "", "профиль", "profile", "рекламодатель", "advertiser"
    )

    # Edit profile -> choose advertiser -> then city field (inline).
    text = await click_inline_and_get_reply(
        client, entity, "profile:menu:edit", timeout=20
    )
    assert text is not None
    if _has_any(
        text or "", "Выберите профиль", "Choose profile", "Select profile"
    ):
        text = await click_inline_and_get_reply(
            client, entity, "profile:type:advertiser", timeout=15
        )
    assert text and _has_any(text, "раздел", "section", "field")

    text = await click_inline_and_get_reply(
        client, entity, "profile:field:city", timeout=15
    )
    # Advertiser city uses generic prompt "Введите новое значение:" in app
    assert text and _has_any(
        text,
        "город",
        "city",
        "новое значение",
        "new value",
        "введите",
        "enter",
        "value",
    )

    text = await send_and_get_reply(
        client, entity, bot_username, "Казань", timeout=15
    )
    assert text is not None, "Bot did not reply after city value"
    # Bot may reply with "Профиль обновлён" or show profile with updated city
    assert _has_any(
        text or "",
        "обновлён",
        "updated",
        "Профиль обновлён",
        "Profile updated",
        "Казань",
    )


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_language_command(
    telegram_user_client, telegram_e2e_config
) -> None:
    """Send /language and verify language selection keyboard is shown."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)

    # Ensure user exists (send /start first).
    text = await send_and_get_reply(
        telegram_user_client, entity, bot_username, "/start", timeout=20
    )
    await _maybe_select_language_and_country(
        telegram_user_client, entity, text, timeout=15
    )

    text = await send_and_get_reply(
        telegram_user_client, entity, bot_username, "/language", timeout=20
    )

    assert text is not None, "Bot did not reply to /language"
    assert _has_any(
        text, "язык", "language", "Choose language", "Выберите язык"
    ), f"Expected language keyboard prompt, got: {text!r}"

"""E2E tests with real Telegram bot via Telethon.

Requires: bot running with webhook, TELEGRAM_E2E_* env vars set.
"""

import os
import time

import pytest

from tests.e2e.telegram_client import (
    get_bot_message_containing,
    get_last_bot_message,
    send_to_bot,
)


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

    await send_to_bot(telegram_user_client, bot_username, "/start")
    text = await get_last_bot_message(telegram_user_client, entity, timeout=20)

    assert text is not None, "Bot did not reply to /start"
    # New user: welcome (UMC). Existing user: profile or menu.
    assert (
        "UMC" in text
        or "профиль" in text
        or "Выберите действие" in text
        or "UGC" in text
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

    await send_to_bot(telegram_user_client, bot_username, "/start")
    await get_last_bot_message(telegram_user_client, entity, timeout=20)

    await send_to_bot(telegram_user_client, bot_username, "Я креатор")
    text = await get_last_bot_message(telegram_user_client, entity, timeout=20)

    assert text is not None, "Bot did not reply to role selection"
    # New creator: intro. Existing: menu or profile.
    assert (
        "UGC" in text
        or "креатор" in text
        or "Выберите" in text
        or "профиль" in text
        or "Блогер" in text
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

    await send_to_bot(telegram_user_client, bot_username, "/start")
    await get_last_bot_message(telegram_user_client, entity, timeout=20)

    await send_to_bot(
        telegram_user_client, bot_username, "Мне нужны UGC‑креаторы"
    )
    text = await get_last_bot_message(telegram_user_client, entity, timeout=25)

    assert text is not None, "Bot did not reply to role selection"
    assert (
        "профиль" in text
        or "роль" in text
        or "UGC" in text
        or "Выберите" in text
        or "Начать" in text
    )


async def _send_and_wait(
    client, entity, bot_username: str, text: str
) -> str | None:
    """Send message to bot and return last bot reply."""
    await send_to_bot(client, bot_username, text)
    return await get_last_bot_message(client, entity, timeout=20)


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

    await send_to_bot(client, bot_username, "/start")
    text = await get_last_bot_message(client, entity, timeout=20)
    assert text and ("UGC" in text or "профиль" in text or "Выберите" in text)

    await send_to_bot(client, bot_username, "Я креатор")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and (
        "креатор" in text or "профиль" in text or "Создать" in text
    )

    await send_to_bot(client, bot_username, "Создать профиль")
    text = await get_last_bot_message(client, entity, timeout=20)
    assert text is not None
    if "имя" in text.lower():
        text = await _send_and_wait(client, entity, bot_username, "E2E Креатор")
        assert text and "инстаграмм" in text.lower()
    await send_to_bot(
        client,
        bot_username,
        f"https://instagram.com/e2etest_creator_{int(time.time())}",
    )
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "город" in text.lower()

    await send_to_bot(client, bot_username, "Казань")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "пол" in text.lower()

    await send_to_bot(client, bot_username, "Женский")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "тематик" in text.lower() or "контент" in text.lower()

    await send_to_bot(client, bot_username, "бьюти, лайфстайл")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and ("женщин" in text or "мужчин" in text or "поровну" in text)

    await send_to_bot(client, bot_username, "👩 В основном женщины")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "возраст" in text.lower()

    await send_to_bot(client, bot_username, "25–34")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "аудитори" in text.lower() or "город" in text.lower()

    await send_to_bot(client, bot_username, "Москва")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "цен" in text.lower() or "рубл" in text.lower()

    await send_to_bot(client, bot_username, "1000")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "бартер" in text.lower()

    await send_to_bot(client, bot_username, "Нет")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and ("UGC" in text or "размещ" in text.lower())

    await send_to_bot(client, bot_username, "❌ Только UGC (без размещения)")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "согласи" in text.lower()

    await send_to_bot(client, bot_username, "✅ Подтвердить согласие")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text is not None, "Bot did not reply after agreement"
    assert "Профиль создан" in text or "подтвердить Instagram" in text


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

    await send_to_bot(client, bot_username, "/start")
    await get_last_bot_message(client, entity, timeout=15)

    await send_to_bot(client, bot_username, "Мне нужны UGC‑креаторы")
    text = await get_last_bot_message(client, entity, timeout=25)
    assert text and (
        "профиль" in text
        or "UGC" in text
        or "Выберите" in text
        or "Начать" in text
    )

    await send_to_bot(client, bot_username, "Начать")
    text = await get_last_bot_message(client, entity, timeout=20)
    assert text is not None
    if "зовут" in text or "имя" in text.lower():
        text = await _send_and_wait(
            client, entity, bot_username, "E2E Рекламодатель"
        )
    assert "телефон" in text.lower() or "номер" in text.lower()

    await send_to_bot(client, bot_username, "79001112233")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "город" in text.lower()

    await send_to_bot(client, bot_username, "Москва")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "бренд" in text.lower()

    await send_to_bot(client, bot_username, "E2E Test Brand")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "компани" in text.lower() or "занимается" in text

    await send_to_bot(client, bot_username, "Тестирование E2E")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "сайт" in text.lower() or "ссылк" in text.lower()

    await send_to_bot(client, bot_username, "https://example.com")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "согласи" in text.lower()

    await send_to_bot(client, bot_username, "✅ Подтвердить согласие")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text is not None, "Bot did not reply after agreement"
    assert "разместить заказ" in text or "заказ" in text


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_blogger_exit_before_consent_then_return_via_my_profile(
    telegram_user_client, telegram_e2e_config
) -> None:
    """E2E: exit blogger form before consent, then My Profile and confirm.

    Fill to agreements, /start to exit, then open My Profile and confirm.
    """
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)
    client = telegram_user_client
    suffix = int(time.time())

    await send_to_bot(client, bot_username, "/start")
    text = await get_last_bot_message(client, entity, timeout=20)
    assert text and ("UGC" in text or "профиль" in text or "Выберите" in text)

    await send_to_bot(client, bot_username, "Я креатор")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and (
        "креатор" in text or "профиль" in text or "Создать" in text
    )

    await send_to_bot(client, bot_username, "Создать профиль")
    text = await get_last_bot_message(client, entity, timeout=20)
    assert text is not None
    if "имя" in text.lower():
        text = await _send_and_wait(
            client, entity, bot_username, f"E2E ExitReturn {suffix}"
        )
        assert text and "инстаграмм" in text.lower()

    await send_to_bot(
        client,
        bot_username,
        f"https://instagram.com/e2etest_exit_return_{suffix}",
    )
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "город" in text.lower()

    await send_to_bot(client, bot_username, "Казань")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "пол" in text.lower()

    await send_to_bot(client, bot_username, "Женский")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and ("тематик" in text.lower() or "контент" in text.lower())

    await send_to_bot(client, bot_username, "бьюти, лайфстайл")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and ("женщин" in text or "мужчин" in text or "поровну" in text)

    await send_to_bot(client, bot_username, "👩 В основном женщины")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "возраст" in text.lower()

    await send_to_bot(client, bot_username, "25–34")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and ("аудитори" in text.lower() or "город" in text.lower())

    await send_to_bot(client, bot_username, "Москва")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and ("цен" in text.lower() or "рубл" in text.lower())

    await send_to_bot(client, bot_username, "1000")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "бартер" in text.lower()

    await send_to_bot(client, bot_username, "Нет")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and ("UGC" in text or "размещ" in text.lower())

    await send_to_bot(client, bot_username, "❌ Только UGC (без размещения)")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert (
        text and "согласи" in text.lower()
    ), "Expected agreements step before exit"

    # Exit: send /start instead of confirming consent (clears FSM state).
    await send_to_bot(client, bot_username, "/start")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text is not None, "Bot did not reply after /start on agreements step"
    assert (
        "прервана" in text or "Мой профиль" in text
    ), "Expected 'registration interrupted' message"

    # Return: open My Profile — bot should show agreements again.
    await send_to_bot(client, bot_username, "👤 Мой профиль")
    text = await get_last_bot_message(client, entity, timeout=20)
    assert text is not None, "Bot did not reply to My Profile"
    assert (
        "согласи" in text.lower()
    ), "Expected agreements again when opening profile without consent"

    # Confirm consent and complete registration.
    await send_to_bot(client, bot_username, "✅ Подтвердить согласие")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text is not None, "Bot did not reply after confirming consent"
    assert (
        "Профиль создан" in text or "подтвердить Instagram" in text
    ), "Expected profile created or Instagram confirmation step"


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_advertiser_exit_before_consent_then_return_via_my_profile(
    telegram_user_client, telegram_e2e_config
) -> None:
    """E2E: exit advertiser form before consent, then My Profile and confirm.

    Fill to agreements, /start to exit, then open My Profile and confirm.
    """
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)
    client = telegram_user_client

    await send_to_bot(client, bot_username, "/start")
    await get_last_bot_message(client, entity, timeout=15)

    await send_to_bot(client, bot_username, "Мне нужны UGC‑креаторы")
    text = await get_last_bot_message(client, entity, timeout=25)
    assert text and (
        "профиль" in text
        or "UGC" in text
        or "Выберите" in text
        or "Начать" in text
    )

    await send_to_bot(client, bot_username, "Начать")
    text = await get_last_bot_message(client, entity, timeout=20)
    assert text is not None
    if "зовут" in text or "имя" in text.lower():
        text = await _send_and_wait(
            client, entity, bot_username, "E2E ExitReturn Adv"
        )
    assert "телефон" in text.lower() or "номер" in text.lower()

    await send_to_bot(client, bot_username, "79009998877")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "город" in text.lower()

    await send_to_bot(client, bot_username, "Санкт-Петербург")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "бренд" in text.lower()

    await send_to_bot(client, bot_username, "E2E ExitReturn Brand")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and ("компани" in text.lower() or "занимается" in text)

    await send_to_bot(client, bot_username, "E2E тесты")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "сайт" in text.lower() or "ссылк" in text.lower()

    await send_to_bot(
        client, bot_username, "https://exit-return-e2e.example.com"
    )
    text = await get_last_bot_message(client, entity, timeout=15)
    assert (
        text and "согласи" in text.lower()
    ), "Expected agreements step before exit"

    # Exit: send /start instead of confirming consent (clears FSM state).
    await send_to_bot(client, bot_username, "/start")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text is not None, "Bot did not reply after /start on agreements step"
    assert (
        "прервана" in text or "Мой профиль" in text
    ), "Expected 'registration interrupted' message"

    # Return: open My Profile — bot should show agreements again.
    await send_to_bot(client, bot_username, "👤 Мой профиль")
    text = await get_last_bot_message(client, entity, timeout=20)
    assert text is not None, "Bot did not reply to My Profile"
    assert (
        "согласи" in text.lower()
    ), "Expected agreements again when opening profile without consent"

    # Confirm consent and complete registration.
    await send_to_bot(client, bot_username, "✅ Подтвердить согласие")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text is not None, "Bot did not reply after confirming consent"
    assert (
        "разместить заказ" in text or "заказ" in text
    ), "Expected advertiser menu after profile created"


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

    await send_to_bot(client, bot_username, "/start")
    await get_last_bot_message(client, entity, timeout=20)
    await send_to_bot(client, bot_username, "Мне нужны UGC‑креаторы")
    text = await get_last_bot_message(client, entity, timeout=25)
    # Already advertiser: menu. New: "Начать" then registration.
    if text and "Выберите действие" in text:
        pass
    else:
        await send_to_bot(client, bot_username, "Начать")
        text = await get_last_bot_message(client, entity, timeout=20)
        if text and ("зовут" in text or "имя" in text.lower()):
            await send_to_bot(client, bot_username, "E2E Advertiser")
            text = await get_last_bot_message(client, entity, timeout=20)
        if text and ("телефон" in text.lower() or "номер" in text):
            await send_to_bot(client, bot_username, "79001112233")
            text = await get_last_bot_message(client, entity, timeout=20)
        if text and "город" in text.lower():
            await send_to_bot(client, bot_username, "Москва")
            text = await get_last_bot_message(client, entity, timeout=20)
        if text and "бренд" in text.lower():
            await send_to_bot(client, bot_username, "E2E Brand")
            text = await get_last_bot_message(client, entity, timeout=20)
        if text and ("компани" in text.lower() or "занимается" in text):
            await send_to_bot(client, bot_username, "E2E Tests")
            text = await get_last_bot_message(client, entity, timeout=20)
        if text and ("сайт" in text.lower() or "ссылк" in text.lower()):
            await send_to_bot(client, bot_username, "https://example.com")
            text = await get_last_bot_message(client, entity, timeout=20)
        if text and "согласи" in text.lower():
            await send_to_bot(client, bot_username, "✅ Подтвердить согласие")
            await get_last_bot_message(client, entity, timeout=20)

    await send_to_bot(client, bot_username, "➕ Создать заказ")
    text = await get_last_bot_message(client, entity, timeout=25)
    assert text is not None
    if "Профиль" in text and "не заполнен" in text:
        pytest.skip("Advertiser profile not filled; run test_advertiser first")
    assert "нужно" in text.lower() or "вам" in text

    await send_to_bot(client, bot_username, "🎥 UGC-видео для бренда")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "опис" in text.lower() or "задач" in text.lower()

    await send_to_bot(client, bot_username, "Видео с распаковкой продукта")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "формат" in text.lower() or "сотрудничеств" in text.lower()

    await send_to_bot(client, bot_username, "💰 Оплата")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "бюджет" in text.lower() or "цен" in text.lower()

    await send_to_bot(client, bot_username, "1500")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "креатор" in text.lower()

    await send_to_bot(client, bot_username, "1")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "ссылк" in text.lower() or "продукт" in text.lower()

    await send_to_bot(client, bot_username, "https://example.com/product")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "фото" in text.lower()

    await send_to_bot(client, bot_username, "⏭ Пропустить")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "использовать" in text.lower() or "UGC" in text

    await send_to_bot(client, bot_username, "📱 В соцсетях бренда")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "срок" in text.lower() or "дней" in text

    await send_to_bot(client, bot_username, "⏱ До 7 дней")
    text = await get_last_bot_message(client, entity, timeout=15)
    assert text and "город" in text.lower() or "регион" in text.lower()

    await send_to_bot(client, bot_username, "Москва")
    text = await get_bot_message_containing(
        client, entity, "Заказ создан", timeout=25
    )
    assert text is not None, "Bot did not send order created message"
    assert "Заказ создан" in text

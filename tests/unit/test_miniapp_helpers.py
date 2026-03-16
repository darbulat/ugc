"""Tests for miniapp e2e helpers."""

from ugc_bot.miniapp.auth import validate_init_data_and_get_telegram_user_id


def test_generate_init_data_produces_valid_signature():
    from tests.e2e.miniapp_helpers import generate_init_data

    bot_token = "123456:ABC-DEF"
    user_id = 990000001
    username = "test_user"

    init_data = generate_init_data(bot_token, user_id, username)

    # Must pass the real validation from auth.py
    result = validate_init_data_and_get_telegram_user_id(init_data, bot_token)
    assert result == str(user_id)


def test_generate_init_data_contains_username():
    from tests.e2e.miniapp_helpers import generate_init_data

    init_data = generate_init_data("tok:en", 123, "alice")
    assert "alice" in init_data

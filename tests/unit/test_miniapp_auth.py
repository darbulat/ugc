"""Tests for Mini App initData validation."""

import hashlib
import hmac
import json

import pytest

from ugc_bot.miniapp.auth import (
    validate_init_data_and_get_telegram_user_id,
)


def _make_valid_init_data(bot_token: str, user_id: int) -> str:
    """Build init_data string with valid HMAC for testing."""
    user_json = json.dumps({"id": user_id, "first_name": "Test"})
    data_dict = {
        "auth_date": "1609459200",
        "user": user_json,
    }
    data_check_parts = sorted(
        (k + "=" + v for k, v in data_dict.items()),
        key=lambda x: x.split("=", 1)[0],
    )
    data_check_string = "\n".join(data_check_parts)
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode(),
        hashlib.sha256,
    ).digest()
    computed_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    data_dict["hash"] = computed_hash
    return "&".join(k + "=" + v for k, v in sorted(data_dict.items()))


class TestValidateInitDataAndGetTelegramUserId:
    """Tests for validate_init_data_and_get_telegram_user_id."""

    def test_empty_init_data_raises(self) -> None:
        """Empty or whitespace init_data raises ValueError."""
        with pytest.raises(ValueError, match="init_data is required"):
            validate_init_data_and_get_telegram_user_id("", "token")
        with pytest.raises(ValueError, match="init_data is required"):
            validate_init_data_and_get_telegram_user_id("   ", "token")

    def test_missing_hash_raises(self) -> None:
        """init_data without hash raises ValueError."""
        with pytest.raises(ValueError, match="missing hash"):
            validate_init_data_and_get_telegram_user_id(
                "user=%7B%22id%22%3A123%7D&auth_date=1609459200",
                "token",
            )

    def test_invalid_signature_raises(self) -> None:
        """Wrong hash raises ValueError."""
        init_data = "auth_date=1609459200&hash=wrong&user=%7B%22id%22%3A123%7D"
        with pytest.raises(ValueError, match="Invalid init_data signature"):
            validate_init_data_and_get_telegram_user_id(init_data, "token")

    def test_missing_user_raises(self) -> None:
        """init_data without user raises ValueError."""
        bot_token = "test_bot_token_123"
        data_dict = {"auth_date": "1609459200"}
        data_check_parts = sorted(
            (k + "=" + v for k, v in data_dict.items()),
            key=lambda x: x.split("=", 1)[0],
        )
        data_check_string = "\n".join(data_check_parts)
        secret_key = hmac.new(
            b"WebAppData", bot_token.encode(), hashlib.sha256
        ).digest()
        computed_hash = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()
        data_dict["hash"] = computed_hash
        init_data = "&".join(k + "=" + v for k, v in sorted(data_dict.items()))
        with pytest.raises(ValueError, match="missing user"):
            validate_init_data_and_get_telegram_user_id(init_data, bot_token)

    def test_user_not_json_raises(self) -> None:
        """user value that is not valid JSON raises ValueError."""
        bot_token = "test_bot_token"
        data_dict = {"auth_date": "1609459200", "user": "not-json"}
        data_check_parts = sorted(
            (k + "=" + v for k, v in data_dict.items()),
            key=lambda x: x.split("=", 1)[0],
        )
        data_check_string = "\n".join(data_check_parts)
        secret_key = hmac.new(
            b"WebAppData", bot_token.encode(), hashlib.sha256
        ).digest()
        computed_hash = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()
        data_dict["hash"] = computed_hash
        init_data = "&".join(k + "=" + v for k, v in sorted(data_dict.items()))
        with pytest.raises(ValueError, match="not valid JSON"):
            validate_init_data_and_get_telegram_user_id(init_data, bot_token)

    def test_user_missing_id_raises(self) -> None:
        """user object without id raises ValueError."""
        bot_token = "test_bot_token"
        user_json = json.dumps({"first_name": "Test"})
        data_dict = {"auth_date": "1609459200", "user": user_json}
        data_check_parts = sorted(
            (k + "=" + v for k, v in data_dict.items()),
            key=lambda x: x.split("=", 1)[0],
        )
        data_check_string = "\n".join(data_check_parts)
        secret_key = hmac.new(
            b"WebAppData", bot_token.encode(), hashlib.sha256
        ).digest()
        computed_hash = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()
        data_dict["hash"] = computed_hash
        init_data = "&".join(k + "=" + v for k, v in sorted(data_dict.items()))
        with pytest.raises(ValueError, match="missing id"):
            validate_init_data_and_get_telegram_user_id(init_data, bot_token)

    def test_valid_init_data_returns_telegram_user_id(self) -> None:
        """Valid init_data returns Telegram user id as string."""
        bot_token = "test_bot_token_456"
        user_id = 123456789
        init_data = _make_valid_init_data(bot_token, user_id)
        result = validate_init_data_and_get_telegram_user_id(
            init_data, bot_token
        )
        assert result == str(user_id)

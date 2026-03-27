"""Tests for Mini App initData validation."""

import hashlib
import hmac
import json

import pytest

from ugc_bot.miniapp.auth import (
    get_telegram_user_id_and_username,
    validate_init_data_and_get_telegram_user_id,
)


def _make_valid_init_data(
    bot_token: str,
    user_id: int,
    username: str | None = None,
) -> str:
    """Build init_data string with valid HMAC for testing."""
    user_obj: dict = {"id": user_id, "first_name": "Test"}
    if username is not None:
        user_obj["username"] = username
    user_json = json.dumps(user_obj)
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


class TestGetTelegramUserIdAndUsername:
    """Tests for get_telegram_user_id_and_username."""

    def test_returns_user_id_and_username(self) -> None:
        """Valid init_data with username returns (id, username)."""
        bot_token = "test_bot_789"
        init_data = _make_valid_init_data(
            bot_token, 111222333, username="johndoe"
        )
        user_id, username = get_telegram_user_id_and_username(
            init_data, bot_token
        )
        assert user_id == "111222333"
        assert username == "johndoe"

    def test_returns_none_username_when_missing(self) -> None:
        """Valid init_data without username returns (id, None)."""
        bot_token = "test_bot_789"
        init_data = _make_valid_init_data(bot_token, 444555666)
        user_id, username = get_telegram_user_id_and_username(
            init_data, bot_token
        )
        assert user_id == "444555666"
        assert username is None

    def test_invalid_init_data_raises(self) -> None:
        """Invalid init_data raises ValueError."""
        with pytest.raises(ValueError):
            get_telegram_user_id_and_username("", "token")

    def test_empty_username_returns_none(self) -> None:
        """Username that is empty string returns None."""
        bot_token = "test_bot_789"
        init_data = _make_valid_init_data(bot_token, 777888999, username="")
        _, username = get_telegram_user_id_and_username(init_data, bot_token)
        assert username is None

    def test_whitespace_username_returns_none(self) -> None:
        """Username that is only whitespace returns None."""
        bot_token = "test_bot_789"
        init_data = _make_valid_init_data(bot_token, 123456, username="   ")
        _, username = get_telegram_user_id_and_username(init_data, bot_token)
        assert username is None

    def test_non_string_username_returns_none(self) -> None:
        """User object with non-string username (e.g. number) returns None."""
        bot_token = "test_bot_789"
        user_obj = {"id": 321654, "username": 12345}
        user_json = json.dumps(user_obj)
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
        user_id, username = get_telegram_user_id_and_username(
            init_data, bot_token
        )
        assert user_id == "321654"
        assert username is None


def _make_valid_init_data_with_user_json(bot_token: str, user_json: str) -> str:
    """Build init_data where user field holds arbitrary raw JSON string."""
    data_dict = {"auth_date": "1609459200", "user": user_json}
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


class TestValidateInitDataUserNotDict:
    """User JSON valid but not a dict branch (line 76)."""

    def test_user_is_list_raises_value_error(self) -> None:
        """User JSON as list raises ValueError 'user must be an object'."""
        bot_token = "token_list_test"
        user_json = json.dumps([1, 2, 3])
        init_data = _make_valid_init_data_with_user_json(bot_token, user_json)
        with pytest.raises(ValueError, match="user must be an object"):
            validate_init_data_and_get_telegram_user_id(init_data, bot_token)

    def test_user_is_number_raises_value_error(self) -> None:
        """User JSON as number raises ValueError 'user must be an object'."""
        bot_token = "token_num_test"
        user_json = "42"
        init_data = _make_valid_init_data_with_user_json(bot_token, user_json)
        with pytest.raises(ValueError, match="user must be an object"):
            validate_init_data_and_get_telegram_user_id(init_data, bot_token)


class TestValidateInitDataForPlatform:
    def test_telegram_platform_uses_telegram_token(self) -> None:
        from ugc_bot.miniapp.auth import validate_init_data_for_platform

        tg_token = "tg_token_123"
        max_token = "max_token_456"
        init_data = _make_valid_init_data(tg_token, 111)
        result = validate_init_data_for_platform(
            init_data,
            platform="telegram",
            telegram_bot_token=tg_token,
            max_bot_token=max_token,
        )
        assert result == "111"

    def test_max_platform_uses_max_token(self) -> None:
        from ugc_bot.miniapp.auth import validate_init_data_for_platform

        tg_token = "tg_token_123"
        max_token = "max_token_456"
        init_data = _make_valid_init_data(max_token, 222)
        result = validate_init_data_for_platform(
            init_data,
            platform="max",
            telegram_bot_token=tg_token,
            max_bot_token=max_token,
        )
        assert result == "222"

    def test_unknown_platform_raises(self) -> None:
        from ugc_bot.miniapp.auth import validate_init_data_for_platform

        with pytest.raises(ValueError, match="Unknown platform"):
            validate_init_data_for_platform(
                "any",
                platform="vk",
                telegram_bot_token="t",
                max_bot_token="m",
            )

    def test_max_with_telegram_token_fails(self) -> None:
        from ugc_bot.miniapp.auth import validate_init_data_for_platform

        max_token = "max_token_789"
        init_data = _make_valid_init_data(max_token, 333)
        with pytest.raises(ValueError, match="Invalid init_data signature"):
            validate_init_data_for_platform(
                init_data,
                platform="telegram",
                telegram_bot_token="wrong_token",
                max_bot_token=max_token,
            )


class TestGetTelegramUserIdAndUsernameGuardBranches:
    """Tests for defensive branches in get_telegram_user_id_and_username."""

    def test_no_user_json_in_parse_returns_external_id_and_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When parse_qsl returns no user key, returns (id, None) (line 99)."""
        from ugc_bot.miniapp import auth as auth_module

        # Patch validate_init_data_and_get_telegram_user_id to return directly
        monkeypatch.setattr(
            auth_module,
            "validate_init_data_and_get_telegram_user_id",
            lambda init_data, token: "12345",
        )
        # Patch parse_qsl to return data without 'user' key
        monkeypatch.setattr(
            auth_module,
            "parse_qsl",
            lambda s, **kwargs: [("auth_date", "1609459200"), ("hash", "abc")],
        )

        user_id, username = auth_module.get_telegram_user_id_and_username(
            "any_init_data", "any_token"
        )
        assert user_id == "12345"
        assert username is None

    def test_user_json_invalid_in_parse_returns_none_username(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When user JSON is invalid, returns (id, None) (lines 102-103)."""
        from ugc_bot.miniapp import auth as auth_module

        monkeypatch.setattr(
            auth_module,
            "validate_init_data_and_get_telegram_user_id",
            lambda init_data, token: "99999",
        )
        monkeypatch.setattr(
            auth_module,
            "parse_qsl",
            lambda s, **kwargs: [
                ("user", "not-valid-json"),
                ("auth_date", "1609459200"),
            ],
        )

        user_id, username = auth_module.get_telegram_user_id_and_username(
            "any_init_data", "any_token"
        )
        assert user_id == "99999"
        assert username is None

    def test_user_is_not_dict_in_parse_returns_none_username(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When user JSON is not a dict, returns (id, None) (line 105)."""
        from ugc_bot.miniapp import auth as auth_module

        monkeypatch.setattr(
            auth_module,
            "validate_init_data_and_get_telegram_user_id",
            lambda init_data, token: "77777",
        )
        # user is a list — valid JSON but not a dict
        monkeypatch.setattr(
            auth_module,
            "parse_qsl",
            lambda s, **kwargs: [
                ("user", "[1,2,3]"),
                ("auth_date", "1609459200"),
            ],
        )

        user_id, username = auth_module.get_telegram_user_id_and_username(
            "any_init_data", "any_token"
        )
        assert user_id == "77777"
        assert username is None

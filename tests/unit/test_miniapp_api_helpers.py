"""Tests for miniapp API helper functions."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from ugc_bot.miniapp.api import (
    RegisterAdvertiserRequest,
    RegisterBloggerRequest,
    _get_telegram_user_id,
    _get_telegram_username_from_init_data,
    _parse_birth_date_optional,
    _validate_advertiser_body,
    _validate_blogger_body,
)


def _make_request(bot_token: str = "test_token") -> MagicMock:
    """Create a mock FastAPI Request with minimal state."""
    config = MagicMock()
    config.bot.bot_token = bot_token
    request = MagicMock()
    request.app.state.config = config
    return request


class TestGetTelegramUserIdHelper:
    """Tests for _get_telegram_user_id (lines 246-248)."""

    def test_invalid_init_data_raises_http_401(self) -> None:
        """ValueError from validate_init_data_... becomes HTTP 401."""
        request = _make_request()
        with pytest.raises(HTTPException) as exc_info:
            _get_telegram_user_id(request, "invalid_init_data")
        assert exc_info.value.status_code == 401

    def test_empty_init_data_raises_http_401(self) -> None:
        """Empty init_data raises HTTPException 401."""
        request = _make_request()
        with pytest.raises(HTTPException) as exc_info:
            _get_telegram_user_id(request, "")
        assert exc_info.value.status_code == 401


class TestGetTelegramUsernameFromInitDataHelper:
    """Tests for _get_telegram_username_from_init_data (lines 261-262)."""

    def test_invalid_init_data_returns_none(self) -> None:
        """ValueError from get_telegram_user_id_and_username returns None."""
        request = _make_request()
        result = _get_telegram_username_from_init_data(request, "invalid_data")
        assert result is None

    def test_empty_init_data_returns_none(self) -> None:
        """Empty init_data returns None."""
        request = _make_request()
        result = _get_telegram_username_from_init_data(request, "")
        assert result is None


class TestValidateAdvertiserBodyHelper:
    """Tests for _validate_advertiser_body (lines 409, 416)."""

    def test_invalid_brand_returns_error(self) -> None:
        """validate_brand returns error when brand is too short (line 409)."""
        body = RegisterAdvertiserRequest(
            init_data="x",
            phone="89001110777",
            brand="A",  # too short (min 2)
        )
        err = _validate_advertiser_body(body, texts={})
        assert err is not None

    def test_invalid_city_via_bot_command_returns_error(self) -> None:
        """validate_city returns error when city is a bot command (line 415)."""
        body = RegisterAdvertiserRequest(
            init_data="x",
            phone="89001110777",
            brand="TestBrand",
            city="/profile",
        )
        err = _validate_advertiser_body(body, texts={})
        assert err is not None

    def test_invalid_company_activity_via_bot_command_returns_error(
        self,
    ) -> None:
        """validate_company_activity returns error for bot command."""
        body = RegisterAdvertiserRequest(
            init_data="x",
            phone="89001110777",
            brand="TestBrand",
            city=None,
            company_activity="/creator",
        )
        err = _validate_advertiser_body(body, texts={})
        assert err is not None

    def test_valid_body_returns_none(self) -> None:
        """Valid advertiser body returns None."""
        body = RegisterAdvertiserRequest(
            init_data="x",
            phone="89001110777",
            brand="TestBrand",
        )
        err = _validate_advertiser_body(body, texts={})
        assert err is None


class TestValidateBloggerBodyHelper:
    """Tests for _validate_blogger_body (lines 524, 536, 539)."""

    def _valid_body(self, **overrides) -> RegisterBloggerRequest:
        """Build a valid RegisterBloggerRequest."""
        defaults = dict(
            init_data="x",
            instagram_url="https://instagram.com/valid_user",
            city="Moscow",
            audience_geo="Moscow",
            audience_age_min=18,
            audience_age_max=35,
            audience_gender="all",
            price=1000.0,
            barter=False,
            work_format="ugc_only",
            topics=["fitness"],
            display_name="MyNick",
        )
        defaults.update(overrides)
        return RegisterBloggerRequest(**defaults)

    def test_invalid_display_name_returns_error(self) -> None:
        """Invalid display_name (too short) returns error (line 524)."""
        body = self._valid_body(display_name="A")
        err = _validate_blogger_body(
            body, texts={}, max_price=100000, currency_symbol="₽"
        )
        assert err is not None

    def test_invalid_city_returns_error(self) -> None:
        """Invalid city (bot command) returns error (line 536)."""
        body = self._valid_body(city="/profile")
        err = _validate_blogger_body(
            body, texts={}, max_price=100000, currency_symbol="₽"
        )
        assert err is not None

    def test_invalid_audience_geo_returns_error(self) -> None:
        """Invalid audience_geo (empty) returns error (line 539)."""
        body = self._valid_body(audience_geo="")
        err = _validate_blogger_body(
            body, texts={}, max_price=100000, currency_symbol="₽"
        )
        assert err is not None

    def test_valid_body_returns_none(self) -> None:
        """Valid blogger body returns None."""
        body = self._valid_body()
        err = _validate_blogger_body(
            body, texts={}, max_price=100000, currency_symbol="₽"
        )
        assert err is None


class TestParseBirthDateOptionalHelper:
    """Tests for _parse_birth_date_optional (line 783)."""

    def test_invalid_birth_date_raises_http_400(self) -> None:
        """Invalid birth date string raises HTTPException 400 (line 783)."""
        with pytest.raises(HTTPException) as exc_info:
            _parse_birth_date_optional("not-a-date", texts={})
        assert exc_info.value.status_code == 400

    def test_empty_birth_date_returns_none(self) -> None:
        """Empty or None birth date returns None without error."""
        assert _parse_birth_date_optional("", texts={}) is None
        assert _parse_birth_date_optional(None, texts={}) is None

    def test_valid_birth_date_returns_date(self) -> None:
        """Valid birth date string returns date object."""
        from datetime import date

        result = _parse_birth_date_optional("15.05.1995", texts={})
        assert result == date(1995, 5, 15)

"""Tests for miniapp API helper functions."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from ugc_bot.miniapp.api import (
    RegisterAdvertiserRequest,
    RegisterBloggerRequest,
    _get_external_id,
    _get_username_from_init_data,
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


class TestGetExternalIdHelper:
    """Tests for _get_external_id."""

    def test_invalid_init_data_raises_http_401(self) -> None:
        """ValueError from validate becomes HTTP 401."""
        request = _make_request()
        with pytest.raises(HTTPException) as exc_info:
            _get_external_id(request, "invalid_init_data")
        assert exc_info.value.status_code == 401

    def test_empty_init_data_raises_http_401(self) -> None:
        """Empty init_data raises HTTPException 401."""
        request = _make_request()
        with pytest.raises(HTTPException) as exc_info:
            _get_external_id(request, "")
        assert exc_info.value.status_code == 401


class TestGetUsernameFromInitDataHelper:
    """Tests for _get_username_from_init_data."""

    def test_invalid_init_data_returns_none(self) -> None:
        """Invalid init_data returns None."""
        request = _make_request()
        result = _get_username_from_init_data(request, "invalid_data")
        assert result is None

    def test_empty_init_data_returns_none(self) -> None:
        """Empty init_data returns None."""
        request = _make_request()
        result = _get_username_from_init_data(request, "")
        assert result is None


class TestExtractUsernameFromInitData:
    """Tests for _extract_username_from_init_data."""

    def test_extracts_username(self) -> None:
        from ugc_bot.miniapp.api import _extract_username_from_init_data

        init_data = (
            "user=%7B%22id%22%3A123%2C%22username%22%3A%22joe%22%7D&auth_date=1"
        )
        assert _extract_username_from_init_data(init_data) == "joe"

    def test_returns_none_for_missing_user(self) -> None:
        from ugc_bot.miniapp.api import _extract_username_from_init_data

        assert _extract_username_from_init_data("auth_date=1") is None

    def test_returns_none_for_invalid_json(self) -> None:
        from ugc_bot.miniapp.api import _extract_username_from_init_data

        assert (
            _extract_username_from_init_data("user=notjson&auth_date=1") is None
        )

    def test_returns_none_for_empty(self) -> None:
        from ugc_bot.miniapp.api import _extract_username_from_init_data

        assert _extract_username_from_init_data("") is None


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


class TestSetCountryEndpoint:
    """Tests for the set_country endpoint handler (lines 1233-1253)."""

    @pytest.mark.asyncio
    async def test_set_country_no_country_repo_uses_default_currency(
        self,
    ) -> None:
        """When country_repo is absent, fallback to RUB."""
        from unittest.mock import AsyncMock, patch
        from uuid import uuid4

        from ugc_bot.miniapp.api import SetCountryRequest, set_country

        request = MagicMock()
        dispatcher = MagicMock()
        dispatcher.get.return_value = None  # no country_repo
        user_role_service = MagicMock()
        user_role_service.set_country = AsyncMock()
        dispatcher.__getitem__ = lambda self, k: user_role_service
        request.app.state.dispatcher = dispatcher

        body = SetCountryRequest(init_data="x", country_code="ru")

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                new=AsyncMock(return_value=uuid4()),
            ),
            patch(
                "ugc_bot.miniapp.api._get_external_id",
                return_value="123",
            ),
        ):
            result = await set_country(request, body)

        assert result["ok"] is True
        assert result["currency_code"] == "RUB"
        assert result["currency_symbol"] == "₽"

    @pytest.mark.asyncio
    async def test_set_country_with_country_repo_returns_currency(
        self,
    ) -> None:
        """When country_repo present, returns currency from country object."""
        from unittest.mock import AsyncMock, patch
        from uuid import uuid4

        from ugc_bot.domain.entities import Country
        from ugc_bot.miniapp.api import SetCountryRequest, set_country

        ru = Country(
            code="ru",
            name_native="Россия",
            currency_code="RUB",
            currency_symbol="₽",
        )
        country_repo = MagicMock()
        country_repo.get_by_code = AsyncMock(return_value=ru)

        user_role_service = MagicMock()
        user_role_service.set_country = AsyncMock()

        dispatcher = MagicMock()
        dispatcher.get.return_value = country_repo
        dispatcher.__getitem__ = lambda self, k: user_role_service

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = SetCountryRequest(init_data="x", country_code="ru")

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                new=AsyncMock(return_value=uuid4()),
            ),
            patch(
                "ugc_bot.miniapp.api._get_external_id",
                return_value="123",
            ),
        ):
            result = await set_country(request, body)

        assert result["ok"] is True
        assert result["currency_code"] == "RUB"
        assert result["currency_symbol"] == "₽"

    @pytest.mark.asyncio
    async def test_set_country_unknown_country_code_raises_400(self) -> None:
        """Unknown country code raises HTTPException 400."""
        from unittest.mock import AsyncMock, patch
        from uuid import uuid4

        from ugc_bot.miniapp.api import SetCountryRequest, set_country

        country_repo = MagicMock()
        country_repo.get_by_code = AsyncMock(return_value=None)

        dispatcher = MagicMock()
        dispatcher.get.return_value = country_repo

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = SetCountryRequest(init_data="x", country_code="zz")

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                new=AsyncMock(return_value=uuid4()),
            ),
            patch(
                "ugc_bot.miniapp.api._get_external_id",
                return_value="123",
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await set_country(request, body)

        assert exc_info.value.status_code == 400


class TestMeEndpointCountryResolution:
    """Tests for me endpoint country/currency resolution (lines 362-365)."""

    @pytest.mark.asyncio
    async def test_me_resolves_currency_from_country(self) -> None:
        """me endpoint resolves currency_code and symbol via country_repo."""
        from unittest.mock import AsyncMock, patch
        from uuid import uuid4

        from ugc_bot.domain.entities import Country
        from ugc_bot.miniapp.api import InitDataBody, me

        ru = Country(
            code="ru",
            name_native="Россия",
            currency_code="RUB",
            currency_symbol="₽",
        )
        country_repo = MagicMock()
        country_repo.get_by_code = AsyncMock(return_value=ru)

        user = MagicMock()
        user.telegram_id = "123"
        user.country = "ru"
        user.language = None

        profile_service = MagicMock()
        profile_service.get_advertiser_profile = AsyncMock(return_value=None)
        profile_service.get_blogger_profile = AsyncMock(return_value=None)
        profile_service.get_user_by_external = AsyncMock(return_value=user)

        def dispatcher_get(key):
            if key == "country_repo":
                return country_repo
            return None

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: profile_service
        dispatcher.get = dispatcher_get

        uid = uuid4()
        request = MagicMock()
        request.app.state.dispatcher = dispatcher
        request.app.state.config.market.default_locale = "ru"

        body = InitDataBody(init_data="x")

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                new=AsyncMock(return_value=uid),
            ),
            patch(
                "ugc_bot.miniapp.api._get_external_id",
                return_value="123",
            ),
        ):
            result = await me(request, body)

        assert result.country == "ru"
        assert result.currency_code == "RUB"
        assert result.currency_symbol == "₽"


class TestConfigEndpointCountries:
    """Tests for config endpoint countries list (lines 404-405)."""

    @pytest.mark.asyncio
    async def test_config_includes_countries_when_repo_present(self) -> None:
        """config endpoint includes countries from country_repo."""
        from unittest.mock import AsyncMock, patch
        from uuid import uuid4

        from ugc_bot.domain.entities import Country
        from ugc_bot.miniapp.api import InitDataBody
        from ugc_bot.miniapp.api import config as config_endpoint

        ru = Country(
            code="ru",
            name_native="Россия",
            currency_code="RUB",
            currency_symbol="₽",
        )
        country_repo = MagicMock()
        country_repo.list_enabled = AsyncMock(return_value=[ru])

        def dispatcher_get(key):
            if key == "country_repo":
                return country_repo
            return None

        order_cfg = MagicMock()
        order_cfg.get_allowed_blogger_counts_set.return_value = {1, 3, 5}

        cfg = MagicMock()
        cfg.order = order_cfg
        cfg.bot.bot_username = "testbot"
        docs = MagicMock()
        docs.docs_offer_url = ""
        docs.docs_privacy_url = ""
        docs.docs_consent_url = ""
        docs.docs_offer_url_intl = ""
        docs.docs_privacy_url_intl = ""
        docs.docs_consent_url_intl = ""
        cfg.docs = docs
        cfg.instagram.admin_instagram_username = ""

        dispatcher = MagicMock()
        dispatcher.get = dispatcher_get

        request = MagicMock()
        request.app.state.config = cfg
        request.app.state.dispatcher = dispatcher

        body = InitDataBody(init_data="x")

        with patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=uuid4()),
        ):
            result = await config_endpoint(request, body)

        assert len(result.countries) == 1
        assert result.countries[0]["code"] == "ru"
        assert result.countries[0]["currency_code"] == "RUB"


@pytest.mark.asyncio
async def test_currency_symbol_map_returns_code_to_symbol_mapping() -> None:
    """_currency_symbol_map builds currency_code to currency_symbol dict."""
    from unittest.mock import AsyncMock, MagicMock

    from ugc_bot.miniapp.api import _currency_symbol_map

    country1 = MagicMock()
    country1.currency_code = "RUB"
    country1.currency_symbol = "₽"

    country2 = MagicMock()
    country2.currency_code = "USD"
    country2.currency_symbol = "$"

    # Duplicate currency_code — only first should be kept
    country3 = MagicMock()
    country3.currency_code = "RUB"
    country3.currency_symbol = "RUB"

    country_repo = MagicMock()
    country_repo.list_enabled = AsyncMock(
        return_value=[country1, country2, country3]
    )

    dispatcher = MagicMock()
    dispatcher.get = MagicMock(return_value=country_repo)

    request = MagicMock()
    request.app.state.dispatcher = dispatcher

    result = await _currency_symbol_map(request)

    assert result == {"RUB": "₽", "USD": "$"}

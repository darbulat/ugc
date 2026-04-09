"""Tests for bot input validators."""

from datetime import date

from ugc_bot.bot.telegram.validators import (
    FORBIDDEN_BOT_COMMANDS,
    normalize_instagram_url,
    normalize_url,
    validate_audience_geo,
    validate_barter_description,
    validate_birth_date,
    validate_brand,
    validate_city,
    validate_company_activity,
    validate_geography,
    validate_instagram_url,
    validate_name,
    validate_nickname,
    validate_not_bot_command,
    validate_offer_text,
    validate_phone,
    validate_price,
    validate_product_link,
    validate_site_link,
    validate_topics,
    validate_url,
)


class TestValidateNotBotCommand:
    """Tests for validate_not_bot_command (forbidden commands not saved)."""

    def test_empty_or_whitespace_ok(self) -> None:
        assert validate_not_bot_command("") is None
        assert validate_not_bot_command("   ") is None

    def test_forbidden_commands_rejected(self) -> None:
        for cmd in FORBIDDEN_BOT_COMMANDS:
            err = validate_not_bot_command(cmd)
            assert err is not None, cmd
            assert validate_not_bot_command(cmd.upper()) is not None, cmd
            err_lower = (err or "").lower()
            assert "команд" in err_lower or "command" in err_lower

    def test_profile_creator_advertiser_rejected(self) -> None:
        assert validate_not_bot_command("/profile") is not None
        assert validate_not_bot_command("/creator") is not None
        assert validate_not_bot_command("/advertiser") is not None
        assert validate_not_bot_command("/Profile") is not None

    def test_support_allowed(self) -> None:
        assert validate_not_bot_command("/support") is None
        assert validate_not_bot_command("/Support") is None

    def test_ordinary_text_ok(self) -> None:
        assert validate_not_bot_command("Казань") is None
        assert validate_not_bot_command("Москва, РФ") is None
        assert (
            validate_not_bot_command("Напишите в /support если нужна помощь")
            is None
        )


class TestValidateOfferText:
    """Tests for validate_offer_text."""

    def test_bot_command_rejected(self) -> None:
        assert validate_offer_text("/profile") is not None
        assert validate_offer_text("/creator") is not None
        assert validate_offer_text("/advertiser") is not None

    def test_empty_returns_error(self) -> None:
        assert validate_offer_text("") is not None
        assert "20" in (validate_offer_text("") or "")

    def test_too_short_returns_error(self) -> None:
        assert validate_offer_text("Short") is not None

    def test_min_length_ok(self) -> None:
        assert validate_offer_text("A" * 20) is None

    def test_max_length_ok(self) -> None:
        assert validate_offer_text("A" * 2000) is None

    def test_over_max_returns_error(self) -> None:
        assert validate_offer_text("A" * 2001) is not None


class TestValidateBarterDescription:
    """Tests for validate_barter_description."""

    def test_required_empty_returns_error(self) -> None:
        assert validate_barter_description("", required=True) is not None

    def test_required_whitespace_returns_error(self) -> None:
        assert validate_barter_description("   ", required=True) is not None

    def test_not_required_empty_ok(self) -> None:
        assert validate_barter_description("", required=False) is None

    def test_too_short_when_provided_returns_error(self) -> None:
        assert validate_barter_description("Short", required=False) is not None

    def test_bot_command_rejected(self) -> None:
        assert (
            validate_barter_description("/profile", required=False) is not None
        )
        assert (
            validate_barter_description("/creator", required=True) is not None
        )

    def test_min_length_ok(self) -> None:
        assert validate_barter_description("A" * 10, required=True) is None

    def test_over_max_returns_error(self) -> None:
        assert (
            validate_barter_description("A" * 501, required=False) is not None
        )


class TestValidateProductLink:
    """Tests for validate_product_link."""

    def test_empty_returns_error(self) -> None:
        assert validate_product_link("") is not None

    def test_invalid_url_returns_error(self) -> None:
        assert validate_product_link("not-a-url") is not None
        assert validate_product_link("ftp://example.com") is not None

    def test_valid_https_ok(self) -> None:
        assert validate_product_link("https://example.com/product") is None

    def test_valid_http_ok(self) -> None:
        assert validate_product_link("http://example.com") is None

    def test_valid_domain_without_scheme_ok(self) -> None:
        assert validate_product_link("example.com") is None
        assert validate_product_link("сайт.рф") is None


class TestValidateBirthDate:
    """Tests for validate_birth_date."""

    def test_empty_returns_error(self) -> None:
        d, err = validate_birth_date("")
        assert d is None
        assert err is not None
        err_lower = (err or "").lower()
        assert (
            "формат" in err_lower
            or "дату" in err_lower
            or "format" in err_lower
            or "date" in err_lower
        )

    def test_wrong_format_returns_error(self) -> None:
        d, err = validate_birth_date("15-05-1995")
        assert d is None
        assert err is not None

    def test_non_numeric_returns_error(self) -> None:
        d, err = validate_birth_date("ab.cd.efgh")
        assert d is None
        assert err is not None

    def test_invalid_date_returns_error(self) -> None:
        d, err = validate_birth_date("32.13.2000")
        assert d is None
        assert err is not None
        err_lower = (err or "").lower()
        assert (
            "некоррект" in err_lower
            or "дату" in err_lower
            or "invalid" in err_lower
            or "date" in err_lower
        )

    def test_future_date_returns_error(self) -> None:
        d, err = validate_birth_date("01.01.2030")
        assert d is None
        assert err is not None
        err_lower = (err or "").lower()
        assert "будущ" in err_lower or "future" in err_lower

    def test_age_too_young_returns_error(self) -> None:
        # Use a birth date that is always under min age (10) regardless of today
        d, err = validate_birth_date("25.02.2022")
        assert d is None
        assert err is not None
        assert "10" in (err or "")

    def test_age_too_old_returns_error(self) -> None:
        d, err = validate_birth_date("01.01.1920")
        assert d is None
        assert err is not None
        assert "100" in (err or "") or "реальную" in (err or "").lower()

    def test_valid_returns_date(self) -> None:
        d, err = validate_birth_date("15.05.1995")
        assert err is None
        assert d == date(1995, 5, 15)

    def test_valid_min_age_ok(self) -> None:
        d, err = validate_birth_date("01.01.2010")
        assert err is None
        assert d == date(2010, 1, 1)


class TestValidateGeography:
    """Tests for validate_geography."""

    def test_empty_returns_error(self) -> None:
        assert validate_geography("") is not None

    def test_bot_command_rejected(self) -> None:
        assert validate_geography("/profile") is not None
        assert validate_geography("/advertiser") is not None

    def test_valid_ok(self) -> None:
        assert validate_geography("Казань, Москва") is None
        assert validate_geography("РФ") is None

    def test_over_max_returns_error(self) -> None:
        assert validate_geography("A" * 501) is not None


class TestValidateName:
    """Tests for validate_name."""

    def test_empty_returns_error(self) -> None:
        assert validate_name("") is not None

    def test_single_char_returns_error(self) -> None:
        assert validate_name("A") is not None

    def test_bot_command_rejected(self) -> None:
        assert validate_name("/profile") is not None
        assert validate_name("/creator") is not None

    def test_min_length_ok(self) -> None:
        assert validate_name("Ab") is None

    def test_over_max_returns_error(self) -> None:
        assert validate_name("A" * 101) is not None


class TestValidatePhone:
    """Tests for validate_phone."""

    def test_empty_returns_error(self) -> None:
        assert validate_phone("") is not None

    def test_too_few_digits_returns_error(self) -> None:
        assert validate_phone("123") is not None
        assert validate_phone("+7900") is not None

    def test_valid_10_digits_ok(self) -> None:
        assert validate_phone("9001110777") is None

    def test_valid_11_digits_8_prefix_ok(self) -> None:
        assert validate_phone("89001110777") is None

    def test_valid_11_digits_7_prefix_ok(self) -> None:
        assert validate_phone("79001110777") is None

    def test_valid_with_formatting_ok(self) -> None:
        assert validate_phone("+7 (900) 111-07-77") is None
        assert validate_phone("8-900-111-07-77") is None

    def test_valid_uzbekistan_number_ok(self) -> None:
        """Uzbekistan numbers (+998 prefix, 12 digits) must be accepted."""
        assert validate_phone("+998901234567") is None
        assert validate_phone("998901234567") is None
        assert validate_phone("+998 90 123 45 67") is None

    def test_valid_kazakhstan_number_ok(self) -> None:
        """Kazakhstan numbers (+7 prefix) must be accepted."""
        assert validate_phone("+77011234567") is None

    def test_valid_us_number_ok(self) -> None:
        """US numbers (+1 prefix, 11 digits) must be accepted."""
        assert validate_phone("+12025551234") is None

    def test_valid_uk_number_ok(self) -> None:
        """UK numbers (+44 prefix) must be accepted."""
        assert validate_phone("+442079460000") is None

    def test_too_many_digits_returns_error(self) -> None:
        # 16 digits exceeds E.164 maximum of 15
        assert validate_phone("1234567890123456") is not None

    def test_leading_zero_after_10_digits_returns_error(self) -> None:
        """International numbers must not start with 0 (no country code 0)."""
        assert validate_phone("09001110777") is not None


class TestValidateBrand:
    """Tests for validate_brand."""

    def test_empty_returns_error(self) -> None:
        assert validate_brand("") is not None

    def test_single_char_returns_error(self) -> None:
        assert validate_brand("A") is not None

    def test_bot_command_rejected(self) -> None:
        assert validate_brand("/advertiser") is not None

    def test_min_length_ok(self) -> None:
        assert validate_brand("AB") is None

    def test_over_max_returns_error(self) -> None:
        assert validate_brand("A" * 201) is not None


class TestValidateCity:
    """Tests for validate_city."""

    def test_required_empty_returns_error(self) -> None:
        assert validate_city("", required=True) is not None

    def test_not_required_empty_ok(self) -> None:
        assert validate_city("", required=False) is None
        assert validate_city(None, required=False) is None

    def test_bot_command_rejected(self) -> None:
        assert validate_city("/profile", required=False) is not None
        assert validate_city("/creator", required=True) is not None

    def test_valid_ok(self) -> None:
        assert validate_city("Казань", required=True) is None

    def test_over_max_returns_error(self) -> None:
        assert validate_city("A" * 101, required=False) is not None


class TestValidateCompanyActivity:
    """Tests for validate_company_activity."""

    def test_empty_ok(self) -> None:
        assert validate_company_activity(None) is None
        assert validate_company_activity("") is None

    def test_bot_command_rejected(self) -> None:
        assert validate_company_activity("/advertiser") is not None

    def test_over_max_returns_error(self) -> None:
        assert validate_company_activity("A" * 501) is not None


class TestValidateSiteLink:
    """Tests for validate_site_link."""

    def test_empty_ok(self) -> None:
        assert validate_site_link(None) is None
        assert validate_site_link("") is None

    def test_invalid_url_returns_error(self) -> None:
        assert validate_site_link("not-url") is not None

    def test_valid_url_ok(self) -> None:
        assert validate_site_link("https://example.com") is None
        assert validate_site_link("сайт.рф") is None


class TestValidateNickname:
    """Tests for validate_nickname."""

    def test_empty_returns_error(self) -> None:
        assert validate_nickname("") is not None

    def test_bot_command_rejected(self) -> None:
        assert validate_nickname("/creator") is not None
        assert validate_nickname("/profile") is not None

    def test_single_char_returns_error(self) -> None:
        assert validate_nickname("A") is not None

    def test_min_length_ok(self) -> None:
        assert validate_nickname("Ab") is None

    def test_over_max_returns_error(self) -> None:
        assert validate_nickname("A" * 51) is not None

    def test_instagram_url_rejected(self) -> None:
        """Nickname must not be an Instagram URL."""
        assert validate_nickname("https://instagram.com/user") is not None
        assert validate_nickname("instagram.com/name") is not None


class TestValidateTopics:
    """Tests for validate_topics."""

    def test_empty_returns_error(self) -> None:
        assert validate_topics([]) is not None

    def test_valid_ok(self) -> None:
        assert validate_topics(["fitness"]) is None
        assert validate_topics(["a", "b", "c"]) is None

    def test_over_max_returns_error(self) -> None:
        assert validate_topics([f"t{i}" for i in range(11)]) is not None


class TestValidateAudienceGeo:
    """Tests for validate_audience_geo."""

    def test_empty_returns_error(self) -> None:
        assert validate_audience_geo("") is not None

    def test_bot_command_rejected(self) -> None:
        assert validate_audience_geo("/profile") is not None

    def test_valid_ok(self) -> None:
        assert validate_audience_geo("Москва") is None
        assert validate_audience_geo("Москва, Казань") is None

    def test_over_max_returns_error(self) -> None:
        assert validate_audience_geo("A" * 201) is not None


class TestValidatePrice:
    """Tests for validate_price."""

    def test_zero_returns_error(self) -> None:
        assert validate_price(0, 10000) is not None

    def test_negative_returns_error(self) -> None:
        assert validate_price(-1, 10000) is not None

    def test_over_max_returns_error(self) -> None:
        assert validate_price(10001, 10000) is not None

    def test_valid_ok(self) -> None:
        assert validate_price(1000, 10000) is None
        assert validate_price(10000, 10000) is None


class TestValidateUrl:
    """Tests for validate_url (used by product_link and site_link)."""

    def test_empty_returns_none(self) -> None:
        assert validate_url("") is None

    def test_invalid_scheme_returns_error(self) -> None:
        assert validate_url("ftp://example.com") is not None

    def test_no_scheme_valid_domain_ok(self) -> None:
        assert validate_url("example.com") is None
        assert validate_url("сайт.рф") is None
        assert validate_url("sub.example.com/path") is None

    def test_valid_ok(self) -> None:
        assert validate_url("https://example.com") is None
        assert validate_url("http://example.com") is None


class TestNormalizeUrl:
    """Tests for normalize_url."""

    def test_adds_https_when_no_scheme(self) -> None:
        assert normalize_url("example.com") == "https://example.com"
        assert normalize_url("сайт.рф") == "https://сайт.рф"

    def test_leaves_http_unchanged(self) -> None:
        assert normalize_url("http://example.com") == "http://example.com"

    def test_leaves_https_unchanged(self) -> None:
        assert normalize_url("https://example.com") == "https://example.com"

    def test_empty_returns_empty(self) -> None:
        assert normalize_url("") == ""


class TestValidateInstagramUrl:
    """Tests for validate_instagram_url (covers lines 246, 252)."""

    def test_empty_string_returns_error(self) -> None:
        """Empty string returns err_instagram_empty (line 246)."""
        err = validate_instagram_url("")
        assert err is not None
        err_lower = (err or "").lower()
        assert "empty" in err_lower or "instagram" in err_lower

    def test_url_without_instagram_domain_returns_format_error(self) -> None:
        """URL without instagram.com returns err_instagram_format (line 252)."""
        err = validate_instagram_url("https://facebook.com/user")
        assert err is not None
        err_lower = (err or "").lower()
        assert "format" in err_lower or "instagram" in err_lower

    def test_valid_instagram_url_returns_none(self) -> None:
        """Valid Instagram URL returns None."""
        assert validate_instagram_url("https://instagram.com/username") is None

    def test_invalid_instagram_url_pattern_returns_error(self) -> None:
        """URL with instagram.com but not regex returns err_instagram_example."""  # noqa: E501
        err = validate_instagram_url("https://instagram.com/")
        assert err is not None


class TestValidateUrlUncoveredBranches:
    """Tests for uncovered branches in validate_url (lines 276, 291, 300)."""

    def test_url_over_max_length_returns_error(self) -> None:
        """URL longer than max_len returns err_url_max (line 276)."""
        err = validate_url("a" * 600, max_len=500)
        assert err is not None
        assert "500" in (err or "") or "long" in (err or "").lower()

    def test_http_url_with_no_netloc_returns_error(self) -> None:
        """https:// with no netloc returns err_url_invalid (line 291)."""
        err = validate_url("https://")
        assert err is not None
        err_lower = (err or "").lower()
        assert "valid" in err_lower or "link" in err_lower

    def test_url_with_space_returns_error(self) -> None:
        """URL with space in path returns err_url_invalid (line 300)."""
        err = validate_url("example .com")
        assert err is not None
        err_lower = (err or "").lower()
        assert "valid" in err_lower or "link" in err_lower


class TestValidatePhoneInvalidBranch:
    """Tests for the invalid phone number branch."""

    def test_leading_zero_international_returns_error(self) -> None:
        """International numbers cannot start with 0 (no country code 0)."""
        err = validate_phone("01234567890")
        assert err is not None
        err_lower = (err or "").lower()
        assert (
            "valid" in err_lower
            or "код" in err_lower
            or "country" in err_lower
            or "+7" in err_lower
            or "+998" in err_lower
        )


class TestNormalizeUrlOtherScheme:
    """Tests for normalize_url with non-http/https scheme (line 223)."""

    def test_other_scheme_returned_unchanged(self) -> None:
        """URL with ftp:// scheme (not http/https) is returned as-is."""
        result = normalize_url("ftp://example.com")
        assert result == "ftp://example.com"


class TestNormalizeInstagramUrl:
    """Tests for normalize_instagram_url."""

    def test_strips_query_string(self) -> None:
        url = "https://www.instagram.com/kamil_bakhteev?igsh=bjh1MHRkczhxcTho&utm_source=qr"
        assert (
            normalize_instagram_url(url)
            == "https://instagram.com/kamil_bakhteev"
        )

    def test_strips_fragment(self) -> None:
        url = "https://instagram.com/user#section"
        assert normalize_instagram_url(url) == "https://instagram.com/user"

    def test_removes_www(self) -> None:
        assert (
            normalize_instagram_url("https://www.instagram.com/name")
            == "https://instagram.com/name"
        )

    def test_adds_https_when_no_scheme(self) -> None:
        assert (
            normalize_instagram_url("www.instagram.com/name")
            == "https://instagram.com/name"
        )
        assert (
            normalize_instagram_url("instagram.com/user")
            == "https://instagram.com/user"
        )

    def test_combined_normalization(self) -> None:
        url = "www.instagram.com/user?igsh=abc&utm_source=qr"
        assert normalize_instagram_url(url) == "https://instagram.com/user"

    def test_empty_returns_empty(self) -> None:
        assert normalize_instagram_url("") == ""
        assert normalize_instagram_url("   ") == ""

    def test_already_normalized_unchanged(self) -> None:
        url = "https://instagram.com/username"
        assert normalize_instagram_url(url) == url

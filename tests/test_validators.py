"""Tests for bot input validators."""

from ugc_bot.bot.validators import (
    normalize_url,
    validate_audience_geo,
    validate_barter_description,
    validate_brand,
    validate_city,
    validate_company_activity,
    validate_geography,
    validate_name,
    validate_nickname,
    validate_offer_text,
    validate_phone,
    validate_price,
    validate_product_link,
    validate_site_link,
    validate_topics,
    validate_url,
)


class TestValidateOfferText:
    """Tests for validate_offer_text."""

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


class TestValidateGeography:
    """Tests for validate_geography."""

    def test_empty_returns_error(self) -> None:
        assert validate_geography("") is not None

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

    def test_too_many_digits_returns_error(self) -> None:
        assert validate_phone("890011107771") is not None


class TestValidateBrand:
    """Tests for validate_brand."""

    def test_empty_returns_error(self) -> None:
        assert validate_brand("") is not None

    def test_single_char_returns_error(self) -> None:
        assert validate_brand("A") is not None

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

    def test_valid_ok(self) -> None:
        assert validate_city("Казань", required=True) is None

    def test_over_max_returns_error(self) -> None:
        assert validate_city("A" * 101, required=False) is not None


class TestValidateCompanyActivity:
    """Tests for validate_company_activity."""

    def test_empty_ok(self) -> None:
        assert validate_company_activity(None) is None
        assert validate_company_activity("") is None

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

    def test_single_char_returns_error(self) -> None:
        assert validate_nickname("A") is not None

    def test_min_length_ok(self) -> None:
        assert validate_nickname("Ab") is None

    def test_over_max_returns_error(self) -> None:
        assert validate_nickname("A" * 51) is not None


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

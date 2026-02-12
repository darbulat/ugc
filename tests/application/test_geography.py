"""Tests for geography parsing and blogger matching."""

from ugc_bot.application.geography import (
    REGION_TO_CITIES,
    GeographySpec,
    blogger_matches_geography,
    normalize_geo_token,
    parse_geography,
)


class TestNormalizeGeoToken:
    """Tests for normalize_geo_token."""

    def test_strip_lower(self) -> None:
        """Strip and lower case."""
        assert normalize_geo_token("  Казань  ") == "казань"
        assert normalize_geo_token("МОСКВА") == "москва"

    def test_yo_to_e(self) -> None:
        """Replace ё with е."""
        assert normalize_geo_token("Ёлка") == "елка"
        assert normalize_geo_token("берёза") == "береза"

    def test_empty(self) -> None:
        """Empty or whitespace returns empty string."""
        assert normalize_geo_token("") == ""
        assert normalize_geo_token("   ") == ""


class TestParseGeography:
    """Tests for parse_geography."""

    def test_none_or_empty_returns_none(self) -> None:
        """None or empty string returns None."""
        assert parse_geography(None) is None
        assert parse_geography("") is None
        assert parse_geography("   ") is None

    def test_world_phrases(self) -> None:
        """World phrases yield type world."""
        for phrase in ["весь мир", "МИР", "World", "вся планета"]:
            spec = parse_geography(phrase)
            assert spec is not None
            assert spec.type == "world"
            assert spec.values == []

    def test_country_phrases(self) -> None:
        """Country phrases yield type country."""
        for phrase in ["РФ", "Россия", "RUSSIA", "вся россия"]:
            spec = parse_geography(phrase)
            assert spec is not None
            assert spec.type == "country"
            assert spec.values == []

    def test_single_city(self) -> None:
        """Single city yields type cities with one value."""
        spec = parse_geography("Казань")
        assert spec is not None
        assert spec.type == "cities"
        assert spec.values == ["казань"]

    def test_multiple_cities_comma(self) -> None:
        """Multiple cities separated by comma."""
        spec = parse_geography("Казань, Москва")
        assert spec is not None
        assert spec.type == "cities"
        assert set(spec.values) == {"казань", "москва"}

    def test_multiple_cities_slash(self) -> None:
        """Multiple cities separated by slash."""
        spec = parse_geography("Москва / СПб")
        assert spec is not None
        assert spec.type == "cities"
        assert set(spec.values) == {"москва", "спб"}

    def test_multiple_cities_and(self) -> None:
        """Multiple cities with ' и '."""
        spec = parse_geography("Казань и Москва")
        assert spec is not None
        assert spec.type == "cities"
        assert set(spec.values) == {"казань", "москва"}

    def test_region_single_token(self) -> None:
        """Single token that is a known region yields type region."""
        spec = parse_geography("Татарстан")
        assert spec is not None
        assert spec.type == "region"
        assert spec.values == ["татарстан"]

    def test_multiple_regions_yield_cities_spec(self) -> None:
        """Multiple regions (or mix) yield type cities with all tokens."""
        spec = parse_geography("Татарстан, Бурятия")
        assert spec is not None
        assert spec.type == "cities"
        assert set(spec.values) == {"татарстан", "бурятия"}

    def test_region_case_insensitive(self) -> None:
        """Region name is case-insensitive."""
        spec = parse_geography("ТАТАРСТАН")
        assert spec is not None
        assert spec.type == "region"
        assert spec.values == ["татарстан"]

    def test_extra_whitespace_normalized(self) -> None:
        """Extra whitespace is collapsed."""
        spec = parse_geography("  Казань  ,   Москва  ")
        assert spec is not None
        assert spec.type == "cities"
        assert set(spec.values) == {"казань", "москва"}


class TestBloggerMatchesGeography:
    """Tests for blogger_matches_geography."""

    def test_world_always_true(self) -> None:
        """World spec matches any blogger."""
        spec = GeographySpec(type="world", values=[])
        assert blogger_matches_geography("Казань", spec) is True
        assert blogger_matches_geography("", spec) is True

    def test_country_always_true(self) -> None:
        """Country spec matches any blogger."""
        spec = GeographySpec(type="country", values=[])
        assert blogger_matches_geography("Москва", spec) is True

    def test_cities_exact_match(self) -> None:
        """Cities: exact match after normalization."""
        spec = GeographySpec(type="cities", values=["казань", "москва"])
        assert blogger_matches_geography("Казань", spec) is True
        assert blogger_matches_geography("МОСКВА", spec) is True
        assert blogger_matches_geography("СПб", spec) is False

    def test_cities_no_match_empty_city(self) -> None:
        """Cities: empty blogger city does not match."""
        spec = GeographySpec(type="cities", values=["казань"])
        assert blogger_matches_geography("", spec) is False

    def test_cities_multiple_blogger_cities_match_any(self) -> None:
        """Cities: blogger city lists several; match if one matches order."""
        spec = GeographySpec(type="cities", values=["казань", "москва"])
        assert blogger_matches_geography("Владивосток", spec) is False
        assert blogger_matches_geography("Владивосток, Москва", spec) is True
        assert blogger_matches_geography("Казань и СПб", spec) is True
        assert blogger_matches_geography("СПб / Питер", spec) is False

    def test_cities_list_may_include_regions(self) -> None:
        """Order geography can list regions; match if blogger city in region."""
        spec = GeographySpec(type="cities", values=["татарстан", "москва"])
        assert blogger_matches_geography("Казань", spec) is True
        assert blogger_matches_geography("Москва", spec) is True
        assert blogger_matches_geography("Набережные Челны", spec) is True
        assert blogger_matches_geography("Владивосток", spec) is False

    def test_region_match_by_city(self) -> None:
        """Region: match when blogger city is in region's city list."""
        spec = GeographySpec(type="region", values=["татарстан"])
        assert blogger_matches_geography("Казань", spec) is True
        assert blogger_matches_geography("Набережные Челны", spec) is True
        assert blogger_matches_geography("Москва", spec) is False

    def test_region_match_by_region_name(self) -> None:
        """Region: match when blogger city equals region name."""
        spec = GeographySpec(type="region", values=["татарстан"])
        assert blogger_matches_geography("Татарстан", spec) is True

    def test_region_multiple_blogger_cities_match_any(self) -> None:
        """Region: several cities in blogger city; match if any in region."""
        spec = GeographySpec(type="region", values=["татарстан"])
        assert blogger_matches_geography("Москва", spec) is False
        assert blogger_matches_geography("Москва, Казань", spec) is True

    def test_region_empty_values_no_match(self) -> None:
        """Region with empty values does not match."""
        spec = GeographySpec(type="region", values=[])
        assert blogger_matches_geography("Казань", spec) is False

    def test_region_unknown_region_no_match(self) -> None:
        """Region with value not in REGION_TO_CITIES does not match."""
        spec = GeographySpec(type="region", values=["unknown_region"])
        assert blogger_matches_geography("Казань", spec) is False


class TestRegionToCitiesCoverage:
    """Sanity check for REGION_TO_CITIES."""

    def test_region_to_cities_has_normalized_keys(self) -> None:
        """REGION_TO_CITIES keys and values are normalized (lower, no space)."""
        for key, cities in REGION_TO_CITIES.items():
            assert key == key.lower()
            assert key.strip() == key
            for city in cities:
                assert city == city.lower()
                assert city.strip() == city

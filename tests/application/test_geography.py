"""Tests for geography parsing and blogger matching.

No hardcoded region/city dictionaries; cities are arbitrary worldwide.
"""

from ugc_bot.application.geography import (
    GeographySpec,
    get_cities_list_for_miniapp,
    get_geometry_queries_from_spec,
    get_regions_for_city,
    normalize_geo_token,
    parse_geography,
    parse_miniapp_city_id,
    region_key_to_label,
    resolve_region_from_city_field,
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

    def test_any_non_world_yields_places(self) -> None:
        """Any input that is not world phrase yields type places (no dicts)."""
        spec = parse_geography("РФ")
        assert spec is not None
        assert spec.type == "places"
        assert spec.values == ["рф"]

        spec = parse_geography("Казань")
        assert spec is not None
        assert spec.type == "places"
        assert spec.values == ["казань"]

        spec = parse_geography("Berlin")
        assert spec is not None
        assert spec.type == "places"
        assert spec.values == ["berlin"]

        spec = parse_geography("USA")
        assert spec is not None
        assert spec.type == "places"
        assert spec.values == ["usa"]

        spec = parse_geography("Татарстан")
        assert spec is not None
        assert spec.type == "places"
        assert spec.values == ["татарстан"]

    def test_multiple_places_comma(self) -> None:
        """Multiple places separated by comma."""
        spec = parse_geography("Казань, Москва")
        assert spec is not None
        assert spec.type == "places"
        assert set(spec.values) == {"казань", "москва"}

    def test_multiple_places_slash(self) -> None:
        """Multiple places separated by slash."""
        spec = parse_geography("Москва / СПб")
        assert spec is not None
        assert spec.type == "places"
        assert set(spec.values) == {"москва", "спб"}

    def test_multiple_places_and(self) -> None:
        """Multiple places with ' и '."""
        spec = parse_geography("Казань и Москва")
        assert spec is not None
        assert spec.type == "places"
        assert set(spec.values) == {"казань", "москва"}

    def test_extra_whitespace_normalized(self) -> None:
        """Extra whitespace is collapsed."""
        spec = parse_geography("  Казань  ,   Москва  ")
        assert spec is not None
        assert spec.type == "places"
        assert set(spec.values) == {"казань", "москва"}


class TestGetGeometryQueriesFromSpec:
    """Tests for get_geometry_queries_from_spec (world/places only)."""

    def test_world_returns_empty(self) -> None:
        """World spec returns no queries."""
        assert (
            get_geometry_queries_from_spec(
                GeographySpec(type="world", values=[])
            )
            == []
        )

    def test_places_returns_global_queries(self) -> None:
        """Places spec returns (query, None, '') for each value."""
        assert get_geometry_queries_from_spec(
            GeographySpec(type="places", values=["berlin", "paris"])
        ) == [("berlin", None, ""), ("paris", None, "")]

    def test_places_single_value(self) -> None:
        """Single place returns one tuple."""
        assert get_geometry_queries_from_spec(
            GeographySpec(type="places", values=["казань"])
        ) == [("казань", None, "")]


class TestGetCitiesListForMiniapp:
    """Tests for get_cities_list_for_miniapp (no hardcoded list)."""

    def test_returns_empty_list(self) -> None:
        """Returns empty list; cities are arbitrary worldwide."""
        cities = get_cities_list_for_miniapp()
        assert cities == []


class TestRegionKeyToLabel:
    """Tests for region_key_to_label."""

    def test_returns_title_case(self) -> None:
        """Region key is converted to display label (title case)."""
        assert region_key_to_label("москва") == "Москва"
        assert region_key_to_label("красноярский край") == "Красноярский Край"
        assert (
            region_key_to_label("республика татарстан")
            == "Республика Татарстан"
        )

    def test_hyphenated_preserved(self) -> None:
        """Hyphenated parts get capitalised."""
        assert "Петербург" in region_key_to_label("санкт-петербург")

    def test_empty_returns_empty(self) -> None:
        """Empty string returns empty."""
        assert region_key_to_label("") == ""


class TestGetRegionsForCity:
    """Tests for get_regions_for_city (no hardcoded dictionary)."""

    def test_always_returns_empty(self) -> None:
        """Always returns empty list; region resolved by geocoder."""
        assert get_regions_for_city("Москва") == []
        assert get_regions_for_city("Berlin") == []
        assert get_regions_for_city("НесуществующийГород") == []


class TestResolveRegionFromCityField:
    """Tests for resolve_region_from_city_field (no hardcoded dictionary)."""

    def test_any_city_returns_unrecognized(self) -> None:
        """Any city string returns (None, 'unrecognized')."""
        region_key, status = resolve_region_from_city_field("Москва")
        assert status == "unrecognized"
        assert region_key is None

        region_key, status = resolve_region_from_city_field("Казань, Татарстан")
        assert status == "unrecognized"
        assert region_key is None

    def test_empty_or_whitespace_returns_unrecognized(self) -> None:
        """Empty or whitespace returns (None, 'unrecognized')."""
        assert resolve_region_from_city_field("") == (None, "unrecognized")
        assert resolve_region_from_city_field("   ") == (None, "unrecognized")


class TestParseMiniappCityId:
    """Tests for parse_miniapp_city_id."""

    def test_plain_city_returns_city_and_none_region(self) -> None:
        """Plain city id returns (city, None)."""
        assert parse_miniapp_city_id("казань") == ("казань", None)
        assert parse_miniapp_city_id("  москва  ") == ("москва", None)

    def test_region_city_format_returns_both(self) -> None:
        """region:city format returns (city, region)."""
        assert parse_miniapp_city_id("республика татарстан:казань") == (
            "казань",
            "республика татарстан",
        )

    def test_empty_returns_empty_tuple(self) -> None:
        """Empty or whitespace returns ('', None)."""
        assert parse_miniapp_city_id("") == ("", None)
        assert parse_miniapp_city_id("   ") == ("", None)


class TestParseGeographyEdgeCases:
    """Additional edge cases for parse_geography (lines 59, uncovered)."""

    def test_separator_only_returns_none(self) -> None:
        """Text that splits into empty tokens returns None (line 59)."""
        result = parse_geography(",,,")
        assert result is None

    def test_only_commas_returns_none(self) -> None:
        """Text that is only comma/slash separators returns None (line 59)."""
        result = parse_geography(",,, / ,")
        assert result is None


class TestGetGeometryQueriesEdgeCases:
    """Tests for get_geometry_queries_from_spec edge case (line 118)."""

    def test_places_spec_with_empty_values_returns_empty_list(self) -> None:
        """GeographySpec type='places' and empty values returns []."""
        spec = GeographySpec(type="places", values=[])
        result = get_geometry_queries_from_spec(spec)
        assert result == []

"""Tests for geography parsing and blogger matching."""

from ugc_bot.application.geography import (
    REGION_TO_CITIES,
    GeographySpec,
    get_canonical_cities_set,
    get_cities_list_for_miniapp,
    get_geometry_queries_from_spec,
    get_regions_for_city,
    is_canonical_city,
    is_canonical_city_only,
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
    """Tests for get_cities_list_for_miniapp."""

    def test_returns_list_of_dicts_with_id_and_label(self) -> None:
        """List items have id and label keys."""
        cities = get_cities_list_for_miniapp()
        assert len(cities) > 0
        for item in cities:
            assert "id" in item
            assert "label" in item
            assert isinstance(item["id"], str)
            assert isinstance(item["label"], str)

    def test_contains_moscow_and_spb(self) -> None:
        """List contains Moscow, SPB, Kazan; id format region:city."""
        cities = get_cities_list_for_miniapp()
        ids = {c["id"] for c in cities}
        assert "москва:москва" in ids
        assert "республика татарстан:казань" in ids
        assert any("санкт-петербург" in i for i in ids)

    def test_label_includes_region(self) -> None:
        """Each item label is 'City (Region)'."""
        cities = get_cities_list_for_miniapp()
        for item in cities:
            assert " (" in item["label"]
            assert item["label"].endswith(")")

    def test_sorted_by_label(self) -> None:
        """List is sorted by label."""
        cities = get_cities_list_for_miniapp()
        labels = [c["label"] for c in cities]
        assert labels == sorted(labels)

    def test_no_duplicate_ids(self) -> None:
        """No duplicate ids (each region:city pair once)."""
        cities = get_cities_list_for_miniapp()
        ids = [c["id"] for c in cities]
        assert len(ids) == len(set(ids))


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
    """Tests for get_regions_for_city."""

    def test_city_in_one_region(self) -> None:
        """City in one region returns single-element list."""
        regions = get_regions_for_city("Москва")
        assert regions == ["москва"]

    def test_city_in_multiple_regions(self) -> None:
        """City in multiple regions returns all region keys."""
        regions = get_regions_for_city("Железногорск")
        assert len(regions) >= 2
        assert "красноярский край" in regions
        assert "курская область" in regions

    def test_unknown_city_returns_empty(self) -> None:
        """Unknown city returns empty list."""
        assert get_regions_for_city("НесуществующийГород") == []


class TestResolveRegionFromCityField:
    """Tests for resolve_region_from_city_field."""

    def test_plain_city_one_region_returns_ok(self) -> None:
        """Single city in one region returns (region, 'ok')."""
        region_key, status = resolve_region_from_city_field("Москва")
        assert status == "ok"
        assert region_key == "москва"

    def test_city_with_region_token_returns_ok(self) -> None:
        """City and matching region in field use explicit region."""
        region_key, status = resolve_region_from_city_field("Казань, Татарстан")
        assert status == "ok"
        assert region_key == "республика татарстан"

    def test_region_before_city_returns_ok(self) -> None:
        """Region then city in field uses that region."""
        region_key, status = resolve_region_from_city_field(
            "Московская область, Балашиха"
        )
        assert status == "ok"
        assert region_key == "московская область"

    def test_city_in_multiple_regions_returns_multiple(self) -> None:
        """City in several regions returns (None, 'multiple')."""
        region_key, status = resolve_region_from_city_field("Железногорск")
        assert status == "multiple"
        assert region_key is None

    def test_unrecognized_city_returns_unrecognized(self) -> None:
        """Unknown city returns (None, 'unrecognized')."""
        region_key, status = resolve_region_from_city_field(
            "НесуществующийГород"
        )
        assert status == "unrecognized"
        assert region_key is None

    def test_empty_or_whitespace_returns_unrecognized(self) -> None:
        """Empty or whitespace returns (None, 'unrecognized')."""
        assert resolve_region_from_city_field("") == (None, "unrecognized")
        assert resolve_region_from_city_field("   ") == (None, "unrecognized")

    def test_only_region_token_returns_unrecognized(self) -> None:
        """Only region name (no city) is treated as unrecognized city."""
        region_key, status = resolve_region_from_city_field("Татарстан")
        assert status == "unrecognized"
        assert region_key is None


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


class TestIsCanonicalCity:
    """Tests for is_canonical_city."""

    def test_known_cities_true(self) -> None:
        """Known cities return True."""
        assert is_canonical_city("москва") is True
        assert is_canonical_city("Москва") is True
        assert is_canonical_city("казань") is True
        assert is_canonical_city("санкт-петербург") is True

    def test_unknown_returns_false(self) -> None:
        """Unknown or typo returns False."""
        assert is_canonical_city("питер") is False
        assert is_canonical_city("unknown_city") is False
        assert is_canonical_city("") is False


class TestIsCanonicalCityOnly:
    """Tests for is_canonical_city_only (city names only, not regions)."""

    def test_city_returns_true(self) -> None:
        """Actual city names return True."""
        assert is_canonical_city_only("москва") is True
        assert is_canonical_city_only("якутск") is True
        assert is_canonical_city_only("казань") is True

    def test_region_returns_false(self) -> None:
        """Region names must not pass as city."""
        assert is_canonical_city_only("республика якутия") is False
        assert is_canonical_city_only("республика татарстан") is False
        assert is_canonical_city_only("саха") is False

    def test_unknown_returns_false(self) -> None:
        """Unknown value returns False."""
        assert is_canonical_city_only("питер") is False
        assert is_canonical_city_only("") is False


class TestGetCanonicalCitiesSet:
    """Tests for get_canonical_cities_set."""

    def test_contains_expected_ids(self) -> None:
        """Set contains region keys and city values from REGION_TO_CITIES."""
        s = get_canonical_cities_set()
        assert "москва" in s
        assert "санкт-петербург" in s
        assert "республика татарстан" in s
        assert "казань" in s

    def test_is_frozenset(self) -> None:
        """Returns frozenset."""
        assert isinstance(get_canonical_cities_set(), frozenset)


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

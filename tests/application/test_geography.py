"""Tests for geography parsing and blogger matching."""

from ugc_bot.application.geography import (
    REGION_TO_CITIES,
    GeographySpec,
    blogger_matches_geography,
    get_canonical_cities_set,
    get_cities_list_for_miniapp,
    get_regions_for_city,
    is_canonical_city,
    is_canonical_city_only,
    normalize_geo_token,
    parse_geography,
    parse_miniapp_city_id,
    region_key_to_label,
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

    def test_region_alias_sakha_resolves_to_yakutia(self) -> None:
        """Alias 'Саха' resolves to canonical region 'якутия'."""
        spec = parse_geography("Саха")
        assert spec is not None
        assert spec.type == "region"
        assert spec.values == ["якутия"]

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
        assert "татарстан:казань" in ids
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
        assert region_key_to_label("татарстан") == "Татарстан"

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


class TestParseMiniappCityId:
    """Tests for parse_miniapp_city_id."""

    def test_plain_city_returns_city_and_none_region(self) -> None:
        """Plain city id returns (city, None)."""
        assert parse_miniapp_city_id("казань") == ("казань", None)
        assert parse_miniapp_city_id("  москва  ") == ("москва", None)

    def test_region_city_format_returns_both(self) -> None:
        """region:city format returns (city, region)."""
        assert parse_miniapp_city_id("татарстан:казань") == (
            "казань",
            "татарстан",
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
        assert is_canonical_city_only("якутия") is False
        assert is_canonical_city_only("татарстан") is False
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
        assert "татарстан" in s
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

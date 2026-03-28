#!/usr/bin/env python3
"""Backfill location_geometry for blogger_profiles from city field.

Parses city string by comma, slash, " и ", newline; for each token (after
normalization and dedup) geocodes via configured geocoder using profile.region
and profile.country; builds MULTIPOINT from (lat, lon) and updates
blogger_profiles.location_geometry.

(City, country, region) -> coordinates are cached in RAM for the script run
to avoid repeated requests.
"""

import argparse
import asyncio
import logging
import sys
from dataclasses import replace

from sqlalchemy import select

from ugc_bot.application.geography import (
    GEO_TOKEN_SPLIT_RE,
    normalize_geo_token,
)
from ugc_bot.application.ports import GeocoderPort
from ugc_bot.application.services.geocoder import wkt_multipoint_from_coords
from ugc_bot.config import load_config
from ugc_bot.container import repository_factory
from ugc_bot.container.service_factory import build_geocoder
from ugc_bot.infrastructure.db.models import BloggerProfileModel
from ugc_bot.infrastructure.db.session import create_session_factory

logger = logging.getLogger(__name__)

# For Nominatim, Crimea region is queried as Ukraine
REGION_CRIMEA_NORMALIZED = "республика крым"


def _parse_city_tokens(city_raw: str | None) -> list[str]:
    """Split city into normalized unique tokens (for geocoding)."""
    if not city_raw or not city_raw.strip():
        return []
    tokens = [
        normalize_geo_token(p)
        for p in GEO_TOKEN_SPLIT_RE.split(city_raw)
        if normalize_geo_token(p)
    ]
    return list(dict.fromkeys(tokens))


def _cache_key(token: str, country: str | None, region: str | None) -> str:
    """Cache key for (city token, country, region) to avoid mixing results."""
    return "|".join(
        (
            token.strip(),
            (country or "").strip().lower(),
            (region or "").strip().lower(),
        )
    )


async def _geocode_city_tokens(
    geocoder: GeocoderPort,
    tokens: list[str],
    country: str | None,
    region: str | None,
    cache: dict[str, tuple[float, float] | None],
    *,
    provider: str,
    delay_seconds: float,
) -> tuple[list[tuple[float, float]], str | None, str | None]:
    """Geocode each token; accept only populated places/regions.

    Returns (coords, region_from_geocoder, country_from_geocoder) from
    the first accepted result (for saving when profile.region/country empty).
    No default country: if profile country is empty, query is sent without it.
    """
    coords: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    region_from_geocoder: str | None = None
    country_from_geocoder: str | None = None
    country_for_query: str | None = (country or "").strip() or None
    region_for_query = (region or "").strip() or None
    region_norm = (region or "").strip().lower()
    if provider == "nominatim" and region_norm == REGION_CRIMEA_NORMALIZED:
        country_for_query = "Ukraine"
    for token in tokens:
        key = _cache_key(token, country or "", region)
        if key in cache:
            coord = cache[key]
            detail_region = None
            detail_country = None
        else:
            details = await geocoder.geocode_with_details(
                token.strip(),
                region=region_for_query,
                country=country_for_query,
            )
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
            if details is None:
                cache[key] = None
                coord = None
                detail_region = None
                detail_country = None
            else:
                (
                    lat,
                    lon,
                    place_class,
                    place_type,
                    detail_region,
                    detail_country,
                ) = details
                if geocoder.accepts_as_place_or_region(place_class, place_type):
                    cache[key] = (lat, lon)
                    coord = (lat, lon)
                else:
                    logger.warning(
                        "Skipping non-place result for %r: class=%r type=%r (not saved to DB)",
                        token.strip(),
                        place_class or "(empty)",
                        place_type or "(empty)",
                    )
                    cache[key] = None
                    coord = None
                    detail_region = None
                    detail_country = None
        if coord is not None and coord not in seen:
            seen.add(coord)
            coords.append(coord)
            if region_from_geocoder is None and detail_region:
                region_from_geocoder = detail_region
            if country_from_geocoder is None and detail_country:
                country_from_geocoder = detail_country
    return (coords, region_from_geocoder, country_from_geocoder)


async def run(
    dry_run: bool,
    only_empty_geometry: bool,
) -> int:
    """Backfill location_geometry for creators from city."""
    config = load_config()
    if not config.db.database_url:
        print("DATABASE_URL is required.", file=sys.stderr)
        return 1

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )

    session_factory = create_session_factory(
        config.db.database_url,
        pool_size=config.db.pool_size,
        max_overflow=config.db.max_overflow,
        pool_timeout=config.db.pool_timeout,
    )
    repos = repository_factory.build_repos(session_factory)
    blogger_repo = repos["blogger_repo"]
    geocoder = build_geocoder(config)
    delay_seconds = (
        config.geocoder.nominatim_delay_seconds
        if config.geocoder.provider == "nominatim"
        else 0.0
    )

    async with session_factory() as session:
        stmt = select(
            BloggerProfileModel.user_id,
            BloggerProfileModel.city,
            BloggerProfileModel.country,
            BloggerProfileModel.region,
        ).where(
            BloggerProfileModel.city.isnot(None),
            BloggerProfileModel.city != "",
        )
        if only_empty_geometry:
            stmt = stmt.where(BloggerProfileModel.location_geometry.is_(None))
        result = await session.execute(stmt)
        rows = list(result.all())

    if not rows:
        print("No blogger profiles to process.")
        return 0

    updated_count = 0
    skipped_no_coords = 0
    errors = 0
    geo_cache: dict[str, tuple[float, float] | None] = {}

    for user_id, city, country, region in rows:
        city_str = (city or "").strip()
        country_for_profile = (country or "").strip() or None
        region_str = (region or "").strip() or None
        tokens = _parse_city_tokens(city_str)
        if not tokens:
            logger.debug(
                "Empty tokens for user_id=%s city=%r", user_id, city_str
            )
            continue

        (
            coords,
            region_from_geocoder,
            country_from_geocoder,
        ) = await _geocode_city_tokens(
            geocoder,
            tokens,
            country_for_profile,
            region_str,
            geo_cache,
            provider=config.geocoder.provider,
            delay_seconds=delay_seconds,
        )
        if not coords:
            skipped_no_coords += 1
            logger.warning(
                "No coords for user_id=%s city=%r tokens=%s",
                user_id,
                city_str,
                tokens,
            )
            continue

        wkt = wkt_multipoint_from_coords(coords)
        if not wkt:
            skipped_no_coords += 1
            continue

        if dry_run:
            updated_count += 1
            logger.info(
                "Would set location_geometry for user_id=%s city=%r -> %d point(s)",
                user_id,
                city_str,
                len(coords),
            )
            continue

        async with session_factory() as session:
            try:
                profile = await blogger_repo.get_by_user_id(
                    user_id, session=session
                )
                if profile is None:
                    logger.warning("Profile not found for user_id=%s", user_id)
                    errors += 1
                    continue
                update_kw: dict = {"location_geometry": wkt}
                if not (profile.region or "").strip() and region_from_geocoder:
                    update_kw["region"] = region_from_geocoder
                if (
                    not (profile.country or "").strip()
                    and country_from_geocoder
                ):
                    update_kw["country"] = country_from_geocoder
                updated = replace(profile, **update_kw)
                await blogger_repo.save(updated, session=session)
                await session.commit()
                updated_count += 1
                logger.info(
                    "Set location_geometry for user_id=%s city=%r -> %d point(s)",
                    user_id,
                    city_str,
                    len(coords),
                )
            except Exception as e:
                logger.exception(
                    "Failed to update user_id=%s: %s",
                    user_id,
                    e,
                )
                errors += 1

    print(
        f"Processed {len(rows)}: updated={updated_count}, "
        f"skipped_no_coords={skipped_no_coords}, errors={errors} "
        f"(dry_run={dry_run}, only_empty_geometry={only_empty_geometry})"
    )
    if dry_run and updated_count > 0:
        print("Run without --dry-run to apply changes.")
    return 0 if errors == 0 else 1


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Fill location_geometry for blogger_profiles from city. "
            "Multiple cities in city (comma/slash/и) become MULTIPOINT."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report what would be updated.",
    )
    parser.add_argument(
        "--only-empty-geometry",
        action="store_true",
        help="Only update profiles where location_geometry is NULL or empty.",
    )
    args = parser.parse_args()
    return asyncio.run(
        run(dry_run=args.dry_run, only_empty_geometry=args.only_empty_geometry)
    )


if __name__ == "__main__":
    sys.exit(main())

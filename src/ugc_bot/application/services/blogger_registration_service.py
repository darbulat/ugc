"""Service for blogger registration."""

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import UUID

from ugc_bot.application.errors import (
    BloggerRegistrationError,
    UserNotFoundError,
)
from ugc_bot.application.ports import (
    BloggerProfileRepository,
    GeocoderPort,
    TransactionManager,
    UserRepository,
)
from ugc_bot.application.services.geocoder import wkt_multipoint_from_lat_lon
from ugc_bot.application.services.referral_service import ReferralService
from ugc_bot.domain.entities import BloggerProfile, User
from ugc_bot.domain.enums import AudienceGender, BloggerGender, WorkFormat
from ugc_bot.infrastructure.db.session import with_optional_tx

# OSM/Nominatim place types accepted as populated places (city, village, etc.)
NOMINATIM_PLACE_TYPES: frozenset[str] = frozenset(
    {
        "city",
        "town",
        "village",
        "hamlet",
        "locality",
        "suburb",
        "neighbourhood",
        "quarter",
        "isolated_dwelling",
    }
)


def _validate_blogger_input(
    instagram_url: str,
    city: str,
    audience_geo: str,
    audience_age_min: int,
    audience_age_max: int,
    price: float,
) -> tuple[str, str, str]:
    """Validate blogger input. Returns (instagram_url, city, geo)."""
    instagram_url_clean = instagram_url.strip()
    if not instagram_url_clean:
        raise BloggerRegistrationError("Instagram URL is required.")

    city_clean = city.strip()
    if not city_clean:
        raise BloggerRegistrationError("City is required.")

    audience_geo_clean = audience_geo.strip()
    if not audience_geo_clean:
        raise BloggerRegistrationError("Audience geo is required.")

    if audience_age_min <= 0 or audience_age_max <= 0:
        raise BloggerRegistrationError("Audience age must be positive.")
    if audience_age_max < audience_age_min:
        raise BloggerRegistrationError("Age max must be >= age min.")

    if price <= 0:
        raise BloggerRegistrationError("Price must be positive.")

    return instagram_url_clean, city_clean, audience_geo_clean


async def _resolve_location_and_nominatim_details(
    geocoder: Optional[GeocoderPort],
    city: str,
    region: Optional[str] = None,
    country: Optional[str] = None,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (wkt_geometry, region_from_nominatim, country_from_nominatim).

    Uses geocode_with_details; returns (None, None, None) when unavailable
    or when the result is not a populated place (city, town, village, etc.).
    """
    if geocoder is None or not city.strip():
        return (None, None, None)
    details = await geocoder.geocode_with_details(
        city.strip(), region=region, country=country
    )
    if details is None:
        return (None, None, None)
    lat, lon, osm_class, osm_type, region_nom, country_nom = details
    osm_class = (osm_class or "").strip().lower()
    osm_type = (osm_type or "").strip().lower()
    if osm_class != "place" or osm_type not in NOMINATIM_PLACE_TYPES:
        return (None, None, None)
    wkt = wkt_multipoint_from_lat_lon(lat, lon)
    return (wkt, region_nom, country_nom)


@dataclass(slots=True)
class UpdateBloggerProfileResult:
    """Result of update_blogger_profile.

    profile is None if not found or not saved.
    """

    profile: Optional[BloggerProfile]
    location_geometry_resolved: bool = True


@dataclass(slots=True)
class BloggerRegistrationService:
    """Register blogger profiles with validation."""

    user_repo: UserRepository
    blogger_repo: BloggerProfileRepository
    referral_service: Optional[ReferralService] = None
    metrics_collector: Optional[Any] = None
    transaction_manager: TransactionManager | None = None
    geocoder: Optional[GeocoderPort] = None

    async def get_profile_by_instagram_url(
        self, instagram_url: str
    ) -> BloggerProfile | None:
        """Fetch blogger profile by Instagram URL in a transaction."""

        async def _run(session: object | None):
            return await self.blogger_repo.get_by_instagram_url(
                instagram_url, session=session
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def resolve_city_from_location(
        self, lat: float, lon: float
    ) -> Optional[tuple[str, Optional[str], Optional[str]]]:
        """Reverse geocode (lat, lon) to (city, region, country)."""
        if self.geocoder is None:
            return None
        return await self.geocoder.reverse_geocode(lat, lon)

    async def register_blogger(
        self,
        user_id: UUID,
        instagram_url: str,
        city: str,
        topics: dict[str, Any],
        audience_gender: AudienceGender,
        audience_age_min: int,
        audience_age_max: int,
        audience_geo: str,
        price: float,
        barter: bool,
        work_format: WorkFormat,
        blogger_gender: BloggerGender,
        display_name: Optional[str] = None,
        telegram_username: Optional[str] = None,
        birth_date: Optional[date] = None,
        region: Optional[str] = None,
    ) -> BloggerProfile:
        """Create a blogger profile after validating input.

        Updates user.role_chosen_at and optionally user.username (display_name)
        and user.telegram (telegram_username) in the same transaction as
        profile creation.
        """

        async def _run(session: object | None) -> BloggerProfile:
            user = await self.user_repo.get_by_id(user_id, session=session)
            if user is None:
                raise UserNotFoundError(
                    "User not found for blogger registration."
                )

            instagram_url_clean, city_clean, audience_geo_clean = (
                _validate_blogger_input(
                    instagram_url,
                    city,
                    audience_geo,
                    audience_age_min,
                    audience_age_max,
                    price,
                )
            )

            existing_profile = await self.blogger_repo.get_by_instagram_url(
                instagram_url_clean, session=session
            )
            if existing_profile is not None:
                raise BloggerRegistrationError(
                    "Этот Instagram аккаунт уже зарегистрирован. "
                    "Пожалуйста, используйте другой аккаунт."
                )

            (
                location_geometry,
                region_nom,
                country_nom,
            ) = await _resolve_location_and_nominatim_details(
                self.geocoder, city_clean, region=region, country=None
            )
            profile_region = region_nom if region_nom is not None else region
            profile_country = country_nom if country_nom is not None else ""
            profile = BloggerProfile(
                user_id=user.user_id,
                instagram_url=instagram_url_clean,
                confirmed=False,
                city=city_clean,
                topics=topics,
                audience_gender=audience_gender,
                audience_age_min=audience_age_min,
                audience_age_max=audience_age_max,
                audience_geo=audience_geo_clean,
                price=price,
                barter=barter,
                work_format=work_format,
                updated_at=datetime.now(timezone.utc),
                blogger_gender=blogger_gender,
                birth_date=birth_date,
                region=profile_region,
                location_geometry=location_geometry,
                country=profile_country,
            )
            await self.blogger_repo.save(profile, session=session)

            now = datetime.now(timezone.utc)
            role_chosen_at = (
                now if user.role_chosen_at is None else user.role_chosen_at
            )
            username = (
                display_name.strip()
                if display_name and display_name.strip()
                else user.username
            )
            telegram = (
                telegram_username
                if telegram_username is not None
                else user.telegram
            )
            updated_user = replace(
                user,
                username=username,
                role_chosen_at=role_chosen_at,
                telegram=telegram,
                agreement_confirmed_at=now,
            )
            await self.user_repo.save(updated_user, session=session)

            if self.referral_service:
                await self.referral_service.create_binding_from_pending(
                    creator_user_id=user_id,
                    session=session,
                )

            if self.metrics_collector:
                self.metrics_collector.record_blogger_registration(
                    str(user.user_id)
                )

            return profile

        return await with_optional_tx(self.transaction_manager, _run)

    async def save_blogger_before_agreement(
        self,
        user_id: UUID,
        instagram_url: str,
        city: str,
        topics: dict[str, Any],
        audience_gender: AudienceGender,
        audience_age_min: int,
        audience_age_max: int,
        audience_geo: str,
        price: float,
        barter: bool,
        work_format: WorkFormat,
        blogger_gender: BloggerGender,
        display_name: Optional[str] = None,
        telegram_username: Optional[str] = None,
        birth_date: Optional[date] = None,
        region: Optional[str] = None,
        location_geometry: Optional[str] = None,
        country: Optional[str] = None,
    ) -> BloggerProfile:
        """Save blogger profile and update user before consent confirmation.

        Does not set agreement_confirmed_at and does not run referral/metrics.
        When location_geometry is provided (e.g. from shared geolocation), it is
        used as-is and country is taken from the country argument.
        """

        async def _run(session: object | None) -> BloggerProfile:
            user = await self.user_repo.get_by_id(user_id, session=session)
            if user is None:
                raise UserNotFoundError(
                    "User not found for blogger registration."
                )

            instagram_url_clean, city_clean, audience_geo_clean = (
                _validate_blogger_input(
                    instagram_url,
                    city,
                    audience_geo,
                    audience_age_min,
                    audience_age_max,
                    price,
                )
            )

            existing_profile = await self.blogger_repo.get_by_instagram_url(
                instagram_url_clean, session=session
            )
            if existing_profile is not None:
                raise BloggerRegistrationError(
                    "Этот Instagram аккаунт уже зарегистрирован. "
                    "Пожалуйста, используйте другой аккаунт."
                )

            geom_wkt: Optional[str]
            if location_geometry is not None:
                geom_wkt = location_geometry
                profile_region = region
                profile_country = (country or "").strip()
            else:
                (
                    geom_wkt,
                    region_nom,
                    country_nom,
                ) = await _resolve_location_and_nominatim_details(
                    self.geocoder, city_clean, region=region, country=None
                )
                profile_region = (
                    region_nom if region_nom is not None else region
                )
                profile_country = country_nom if country_nom is not None else ""
            profile = BloggerProfile(
                user_id=user.user_id,
                instagram_url=instagram_url_clean,
                confirmed=False,
                city=city_clean,
                topics=topics,
                audience_gender=audience_gender,
                audience_age_min=audience_age_min,
                audience_age_max=audience_age_max,
                audience_geo=audience_geo_clean,
                price=price,
                barter=barter,
                work_format=work_format,
                updated_at=datetime.now(timezone.utc),
                blogger_gender=blogger_gender,
                birth_date=birth_date,
                region=profile_region,
                location_geometry=geom_wkt,
                country=profile_country,
            )
            await self.blogger_repo.save(profile, session=session)

            now = datetime.now(timezone.utc)
            role_chosen_at = (
                now if user.role_chosen_at is None else user.role_chosen_at
            )
            username = (
                display_name.strip()
                if display_name and display_name.strip()
                else user.username
            )
            telegram = (
                telegram_username
                if telegram_username is not None
                else user.telegram
            )
            updated_user = replace(
                user,
                username=username,
                role_chosen_at=role_chosen_at,
                telegram=telegram,
                agreement_confirmed_at=None,
            )
            await self.user_repo.save(updated_user, session=session)
            return profile

        return await with_optional_tx(self.transaction_manager, _run)

    async def confirm_blogger_agreement(
        self,
        user_id: UUID,
        telegram_username: Optional[str] = None,
    ) -> None:
        """Set agreement_confirmed_at and run referral/metrics for blogger."""

        async def _run(session: object | None) -> None:
            user = await self.user_repo.get_by_id(user_id, session=session)
            if user is None:
                raise UserNotFoundError(
                    "User not found for agreement confirmation."
                )
            now = datetime.now(timezone.utc)
            telegram = (
                telegram_username
                if telegram_username is not None
                else user.telegram
            )
            updated_user = User(
                user_id=user.user_id,
                external_id=user.external_id,
                messenger_type=user.messenger_type,
                username=user.username,
                status=user.status,
                issue_count=user.issue_count,
                created_at=user.created_at,
                role_chosen_at=user.role_chosen_at,
                last_role_reminder_at=user.last_role_reminder_at,
                telegram=telegram,
                admin=user.admin,
                referral_code=user.referral_code,
                referral_payout_rate=getattr(
                    user, "referral_payout_rate", None
                ),
                agreement_confirmed_at=now,
            )
            await self.user_repo.save(updated_user, session=session)

            if self.referral_service:
                await self.referral_service.create_binding_from_pending(
                    creator_user_id=user_id,
                    session=session,
                )

            if self.metrics_collector:
                self.metrics_collector.record_blogger_registration(
                    str(user.user_id)
                )

        await with_optional_tx(self.transaction_manager, _run)

    async def update_blogger_profile(
        self,
        user_id: UUID,
        *,
        instagram_url: Optional[str] = None,
        city: Optional[str] = None,
        region: Optional[str] = None,
        location_geometry: Optional[str] = None,
        topics: Optional[dict[str, Any]] = None,
        audience_gender: Optional[AudienceGender] = None,
        audience_age_min: Optional[int] = None,
        audience_age_max: Optional[int] = None,
        audience_geo: Optional[str] = None,
        price: Optional[float] = None,
        barter: Optional[bool] = None,
        work_format: Optional[WorkFormat] = None,
        blogger_gender: Optional[BloggerGender] = None,
        birth_date: Optional[date] = None,
        country: Optional[str] = None,
    ) -> UpdateBloggerProfileResult:
        """Update blogger profile. When city is set without location_geometry,
        if geocoding does not resolve to a populated place, profile is not
        saved and location_geometry_resolved is False.
        """

        async def _run(
            session: object | None,
        ) -> UpdateBloggerProfileResult:
            profile = await self.blogger_repo.get_by_user_id(
                user_id, session=session
            )
            if profile is None:
                return UpdateBloggerProfileResult(profile=None)

            new_instagram_url = (
                instagram_url.strip()
                if instagram_url is not None
                else profile.instagram_url
            )
            instagram_changed = (
                instagram_url is not None
                and new_instagram_url != profile.instagram_url
            )
            new_city = city.strip() if city is not None else profile.city
            new_region = region if region is not None else profile.region
            if country is not None:
                new_country = (country or "").strip()
            else:
                new_country = profile.country or ""
            new_geometry = location_geometry
            if new_geometry is None and (
                city is not None or region is not None
            ):
                (
                    geom_wkt,
                    region_nom,
                    country_nom,
                ) = await _resolve_location_and_nominatim_details(
                    self.geocoder,
                    new_city,
                    region=new_region,
                    country=profile.country or None,
                )
                if geom_wkt is None and city is not None:
                    return UpdateBloggerProfileResult(
                        profile=None,
                        location_geometry_resolved=False,
                    )
                new_geometry = geom_wkt
                if region_nom is not None:
                    new_region = region_nom
                if country is None and country_nom is not None:
                    new_country = country_nom
            if new_geometry is None and location_geometry is None:
                new_geometry = profile.location_geometry
            now = datetime.now(timezone.utc)
            updated = replace(
                profile,
                instagram_url=new_instagram_url,
                confirmed=False if instagram_changed else profile.confirmed,
                city=new_city,
                region=new_region,
                country=new_country,
                location_geometry=new_geometry,
                topics=topics if topics is not None else profile.topics,
                audience_gender=audience_gender
                if audience_gender is not None
                else profile.audience_gender,
                audience_age_min=audience_age_min
                if audience_age_min is not None
                else profile.audience_age_min,
                audience_age_max=audience_age_max
                if audience_age_max is not None
                else profile.audience_age_max,
                audience_geo=(
                    audience_geo.strip()
                    if audience_geo is not None
                    else profile.audience_geo
                ),
                price=price if price is not None else profile.price,
                barter=barter if barter is not None else profile.barter,
                work_format=work_format
                if work_format is not None
                else profile.work_format,
                updated_at=now,
                blogger_gender=blogger_gender
                if blogger_gender is not None
                else profile.blogger_gender,
                birth_date=birth_date
                if birth_date is not None
                else profile.birth_date,
            )
            await self.blogger_repo.save(updated, session=session)
            return UpdateBloggerProfileResult(profile=updated)

        return await with_optional_tx(self.transaction_manager, _run)

    async def increment_wanted_to_change_terms_count(
        self, user_id: UUID
    ) -> None:
        """Increment wanted_to_change_terms_count (advertiser reason)."""

        async def _run(session: object | None) -> None:
            profile = await self.blogger_repo.get_by_user_id(
                user_id, session=session
            )
            if profile is None:
                return
            updated = replace(
                profile,
                wanted_to_change_terms_count=profile.wanted_to_change_terms_count
                + 1,
                updated_at=datetime.now(timezone.utc),
            )
            await self.blogger_repo.save(updated, session=session)

        await with_optional_tx(self.transaction_manager, _run)

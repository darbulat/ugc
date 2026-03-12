"""Repository ports for the application layer."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    AsyncContextManager,
    Dict,
    Iterable,
    List,
    Optional,
    Protocol,
    Tuple,
)
from uuid import UUID

from ugc_bot.domain.entities import (
    AdvertiserProfile,
    BloggerProfile,
    Complaint,
    ContactPricing,
    Country,
    InstagramStats,
    InstagramVerificationCode,
    Interaction,
    OfferDispatch,
    Order,
    OutboxEvent,
    Payment,
    PayoutRequest,
    ReferralOrderIncomeRow,
    User,
    UserReferralBinding,
    UserReferralPending,
)
from ugc_bot.domain.enums import MessengerType, PayoutRequestStatus

if TYPE_CHECKING:
    from ugc_bot.domain.enums import ComplaintStatus, InteractionStatus


class UserRepository(ABC):
    """Port for user persistence."""

    @abstractmethod
    async def get_by_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[User]:
        """Fetch a user by ID."""

    async def get_by_ids(
        self,
        user_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, User]:
        """Fetch users by IDs. Override for batch implementation."""
        result: Dict[UUID, User] = {}
        for uid in user_ids:
            u = await self.get_by_id(uid, session=session)
            if u is not None:
                result[uid] = u
        return result

    @abstractmethod
    async def get_by_external(
        self,
        external_id: str,
        messenger_type: MessengerType,
        session: object | None = None,
    ) -> Optional[User]:
        """Fetch a user by external messenger id."""

    @abstractmethod
    async def get_by_referral_code(
        self, referral_code: str, session: object | None = None
    ) -> Optional[User]:
        """Fetch a user by referral code."""

    @abstractmethod
    async def get_by_telegram(
        self, telegram: str, session: object | None = None
    ) -> Optional[User]:
        """Fetch a user by Telegram username (case-insensitive, @ stripped)."""

    @abstractmethod
    async def save(self, user: User, session: object | None = None) -> None:
        """Persist a user."""

    @abstractmethod
    async def list_pending_role_reminders(
        self, reminder_cutoff: datetime, session: object | None = None
    ) -> Iterable[User]:
        """List users who have not chosen a role and are due for a reminder."""

    async def iter_all(self) -> Iterable[User]:
        """Iterate all users (optional)."""

        raise NotImplementedError  # pragma: no cover

    async def list_admins(
        self,
        messenger_type: MessengerType | None = None,
        session: object | None = None,
    ) -> Iterable[User]:
        """List users with admin=True. Optionally filter by messenger_type."""

        raise NotImplementedError  # pragma: no cover


class BloggerProfileRepository(ABC):
    """Port for blogger profile persistence."""

    @abstractmethod
    async def get_by_user_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[BloggerProfile]:
        """Fetch blogger profile by user id."""

    async def get_by_user_ids(
        self,
        user_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, BloggerProfile]:
        """Fetch blogger profiles by user IDs. Override for batch impl."""
        result: Dict[UUID, BloggerProfile] = {}
        for uid in user_ids:
            p = await self.get_by_user_id(uid, session=session)
            if p is not None:
                result[uid] = p
        return result

    @abstractmethod
    async def get_by_instagram_url(
        self, instagram_url: str, session: object | None = None
    ) -> Optional[BloggerProfile]:
        """Fetch blogger profile by Instagram URL."""

    @abstractmethod
    async def save(
        self, profile: BloggerProfile, session: object | None = None
    ) -> None:
        """Persist blogger profile."""

    @abstractmethod
    async def list_confirmed_user_ids(
        self,
        session: object | None = None,
        location_geometry_wkt: Optional[str] = None,
    ) -> list[UUID]:
        """List user ids with confirmed blogger profiles.

        When location_geometry_wkt is set (MULTIPOLYGON WKT), only return
        bloggers whose location_geometry intersects the given geometry.
        """

    @abstractmethod
    async def list_confirmed_with_instagram_id(
        self,
        limit: int,
        offset: int = 0,
        stats_older_than: Optional[datetime] = None,
        session: object | None = None,
    ) -> List[BloggerProfile]:
        """List confirmed blogger profiles with non-empty instagram_user_id.

        When stats_older_than is set, return only profiles that need stats
        update: no row in instagram_stats or instagram_stats.fetched_at
        is older than stats_older_than.
        """


class AdvertiserProfileRepository(ABC):
    """Port for advertiser profile persistence."""

    @abstractmethod
    async def get_by_user_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[AdvertiserProfile]:
        """Fetch advertiser profile by user id."""

    @abstractmethod
    async def save(
        self, profile: AdvertiserProfile, session: object | None = None
    ) -> None:
        """Persist advertiser profile."""


class OrderRepository(ABC):
    """Port for order persistence."""

    @abstractmethod
    async def get_by_id(
        self, order_id: UUID, session: object | None = None
    ) -> Optional[Order]:
        """Fetch order by ID."""

    @abstractmethod
    async def get_by_id_for_update(
        self, order_id: UUID, session: object | None = None
    ) -> Optional[Order]:
        """Fetch order by ID with a row lock when supported."""

    @abstractmethod
    async def list_active(
        self, session: object | None = None
    ) -> Iterable[Order]:
        """List active orders."""

    @abstractmethod
    async def list_by_advertiser(
        self, advertiser_id: UUID, session: object | None = None
    ) -> Iterable[Order]:
        """List orders by advertiser."""

    @abstractmethod
    async def list_completed_before(
        self, cutoff: datetime, session: object | None = None
    ) -> Iterable[Order]:
        """List orders completed before cutoff."""

    @abstractmethod
    async def count_by_advertiser(
        self, advertiser_id: UUID, session: object | None = None
    ) -> int:
        """Count orders by advertiser."""

    @abstractmethod
    async def save(self, order: Order, session: object | None = None) -> None:
        """Persist order."""


class OfferDispatchRepository(ABC):
    """Port for offer dispatches and responses (sent offers and accept/skip)."""

    @abstractmethod
    async def record_sent(
        self,
        order_id: UUID,
        blogger_id: UUID,
        session: object | None = None,
    ) -> None:
        """Record that an offer was sent to a blogger for an order."""

    @abstractmethod
    async def record_response(
        self,
        order_id: UUID,
        blogger_id: UUID,
        accepted: bool,
        in_offer: bool,
        session: object | None = None,
    ) -> None:
        """Update dispatch with response (accepted/in_offer) and updated_at."""

    @abstractmethod
    async def list_blogger_ids_sent_for_order(
        self, order_id: UUID, session: object | None = None
    ) -> list[UUID]:
        """List blogger ids who already received an offer for this order."""

    @abstractmethod
    async def list_responses_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> Iterable[OfferDispatch]:
        """List dispatches (with response) by order."""

    @abstractmethod
    async def list_responses_by_blogger(
        self,
        blogger_id: UUID,
        session: object | None = None,
        in_offer_only: bool = False,
    ) -> Iterable[OfferDispatch]:
        """List dispatches where blogger responded (accepted is not null)."""

    @abstractmethod
    async def exists_responded(
        self, order_id: UUID, blogger_id: UUID, session: object | None = None
    ) -> bool:
        """Check if blogger already responded (accepted is not null)."""

    @abstractmethod
    async def count_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> int:
        """Count dispatches by order (all rows)."""

    @abstractmethod
    async def count_accepted_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> int:
        """Count in_offer=true by order (accepted within limit)."""

    @abstractmethod
    async def count_completed_orders_by_blogger_ids(
        self,
        blogger_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, int]:
        """Count completed orders (CLOSED, interaction OK) per blogger ID."""


class InteractionRepository(ABC):
    """Port for interaction persistence."""

    @abstractmethod
    async def get_by_id(
        self, interaction_id: UUID, session: object | None = None
    ) -> Optional[Interaction]:
        """Fetch interaction by id."""

    @abstractmethod
    async def get_by_participants(
        self,
        order_id: UUID,
        blogger_id: UUID,
        advertiser_id: UUID,
        session: object | None = None,
    ) -> Optional[Interaction]:
        """Fetch interaction by order/blogger/advertiser."""

    @abstractmethod
    async def list_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> Iterable[Interaction]:
        """List interactions for order."""

    @abstractmethod
    async def list_due_for_feedback(
        self, cutoff: datetime, session: object | None = None
    ) -> Iterable[Interaction]:
        """List interactions due for feedback (PENDING)."""

    @abstractmethod
    async def list_by_status(
        self, status: "InteractionStatus", session: object | None = None
    ) -> Iterable[Interaction]:
        """List interactions by status."""

    @abstractmethod
    async def save(
        self, interaction: Interaction, session: object | None = None
    ) -> None:
        """Persist interaction."""

    @abstractmethod
    async def update_next_check_at(
        self,
        interaction_id: UUID,
        next_check_at: datetime,
        session: object | None = None,
    ) -> None:
        """Update next_check_at (e.g. after sending feedback request)."""

    @abstractmethod
    async def list_blogger_ids_with_unfulfilled_interaction(
        self, session: object | None = None
    ) -> list[UUID]:
        """Blogger ids with at least one interaction not in (OK, NO_DEAL)."""


class NpsRepository(ABC):
    """Port for NPS response persistence."""

    @abstractmethod
    async def save(
        self,
        user_id: UUID,
        score: int,
        comment: Optional[str] = None,
        session: object | None = None,
    ) -> None:
        """Save NPS score for a user."""

    @abstractmethod
    async def exists_for_user(
        self, user_id: UUID, session: object | None = None
    ) -> bool:
        """Check if user already gave NPS."""


class InstagramVerificationRepository(ABC):
    """Port for Instagram verification code persistence."""

    @abstractmethod
    async def save(
        self, code: InstagramVerificationCode, session: object | None = None
    ) -> None:
        """Persist verification code."""

    @abstractmethod
    async def get_valid_code(
        self, user_id: UUID, code: str, session: object | None = None
    ) -> Optional[InstagramVerificationCode]:
        """Fetch a valid, unexpired verification code."""

    @abstractmethod
    async def mark_used(
        self, code_id: UUID, session: object | None = None
    ) -> None:
        """Mark verification code as used."""

    @abstractmethod
    async def get_valid_code_by_code(
        self, code: str, session: object | None = None
    ) -> Optional[InstagramVerificationCode]:
        """Fetch valid unexpired verification code by string (for webhook)."""


class InstagramProfileInfo:
    """Instagram profile data from Graph API (IG User node)."""

    __slots__ = (
        "username",
        "followers_count",
        "media_count",
        "follows_count",
        "biography",
        "has_profile_pic",
    )

    def __init__(
        self,
        username: str,
        followers_count: Optional[int] = None,
        media_count: Optional[int] = None,
        follows_count: Optional[int] = None,
        biography: Optional[str] = None,
        has_profile_pic: Optional[bool] = None,
    ) -> None:
        self.username = username
        self.followers_count = followers_count
        self.media_count = media_count
        self.follows_count = follows_count
        self.biography = biography
        self.has_profile_pic = has_profile_pic


class InstagramGraphApiClient(ABC):
    """Port for Instagram Graph API client."""

    @abstractmethod
    async def get_username_by_id(self, instagram_user_id: str) -> str | None:
        """Get Instagram username by user ID.

        Args:
            instagram_user_id: Instagram-scoped user ID (sender_id from webhook)

        Returns:
            Username if found, None otherwise
        """

    @abstractmethod
    async def get_profile_by_id(
        self, instagram_user_id: str
    ) -> Optional["InstagramProfileInfo"]:
        """Get full profile (username, counts, biography) by user ID.

        Args:
            instagram_user_id: Instagram-scoped user ID (sender_id from webhook)

        Returns:
            Profile info if found, None on error or missing username
        """


class InstagramStatsRepository(ABC):
    """Port for Instagram stats persistence (Rapid API results)."""

    @abstractmethod
    async def get_by_user_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[InstagramStats]:
        """Fetch Instagram stats by user id."""

    async def get_by_user_ids(
        self,
        user_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, InstagramStats]:
        """Fetch Instagram stats by user IDs. Override for batch impl."""
        result: Dict[UUID, InstagramStats] = {}
        for uid in user_ids:
            s = await self.get_by_user_id(uid, session=session)
            if s is not None:
                result[uid] = s
        return result

    @abstractmethod
    async def save(
        self, stats: InstagramStats, session: object | None = None
    ) -> None:
        """Persist or update Instagram stats (upsert by user_id)."""


class RapidApiRateLimitError(Exception):
    """Raised when Rapid API returns 429 Too Many Requests."""


class InstagramRapidApiClient(ABC):
    """Port for Rapid API Instagram profile/stats by username."""

    @abstractmethod
    async def get_profile_stats_by_username(
        self, username: str
    ) -> Optional[dict]:
        """Fetch full profile/stats response for username.

        Returns:
            Raw API response dict, or None on error / not found.
        Raises:
            RapidApiRateLimitError: When API returns 429 (caller may try next).
        """


class InstagramStatsProviderClient(ABC):
    """Client that returns Instagram stats with provider id (fallback chain)."""

    @abstractmethod
    async def get_profile_stats_with_provider(
        self, username: str
    ) -> Tuple[Optional[dict], str]:
        """Fetch profile/stats and the provider id that returned them.

        Returns:
            (raw_response_dict, provider_id) or (None, provider_id on last try).
        """


class PaymentRepository(ABC):
    """Port for payment persistence."""

    @abstractmethod
    async def get_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> Optional[Payment]:
        """Fetch payment by order id."""

    @abstractmethod
    async def get_by_external_id(
        self, external_id: str, session: object | None = None
    ) -> Optional[Payment]:
        """Fetch payment by provider external id."""

    @abstractmethod
    async def save(
        self, payment: Payment, session: object | None = None
    ) -> None:
        """Persist payment."""


class ContactPricingRepository(ABC):
    """Port for contact pricing persistence."""

    @abstractmethod
    async def get_by_bloggers_count(
        self, bloggers_count: int, session: object | None = None
    ) -> Optional[ContactPricing]:
        """Fetch pricing by bloggers count."""


class BotTextsRepository(ABC):
    """Port for localized bot text persistence (key, locale -> value)."""

    @abstractmethod
    async def get(
        self, key: str, locale: str, session: object | None = None
    ) -> Optional[str]:
        """Fetch text value for key and locale. Returns None if not found."""

    @abstractmethod
    async def get_all(
        self, session: object | None = None
    ) -> List[Tuple[str, str, str]]:
        """Fetch all texts as (key, locale, value). Preload at startup."""


class OrderActivationPublisher(ABC):
    """Port for publishing order activation events."""

    @abstractmethod
    async def publish(self, order: Order) -> None:
        """Publish order activation message."""


class OutboxRepository(ABC):
    """Port for outbox event persistence."""

    @abstractmethod
    async def save(
        self, event: OutboxEvent, session: object | None = None
    ) -> None:
        """Persist outbox event."""

    @abstractmethod
    async def get_pending_events(
        self, limit: int = 100, session: object | None = None
    ) -> list[OutboxEvent]:
        """Get pending events for processing."""

    @abstractmethod
    async def claim_pending_events(
        self, limit: int = 100, session: object | None = None
    ) -> list[OutboxEvent]:
        """Claim pending events (set to PROCESSING) and return them."""

    @abstractmethod
    async def mark_as_processing(
        self, event_id: UUID, session: object | None = None
    ) -> None:
        """Mark event as processing."""

    @abstractmethod
    async def mark_as_published(
        self,
        event_id: UUID,
        processed_at: datetime,
        session: object | None = None,
    ) -> None:
        """Mark event as published."""

    @abstractmethod
    async def mark_as_failed(
        self,
        event_id: UUID,
        error: str,
        retry_count: int,
        session: object | None = None,
    ) -> None:
        """Mark event as failed (terminal state)."""

    @abstractmethod
    async def mark_for_retry(
        self,
        event_id: UUID,
        error: str,
        retry_count: int,
        session: object | None = None,
    ) -> None:
        """Reset event to PENDING for retry; set retry_count and last_error."""

    @abstractmethod
    async def get_by_id(
        self, event_id: UUID, session: object | None = None
    ) -> Optional[OutboxEvent]:
        """Get event by ID."""

    @abstractmethod
    async def delete_processed_events(
        self,
        retention_days: int,
        batch_size: int,
        session: object | None = None,
    ) -> int:
        """Delete PUBLISHED/FAILED events older than retention_days.

        Returns deleted count.
        """

    @abstractmethod
    async def reset_stale_processing_events(
        self,
        stale_after_minutes: int = 15,
        session: object | None = None,
    ) -> int:
        """Reset stale PROCESSING events back to PENDING.

        Events that have been in PROCESSING state longer than
        stale_after_minutes are reset so they can be retried.
        Returns count of reset events.
        """


class ComplaintRepository(ABC):
    """Port for complaint persistence."""

    @abstractmethod
    async def save(
        self, complaint: Complaint, session: object | None = None
    ) -> None:
        """Persist complaint."""

    @abstractmethod
    async def get_by_id(
        self, complaint_id: UUID, session: object | None = None
    ) -> Optional[Complaint]:
        """Get complaint by ID."""

    @abstractmethod
    async def list_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> Iterable[Complaint]:
        """List complaints for a specific order."""

    @abstractmethod
    async def list_by_reporter(
        self, reporter_id: UUID, session: object | None = None
    ) -> Iterable[Complaint]:
        """List complaints filed by a specific user."""

    @abstractmethod
    async def exists(
        self, order_id: UUID, reporter_id: UUID, session: object | None = None
    ) -> bool:
        """Check if reporter already filed a complaint for this order."""

    @abstractmethod
    async def list_by_status(
        self, status: "ComplaintStatus", session: object | None = None
    ) -> Iterable[Complaint]:
        """List complaints by status."""


class UserReferralBindingRepository(ABC):
    """Port for user referral binding persistence (referrer -> referred)."""

    @abstractmethod
    async def save(
        self,
        binding: UserReferralBinding,
        session: object | None = None,
    ) -> None:
        """Persist referral binding."""

    @abstractmethod
    async def get_by_referred_user(
        self, referred_user_id: UUID, session: object | None = None
    ) -> Optional[UserReferralBinding]:
        """Fetch binding by referred user ID."""

    @abstractmethod
    async def list_by_referrer(
        self,
        referrer_user_id: UUID,
        offset: int = 0,
        limit: int = 10,
        session: object | None = None,
    ) -> Iterable[UserReferralBinding]:
        """List bindings by referrer user ID with pagination."""

    @abstractmethod
    async def count_by_referrer(
        self, referrer_user_id: UUID, session: object | None = None
    ) -> int:
        """Count bindings by referrer user ID."""


class UserReferralPendingRepository(ABC):
    """Port for pending referral bindings until creator registration."""

    @abstractmethod
    async def save(
        self,
        pending: UserReferralPending,
        session: object | None = None,
    ) -> None:
        """Persist pending referral."""

    @abstractmethod
    async def get_by_user(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[UserReferralPending]:
        """Fetch pending referral by user ID."""

    @abstractmethod
    async def delete_by_user(
        self, user_id: UUID, session: object | None = None
    ) -> None:
        """Delete pending referral by user ID."""

    @abstractmethod
    async def list_by_referrer(
        self,
        referrer_user_id: UUID,
        offset: int = 0,
        limit: int = 100,
        session: object | None = None,
    ) -> Iterable[UserReferralPending]:
        """List pending referrals by referrer user ID with pagination."""

    @abstractmethod
    async def count_by_referrer(
        self, referrer_user_id: UUID, session: object | None = None
    ) -> int:
        """Count pending referrals by referrer user ID."""


class PayoutRequestRepository(ABC):
    """Port for payout request persistence."""

    @abstractmethod
    async def save(
        self,
        request: PayoutRequest,
        session: object | None = None,
    ) -> None:
        """Persist payout request."""

    @abstractmethod
    async def get_by_id(
        self, request_id: UUID, session: object | None = None
    ) -> Optional[PayoutRequest]:
        """Fetch payout request by ID."""

    @abstractmethod
    async def update_status(
        self,
        request_id: UUID,
        status: PayoutRequestStatus,
        session: object | None = None,
    ) -> bool:
        """Update payout request status. Returns True if row was updated."""

    @abstractmethod
    async def list_by_user(
        self, user_id: UUID, session: object | None = None
    ) -> Iterable[PayoutRequest]:
        """List payout requests by user ID."""

    async def list_by_user_ids(
        self,
        user_ids: List[UUID],
        session: object | None = None,
    ) -> Iterable[PayoutRequest]:
        """Payout requests for given user IDs. Default: N×list_by_user."""
        result: List[PayoutRequest] = []
        for uid in user_ids:
            result.extend(await self.list_by_user(uid, session=session))
        return result


class ReferralOrderIncomeRowLoader(Protocol):
    """Load referral order income rows in one query (reduces N+1)."""

    async def load_referral_order_income_rows(
        self,
        referrer_user_id: UUID,
        limit: int,
        session: object | None = None,
    ) -> list[ReferralOrderIncomeRow]:
        """Return completed-order rows for referred creators."""
        ...

    async def load_referral_order_income_rows_advertisers(
        self,
        referrer_user_id: UUID,
        limit: int,
        session: object | None = None,
    ) -> list[ReferralOrderIncomeRow]:
        """Return rows for referred advertisers (CLOSED, PAID)."""
        ...

    async def load_referral_order_income_rows_combined(
        self,
        referrer_user_id: UUID,
        limit: int,
        session: object | None = None,
    ) -> list[ReferralOrderIncomeRow]:
        """Optional: blogger + advertiser rows in one query (UNION)."""
        ...

    async def load_referral_order_income_rows_combined_batch(
        self,
        referrer_user_ids: List[UUID],
        limit: Optional[int] = None,
        session: object | None = None,
    ) -> List[Tuple[UUID, ReferralOrderIncomeRow]]:
        """Income rows for multiple referrers in one query."""
        ...


class GeocoderPort(Protocol):
    """Port for geocoding city/address to (lat, lon) and resolving polygons."""

    async def geocode(
        self,
        query: str,
        region: Optional[str] = None,
        country: str = "Russia",
    ) -> Optional[Tuple[float, float]]:
        """Return (latitude, longitude) for the query, or None if not found."""
        ...

    async def geocode_with_details(
        self,
        query: str,
        region: Optional[str] = None,
        country: Optional[str] = None,
    ) -> Optional[Tuple[float, float, str, str, Optional[str], Optional[str]]]:
        """Return details for query or None when not found.

        Returns:
            Tuple of:
            - lat (float)
            - lon (float)
            - place_class (str): provider-specific class/category (e.g. OSM
              class for Nominatim)
            - place_type (str): provider-specific type (e.g. OSM type for
              Nominatim)
            - region (str | None): best-effort region extracted from response
            - country (str | None): best-effort country extracted from response
        """
        ...

    def accepts_as_populated_place(
        self, place_class: str, place_type: str
    ) -> bool:
        """Return True when place_class/type represent a populated place.

        This is intentionally provider-specific: each geocoder implementation
        encapsulates its own taxonomy/mapping (OSM, Dadata, etc.).
        """
        ...

    def accepts_as_place_or_region(
        self, place_class: str, place_type: str
    ) -> bool:
        """Return True when place_class/type represent a place or a region.

        Used for cases where both populated places and administrative regions
        are acceptable (e.g. backfills from free-text city field).
        """
        ...

    async def get_multipolygon_wkt_for_queries(
        self,
        queries: List[Tuple[str, Optional[str], str]],
    ) -> Optional[str]:
        """Resolve (query, region, country) list to one MULTIPOLYGON WKT."""
        ...

    async def reverse_geocode(
        self, lat: float, lon: float
    ) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
        """Return (city, region, country) for coordinates or None."""
        ...


class CountryRepository(ABC):
    """Port for country persistence."""

    @abstractmethod
    async def list_enabled(
        self, session: object | None = None
    ) -> list[Country]:
        """List enabled countries."""

    @abstractmethod
    async def get_by_code(
        self, code: str, session: object | None = None
    ) -> Optional[Country]:
        """Fetch country by code."""

    @abstractmethod
    async def get_by_currency_code(
        self, currency_code: str, session: object | None = None
    ) -> Optional[Country]:
        """Fetch any enabled country with the given currency code."""



class TransactionManager(Protocol):
    """Protocol for transaction handling used by application services.

    Services receive a TransactionManager that provides a session via
    async with tm.transaction() as session. The implementation (e.g.
    SessionTransactionManager in infrastructure) commits on success and
    rolls back on exception.
    """

    def transaction(self) -> AsyncContextManager[object]:
        """Return an async context manager yielding a session.

        Use: async with tm.transaction() as session: ...
        """

"""In-memory repository implementations."""

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple
from uuid import UUID

from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    BloggerProfileRepository,
    ComplaintRepository,
    ContactPricingRepository,
    CountryRepository,
    InstagramGraphApiClient,
    InstagramProfileInfo,
    InstagramRapidApiClient,
    InstagramStatsRepository,
    InstagramVerificationRepository,
    InteractionRepository,
    LanguageRepository,
    ManagerOrderRepository,
    NpsRepository,
    OfferDispatchRepository,
    OrderRepository,
    OutboxRepository,
    PaymentRepository,
    PayoutRequestRepository,
    UserReferralBindingRepository,
    UserReferralPendingRepository,
    UserRepository,
)
from ugc_bot.domain.entities import (
    AdvertiserProfile,
    BloggerProfile,
    Complaint,
    ContactPricing,
    Country,
    InstagramStats,
    InstagramVerificationCode,
    Interaction,
    Language,
    ManagerOrder,
    OfferDispatch,
    Order,
    OutboxEvent,
    Payment,
    PayoutRequest,
    User,
    UserReferralBinding,
    UserReferralPending,
)
from ugc_bot.domain.enums import (
    ComplaintStatus,
    InteractionStatus,
    MessengerType,
    OrderStatus,
    OutboxEventStatus,
    PayoutRequestStatus,
)


@dataclass
class InMemoryUserRepository(UserRepository):
    """In-memory implementation of user repository."""

    users: Dict[UUID, User] = field(default_factory=dict)
    external_index: Dict[Tuple[str, MessengerType], UUID] = field(
        default_factory=dict
    )

    async def get_by_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[User]:
        """Fetch a user by ID."""

        return self.users.get(user_id)

    async def get_by_external(
        self,
        external_id: str,
        messenger_type: MessengerType,
        session: object | None = None,
    ) -> Optional[User]:
        """Fetch a user by external messenger id."""

        key = (external_id, messenger_type)
        user_id = self.external_index.get(key)
        return self.users.get(user_id) if user_id else None

    async def get_by_referral_code(
        self, referral_code: str, session: object | None = None
    ) -> Optional[User]:
        """Fetch a user by referral code."""

        for u in self.users.values():
            if getattr(u, "referral_code", None) == referral_code:
                return u
        return None

    async def get_by_telegram(
        self, telegram: str, session: object | None = None
    ) -> Optional[User]:
        """Fetch a user by Telegram username (case-insensitive, @ stripped)."""
        normalized = (telegram or "").strip().lstrip("@").lower()
        if not normalized:
            return None
        for u in self.users.values():
            t = getattr(u, "telegram", None)
            if t and t.strip().lstrip("@").lower() == normalized:
                return u
        return None

    async def save(self, user: User, session: object | None = None) -> None:
        """Persist a user in memory."""

        self.users[user.user_id] = user
        self.external_index[(user.external_id, user.messenger_type)] = (
            user.user_id
        )

    async def list_pending_role_reminders(
        self, reminder_cutoff: datetime, session: object | None = None
    ) -> Iterable[User]:
        """List users who have not chosen a role and are due for a reminder."""

        return [
            u
            for u in self.users.values()
            if u.role_chosen_at is None
            and (
                u.last_role_reminder_at is None
                or u.last_role_reminder_at < reminder_cutoff
            )
        ]

    async def iter_all(self) -> Iterable[User]:
        """Iterate all users."""

        return list(self.users.values())

    async def list_admins(
        self,
        messenger_type: MessengerType | None = None,
        session: object | None = None,
    ) -> Iterable[User]:
        """List users with admin=True. Optionally filter by messenger_type."""

        result = [u for u in self.users.values() if getattr(u, "admin", False)]
        if messenger_type is not None:
            result = [u for u in result if u.messenger_type == messenger_type]
        return result


@dataclass
class InMemoryUserReferralBindingRepository(UserReferralBindingRepository):
    """In-memory implementation of user referral binding repository."""

    _bindings: List[UserReferralBinding] = field(default_factory=list)

    async def save(
        self,
        binding: UserReferralBinding,
        session: object | None = None,
    ) -> None:
        """Persist referral binding."""
        self._bindings = [
            b
            for b in self._bindings
            if b.referred_user_id != binding.referred_user_id
        ]
        self._bindings.append(binding)

    async def get_by_referred_user(
        self, referred_user_id: UUID, session: object | None = None
    ) -> Optional[UserReferralBinding]:
        """Fetch binding by referred user ID."""
        for b in self._bindings:
            if b.referred_user_id == referred_user_id:
                return b
        return None

    async def list_by_referrer(
        self,
        referrer_user_id: UUID,
        offset: int = 0,
        limit: int = 10,
        session: object | None = None,
    ) -> Iterable[UserReferralBinding]:
        """List bindings by referrer user ID with pagination."""
        by_referrer = [
            b for b in self._bindings if b.referrer_user_id == referrer_user_id
        ]
        by_referrer.sort(key=lambda x: x.created_at)
        return by_referrer[offset : offset + limit]

    async def count_by_referrer(
        self, referrer_user_id: UUID, session: object | None = None
    ) -> int:
        """Count bindings by referrer user ID."""
        return sum(
            1 for b in self._bindings if b.referrer_user_id == referrer_user_id
        )


@dataclass
class InMemoryUserReferralPendingRepository(UserReferralPendingRepository):
    """In-memory implementation of user referral pending repository."""

    _pending: Dict[UUID, UserReferralPending] = field(default_factory=dict)

    async def save(
        self,
        pending: UserReferralPending,
        session: object | None = None,
    ) -> None:
        """Persist pending referral."""
        self._pending[pending.user_id] = pending

    async def get_by_user(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[UserReferralPending]:
        """Fetch pending referral by user ID."""
        return self._pending.get(user_id)

    async def delete_by_user(
        self, user_id: UUID, session: object | None = None
    ) -> None:
        """Delete pending referral by user ID."""
        self._pending.pop(user_id, None)

    async def list_by_referrer(
        self,
        referrer_user_id: UUID,
        offset: int = 0,
        limit: int = 100,
        session: object | None = None,
    ) -> Iterable[UserReferralPending]:
        """List pending referrals by referrer user ID with pagination."""
        by_referrer = [
            p
            for p in self._pending.values()
            if p.referrer_user_id == referrer_user_id
        ]
        by_referrer.sort(key=lambda x: x.created_at)
        return by_referrer[offset : offset + limit]

    async def count_by_referrer(
        self, referrer_user_id: UUID, session: object | None = None
    ) -> int:
        """Count pending referrals by referrer user ID."""
        return sum(
            1
            for p in self._pending.values()
            if p.referrer_user_id == referrer_user_id
        )


@dataclass
class InMemoryPayoutRequestRepository(PayoutRequestRepository):
    """In-memory implementation of payout request repository."""

    _requests: Dict[UUID, PayoutRequest] = field(default_factory=dict)

    async def save(
        self,
        request: PayoutRequest,
        session: object | None = None,
    ) -> None:
        """Persist payout request."""
        self._requests[request.request_id] = request

    async def get_by_id(
        self, request_id: UUID, session: object | None = None
    ) -> Optional[PayoutRequest]:
        """Fetch payout request by ID."""
        return self._requests.get(request_id)

    async def update_status(
        self,
        request_id: UUID,
        status: PayoutRequestStatus,
        session: object | None = None,
    ) -> bool:
        """Update payout request status. Returns True if row was updated."""
        request = self._requests.get(request_id)
        if request is None:
            return False
        self._requests[request_id] = replace(request, status=status)
        return True

    async def list_by_user(
        self, user_id: UUID, session: object | None = None
    ) -> Iterable[PayoutRequest]:
        """List payout requests by user ID."""
        return [r for r in self._requests.values() if r.user_id == user_id]


@dataclass
class InMemoryBloggerProfileRepository(BloggerProfileRepository):
    """In-memory implementation of blogger profile repository."""

    profiles: Dict[UUID, BloggerProfile] = field(default_factory=dict)

    async def get_by_user_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[BloggerProfile]:
        """Fetch blogger profile by user id."""

        return self.profiles.get(user_id)

    async def get_by_user_ids(
        self,
        user_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, BloggerProfile]:
        """Fetch blogger profiles by user IDs."""
        return {
            uid: self.profiles[uid] for uid in user_ids if uid in self.profiles
        }

    async def get_by_instagram_url(
        self, instagram_url: str, session: object | None = None
    ) -> Optional[BloggerProfile]:
        """Fetch blogger profile by Instagram URL."""

        for profile in self.profiles.values():
            if profile.instagram_url == instagram_url:
                return profile
        return None

    async def save(
        self, profile: BloggerProfile, session: object | None = None
    ) -> None:
        """Persist blogger profile in memory."""

        self.profiles[profile.user_id] = profile

    async def list_confirmed_user_ids(
        self,
        session: object | None = None,
        location_geometry_wkt: Optional[str] = None,
    ) -> list[UUID]:
        """List confirmed blogger user ids.

        location_geometry_wkt is ignored (no spatial filter in memory).
        """
        return [
            profile.user_id
            for profile in self.profiles.values()
            if profile.confirmed
        ]

    async def list_confirmed_with_instagram_id(
        self,
        limit: int,
        offset: int = 0,
        stats_older_than: Optional[datetime] = None,
        session: object | None = None,
    ) -> list[BloggerProfile]:
        """List confirmed profiles with non-empty instagram_user_id.

        stats_older_than is ignored (no instagram_stats in memory).
        """
        eligible = [
            p
            for p in self.profiles.values()
            if p.confirmed
            and getattr(p, "instagram_user_id", None)
            and (p.instagram_user_id or "").strip() != ""
        ]
        eligible.sort(key=lambda p: p.user_id)
        return eligible[offset : offset + limit]


@dataclass
class InMemoryAdvertiserProfileRepository(AdvertiserProfileRepository):
    """In-memory implementation of advertiser profile repository."""

    profiles: Dict[UUID, AdvertiserProfile] = field(default_factory=dict)

    async def get_by_user_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[AdvertiserProfile]:
        """Fetch advertiser profile by user id."""

        return self.profiles.get(user_id)

    async def save(
        self, profile: AdvertiserProfile, session: object | None = None
    ) -> None:
        """Persist advertiser profile in memory."""

        self.profiles[profile.user_id] = profile


@dataclass
class InMemoryInstagramVerificationRepository(InstagramVerificationRepository):
    """In-memory implementation of Instagram verification repository."""

    codes: Dict[UUID, InstagramVerificationCode] = field(default_factory=dict)

    async def save(
        self, code: InstagramVerificationCode, session: object | None = None
    ) -> None:
        """Persist verification code in memory."""

        self.codes[code.code_id] = code

    async def get_valid_code(
        self, user_id: UUID, code: str, session: object | None = None
    ) -> Optional[InstagramVerificationCode]:
        """Fetch a valid, unexpired verification code."""

        now = datetime.now(timezone.utc)
        for item in self.codes.values():
            if (
                item.user_id == user_id
                and item.code == code
                and not item.used
                and item.expires_at > now
            ):
                return item
        return None

    async def get_valid_code_by_code(
        self, code: str, session: object | None = None
    ) -> Optional[InstagramVerificationCode]:
        """Fetch valid unexpired verification code by string (for webhook)."""

        now = datetime.now(timezone.utc)
        for item in self.codes.values():
            if item.code == code and not item.used and item.expires_at > now:
                return item
        return None

    async def mark_used(
        self, code_id: UUID, session: object | None = None
    ) -> None:
        """Mark verification code as used."""

        if code_id not in self.codes:
            return
        existing = self.codes[code_id]
        self.codes[code_id] = InstagramVerificationCode(
            code_id=existing.code_id,
            user_id=existing.user_id,
            code=existing.code,
            expires_at=existing.expires_at,
            used=True,
            created_at=existing.created_at,
        )


@dataclass
class InMemoryInstagramStatsRepository(InstagramStatsRepository):
    """In-memory implementation of Instagram stats repository."""

    stats: Dict[UUID, InstagramStats] = field(default_factory=dict)

    async def get_by_user_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[InstagramStats]:
        """Fetch Instagram stats by user id."""
        return self.stats.get(user_id)

    async def get_by_user_ids(
        self,
        user_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, InstagramStats]:
        """Fetch Instagram stats by user IDs."""
        return {uid: self.stats[uid] for uid in user_ids if uid in self.stats}

    async def save(
        self, stats: InstagramStats, session: object | None = None
    ) -> None:
        """Persist or update Instagram stats (upsert by user_id)."""
        self.stats[stats.user_id] = stats


@dataclass
class InMemoryInstagramRapidApiClient(InstagramRapidApiClient):
    """In-memory Rapid API client for testing."""

    profile_by_username: Dict[str, dict] = field(default_factory=dict)

    async def get_profile_stats_by_username(
        self, username: str
    ) -> Optional[dict]:
        """Return pre-set response for username."""
        return self.profile_by_username.get(username)


@dataclass
class InMemoryInstagramGraphApiClient(InstagramGraphApiClient):
    """In-memory implementation of Instagram Graph API client for testing."""

    username_map: Dict[str, str] = field(default_factory=dict)
    profile_map: Dict[str, InstagramProfileInfo] = field(default_factory=dict)

    async def get_username_by_id(self, instagram_user_id: str) -> str | None:
        """Get Instagram username by user ID from in-memory map."""
        return self.username_map.get(instagram_user_id)

    async def get_profile_by_id(
        self, instagram_user_id: str
    ) -> Optional[InstagramProfileInfo]:
        """Get profile by ID: profile_map if set, else from username_map."""
        if instagram_user_id in self.profile_map:
            return self.profile_map[instagram_user_id]
        username = self.username_map.get(instagram_user_id)
        if username is not None:
            return InstagramProfileInfo(username=username)
        return None


@dataclass
class InMemoryOrderRepository(OrderRepository):
    """In-memory implementation of order repository."""

    orders: Dict[UUID, Order] = field(default_factory=dict)

    async def get_by_id(
        self, order_id: UUID, session: object | None = None
    ) -> Optional[Order]:
        """Fetch order by id."""

        return self.orders.get(order_id)

    async def get_by_id_for_update(
        self, order_id: UUID, session: object | None = None
    ) -> Optional[Order]:
        """Fetch order by id with a row lock (no-op in memory)."""

        return self.orders.get(order_id)

    async def list_active(
        self, session: object | None = None
    ) -> Iterable[Order]:
        """List active orders."""

        return [
            order
            for order in self.orders.values()
            if order.status == OrderStatus.ACTIVE
        ]

    async def list_by_advertiser(
        self, advertiser_id: UUID, session: object | None = None
    ) -> Iterable[Order]:
        """List orders by advertiser."""

        return [
            order
            for order in self.orders.values()
            if order.advertiser_id == advertiser_id
        ]

    async def list_completed_before(
        self, cutoff: datetime, session: object | None = None
    ) -> Iterable[Order]:
        """List orders completed before cutoff."""

        return [
            order
            for order in self.orders.values()
            if order.completed_at and order.completed_at <= cutoff
        ]

    async def count_by_advertiser(
        self, advertiser_id: UUID, session: object | None = None
    ) -> int:
        """Count orders by advertiser."""

        return len(
            [
                order
                for order in self.orders.values()
                if order.advertiser_id == advertiser_id
            ]
        )

    async def save(self, order: Order, session: object | None = None) -> None:
        """Persist order in memory."""

        self.orders[order.order_id] = order


@dataclass
class InMemoryOfferDispatchRepository(OfferDispatchRepository):
    """In-memory implementation of offer dispatch repository."""

    _dispatches: Dict[Tuple[UUID, UUID], OfferDispatch] = field(
        default_factory=dict
    )
    order_repo: Optional[OrderRepository] = None
    interaction_repo: Optional[InteractionRepository] = None

    async def record_sent(
        self,
        order_id: UUID,
        blogger_id: UUID,
        session: object | None = None,
    ) -> None:
        """Record that an offer was sent to a blogger for an order."""
        key = (order_id, blogger_id)
        if key not in self._dispatches:
            self._dispatches[key] = OfferDispatch(
                order_id=order_id,
                blogger_id=blogger_id,
                created_at=datetime.now(timezone.utc),
                updated_at=None,
                accepted=None,
                in_offer=False,
            )

    async def record_response(
        self,
        order_id: UUID,
        blogger_id: UUID,
        accepted: bool,
        in_offer: bool,
        session: object | None = None,
        manager_id: UUID | None = None,
    ) -> None:
        """Update dispatch with response (accepted/in_offer) and updated_at."""
        key = (order_id, blogger_id)
        now = datetime.now(timezone.utc)
        if key in self._dispatches:
            d = self._dispatches[key]
            self._dispatches[key] = replace(
                d,
                updated_at=now,
                accepted=accepted,
                in_offer=in_offer,
                manager_id=manager_id,
            )

    async def list_blogger_ids_sent_for_order(
        self, order_id: UUID, session: object | None = None
    ) -> List[UUID]:
        """List blogger ids who already received an offer for this order."""
        return [
            blogger_id
            for (oid, blogger_id) in self._dispatches
            if oid == order_id
        ]

    async def list_responses_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> List[OfferDispatch]:
        """List dispatches (with response) by order."""
        return sorted(
            [d for (oid, _), d in self._dispatches.items() if oid == order_id],
            key=lambda x: (x.updated_at or x.created_at, x.created_at),
        )

    async def list_responses_by_blogger(
        self,
        blogger_id: UUID,
        session: object | None = None,
        in_offer_only: bool = False,
    ) -> List[OfferDispatch]:
        """List dispatches where blogger responded (accepted is not null).

        When in_offer_only is True, return only dispatches in offer.
        """
        return sorted(
            [
                d
                for (_, bid), d in self._dispatches.items()
                if bid == blogger_id
                and d.accepted is not None
                and (d.in_offer if in_offer_only else True)
            ],
            key=lambda x: (x.updated_at or x.created_at, x.created_at),
            reverse=True,
        )

    async def exists_responded(
        self, order_id: UUID, blogger_id: UUID, session: object | None = None
    ) -> bool:
        """Check if blogger already responded (accepted is not null)."""
        key = (order_id, blogger_id)
        return (
            key in self._dispatches
            and self._dispatches[key].accepted is not None
        )

    async def count_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> int:
        """Count dispatches by order (all rows)."""
        return sum(1 for (oid, _) in self._dispatches if oid == order_id)

    async def count_accepted_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> int:
        """Count in_offer=true by order (accepted within limit)."""
        return sum(
            1
            for (oid, _), d in self._dispatches.items()
            if oid == order_id and d.in_offer
        )

    async def count_completed_orders_by_blogger_ids(
        self,
        blogger_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, int]:
        """Count completed orders (CLOSED, interaction OK) per blogger ID."""
        if self.order_repo is None or self.interaction_repo is None:
            return {uid: 0 for uid in blogger_ids}
        result = {uid: 0 for uid in blogger_ids}
        for blogger_id in blogger_ids:
            dispatches = await self.list_responses_by_blogger(
                blogger_id, session=session
            )
            for d in dispatches:
                if not d.in_offer:
                    continue
                order = await self.order_repo.get_by_id(
                    d.order_id, session=session
                )
                if order is None or order.status != OrderStatus.CLOSED:
                    continue
                interaction = await self.interaction_repo.get_by_participants(
                    order_id=d.order_id,
                    blogger_id=blogger_id,
                    advertiser_id=order.advertiser_id,
                    session=session,
                )
                if (
                    interaction is not None
                    and interaction.status == InteractionStatus.OK
                ):
                    result[blogger_id] = result.get(blogger_id, 0) + 1
        return result

    async def list_responses_by_order_and_manager(
        self,
        order_id: UUID,
        manager_id: UUID,
        in_offer: bool,
        limit: int = 20,
        offset: int = 0,
        session: object | None = None,
    ) -> list[OfferDispatch]:
        """List dispatches by order and manager with pagination."""
        matches = sorted(
            [
                d
                for d in self._dispatches.values()
                if d.order_id == order_id
                and d.manager_id == manager_id
                and d.in_offer == in_offer
                and d.accepted is True
            ],
            key=lambda x: (x.updated_at or x.created_at, x.created_at),
        )
        return matches[offset : offset + limit]

    async def count_responses_by_order_and_manager(
        self,
        order_id: UUID,
        manager_id: UUID,
        in_offer: bool,
        session: object | None = None,
    ) -> int:
        """Count dispatches by order and manager."""
        return sum(
            1
            for d in self._dispatches.values()
            if d.order_id == order_id
            and d.manager_id == manager_id
            and d.in_offer == in_offer
            and d.accepted is True
        )


@dataclass
class InMemoryInteractionRepository(InteractionRepository):
    """In-memory implementation of interaction repository."""

    interactions: Dict[UUID, Interaction] = field(default_factory=dict)

    async def get_by_id(
        self, interaction_id: UUID, session: object | None = None
    ) -> Optional[Interaction]:
        """Fetch interaction by id."""

        return self.interactions.get(interaction_id)

    async def get_by_participants(
        self,
        order_id: UUID,
        blogger_id: UUID,
        advertiser_id: UUID,
        session: object | None = None,
    ) -> Optional[Interaction]:
        """Fetch interaction by order/blogger/advertiser."""

        for item in self.interactions.values():
            if (
                item.order_id == order_id
                and item.blogger_id == blogger_id
                and item.advertiser_id == advertiser_id
            ):
                return item
        return None

    async def list_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> Iterable[Interaction]:
        """List interactions for order."""

        return [
            item
            for item in self.interactions.values()
            if item.order_id == order_id
        ]

    async def list_due_for_feedback(
        self, cutoff: datetime, session: object | None = None
    ) -> Iterable[Interaction]:
        """List interactions due for feedback."""

        return [
            item
            for item in self.interactions.values()
            if item.next_check_at is not None
            and item.next_check_at <= cutoff
            and item.status == InteractionStatus.PENDING
        ]

    async def list_by_status(
        self, status: InteractionStatus, session: object | None = None
    ) -> Iterable[Interaction]:
        """List interactions by status."""

        return [
            item for item in self.interactions.values() if item.status == status
        ]

    async def save(
        self, interaction: Interaction, session: object | None = None
    ) -> None:
        """Persist interaction in memory."""

        self.interactions[interaction.interaction_id] = interaction

    async def update_next_check_at(
        self,
        interaction_id: UUID,
        next_check_at: datetime,
        session: object | None = None,
    ) -> None:
        """Update next_check_at for an interaction."""

        interaction = self.interactions.get(interaction_id)
        if interaction is not None:
            updated = replace(interaction, next_check_at=next_check_at)
            self.interactions[interaction_id] = updated

    async def list_blogger_ids_with_unfulfilled_interaction(
        self, session: object | None = None
    ) -> list[UUID]:
        """Blogger ids with at least one interaction PENDING or ISSUE."""

        unfulfilled = {
            i.blogger_id
            for i in self.interactions.values()
            if i.status in (InteractionStatus.PENDING, InteractionStatus.ISSUE)
        }
        return list(unfulfilled)


@dataclass
class InMemoryNpsRepository(NpsRepository):
    """In-memory NPS repository for tests."""

    scores: Dict[UUID, List[tuple[int, Optional[str]]]] = field(
        default_factory=lambda: {}
    )

    async def save(
        self,
        user_id: UUID,
        score: int,
        comment: Optional[str] = None,
        session: object | None = None,
    ) -> None:
        """Save NPS score in memory."""
        if user_id not in self.scores:
            self.scores[user_id] = []
        self.scores[user_id].append((score, comment))

    async def exists_for_user(
        self, user_id: UUID, session: object | None = None
    ) -> bool:
        """Check if user already gave NPS."""
        return user_id in self.scores and len(self.scores[user_id]) > 0


@dataclass
class InMemoryPaymentRepository(PaymentRepository):
    """In-memory implementation of payment repository."""

    payments: Dict[UUID, Payment] = field(default_factory=dict)

    async def get_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> Optional[Payment]:
        """Fetch payment by order id."""

        for payment in self.payments.values():
            if payment.order_id == order_id:
                return payment
        return None

    async def get_by_external_id(
        self, external_id: str, session: object | None = None
    ) -> Optional[Payment]:
        """Fetch payment by provider external id."""

        for payment in self.payments.values():
            if payment.external_id == external_id:
                return payment
        return None

    async def save(
        self, payment: Payment, session: object | None = None
    ) -> None:
        """Persist payment in memory."""

        self.payments[payment.payment_id] = payment


@dataclass
class InMemoryContactPricingRepository(ContactPricingRepository):
    """In-memory contact pricing repository."""

    prices: Dict[int, ContactPricing] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize with default prices."""

        if not self.prices:
            now = datetime.now(timezone.utc)
            self.prices = {
                3: ContactPricing(bloggers_count=3, price=0.0, updated_at=now),
                10: ContactPricing(
                    bloggers_count=10, price=0.0, updated_at=now
                ),
                20: ContactPricing(
                    bloggers_count=20, price=0.0, updated_at=now
                ),
                30: ContactPricing(
                    bloggers_count=30, price=0.0, updated_at=now
                ),
                50: ContactPricing(
                    bloggers_count=50, price=0.0, updated_at=now
                ),
            }

    async def get_by_bloggers_count(
        self, bloggers_count: int, session: object | None = None
    ) -> Optional[ContactPricing]:
        """Fetch pricing by bloggers count."""

        return self.prices.get(bloggers_count)

    async def save(self, pricing: ContactPricing) -> None:
        """Persist pricing in memory."""

        self.prices[pricing.bloggers_count] = pricing


@dataclass
class InMemoryOutboxRepository(OutboxRepository):
    """In-memory outbox repository."""

    events: Dict[UUID, OutboxEvent] = field(default_factory=dict)
    _claimed_at: Dict[UUID, datetime] = field(default_factory=dict)

    async def save(
        self, event: OutboxEvent, session: object | None = None
    ) -> None:
        """Persist outbox event."""

        self.events[event.event_id] = event

    async def get_pending_events(
        self, limit: int = 100, session: object | None = None
    ) -> List[OutboxEvent]:
        """Get pending events for processing."""

        pending_events = [
            event
            for event in self.events.values()
            if event.status == OutboxEventStatus.PENDING
        ]
        return sorted(pending_events, key=lambda e: e.created_at)[:limit]

    async def claim_pending_events(
        self, limit: int = 100, session: object | None = None
    ) -> List[OutboxEvent]:
        """Claim pending events (set to PROCESSING) and return them."""

        pending = [
            event
            for event in self.events.values()
            if event.status == OutboxEventStatus.PENDING
        ]
        to_claim = sorted(pending, key=lambda e: e.created_at)[:limit]
        now = datetime.now(timezone.utc)
        for event in to_claim:
            self.events[event.event_id] = replace(
                event, status=OutboxEventStatus.PROCESSING
            )
            self._claimed_at[event.event_id] = now
        return to_claim

    async def mark_as_processing(
        self, event_id: UUID, session: object | None = None
    ) -> None:
        """Mark event as processing."""

        if event_id in self.events:
            event = self.events[event_id]
            self.events[event_id] = replace(
                event, status=OutboxEventStatus.PROCESSING
            )

    async def mark_as_published(
        self,
        event_id: UUID,
        processed_at: datetime,
        session: object | None = None,
    ) -> None:
        """Mark event as published."""

        if event_id in self.events:
            event = self.events[event_id]
            self.events[event_id] = replace(
                event,
                status=OutboxEventStatus.PUBLISHED,
                processed_at=processed_at,
            )

    async def mark_as_failed(
        self,
        event_id: UUID,
        error: str,
        retry_count: int,
        session: object | None = None,
    ) -> None:
        """Mark event as failed (terminal state)."""

        if event_id in self.events:
            event = self.events[event_id]
            self.events[event_id] = replace(
                event,
                status=OutboxEventStatus.FAILED,
                retry_count=retry_count,
                last_error=error,
            )

    async def mark_for_retry(
        self,
        event_id: UUID,
        error: str,
        retry_count: int,
        session: object | None = None,
    ) -> None:
        """Reset event to PENDING for retry."""

        if event_id in self.events:
            event = self.events[event_id]
            self.events[event_id] = replace(
                event,
                status=OutboxEventStatus.PENDING,
                retry_count=retry_count,
                last_error=error,
            )

    async def get_by_id(
        self, event_id: UUID, session: object | None = None
    ) -> Optional[OutboxEvent]:
        """Get event by ID."""

        return self.events.get(event_id)

    async def delete_processed_events(
        self,
        retention_days: int,
        batch_size: int,
        session: object | None = None,
    ) -> int:
        """Delete PUBLISHED/FAILED events older than retention_days."""

        if retention_days <= 0:
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        to_delete: List[UUID] = []

        for event_id, event in self.events.items():
            if len(to_delete) >= batch_size:
                break
            is_published_old = (
                event.status == OutboxEventStatus.PUBLISHED
                and event.processed_at
                and event.processed_at < cutoff
            )
            is_failed_old = (
                event.status == OutboxEventStatus.FAILED
                and event.created_at < cutoff
            )
            if is_published_old or is_failed_old:
                to_delete.append(event_id)

        for event_id in to_delete:
            del self.events[event_id]
            self._claimed_at.pop(event_id, None)

        return len(to_delete)

    async def reset_stale_processing_events(
        self,
        stale_after_minutes: int = 15,
        session: object | None = None,
    ) -> int:
        """Reset stale PROCESSING events back to PENDING."""
        cutoff = datetime.now(timezone.utc) - timedelta(
            minutes=stale_after_minutes
        )
        reset_count = 0
        for event_id, event in list(self.events.items()):
            if event.status != OutboxEventStatus.PROCESSING:
                continue
            claimed = self._claimed_at.get(event_id)
            if claimed is not None and claimed < cutoff:
                self.events[event_id] = replace(
                    event, status=OutboxEventStatus.PENDING
                )
                self._claimed_at.pop(event_id, None)
                reset_count += 1
        return reset_count


@dataclass
class InMemoryComplaintRepository(ComplaintRepository):
    """In-memory implementation of complaint repository."""

    complaints: Dict[UUID, Complaint] = field(default_factory=dict)

    async def save(
        self, complaint: Complaint, session: object | None = None
    ) -> None:
        """Persist complaint."""

        self.complaints[complaint.complaint_id] = complaint

    async def get_by_id(
        self, complaint_id: UUID, session: object | None = None
    ) -> Optional[Complaint]:
        """Get complaint by ID."""

        return self.complaints.get(complaint_id)

    async def list_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> Iterable[Complaint]:
        """List complaints for a specific order."""

        return [
            complaint
            for complaint in self.complaints.values()
            if complaint.order_id == order_id
        ]

    async def list_by_reporter(
        self, reporter_id: UUID, session: object | None = None
    ) -> Iterable[Complaint]:
        """List complaints filed by a specific user."""

        return [
            complaint
            for complaint in self.complaints.values()
            if complaint.reporter_id == reporter_id
        ]

    async def exists(
        self, order_id: UUID, reporter_id: UUID, session: object | None = None
    ) -> bool:
        """Check if reporter already filed a complaint for this order."""

        return any(
            complaint.order_id == order_id
            and complaint.reporter_id == reporter_id
            for complaint in self.complaints.values()
        )

    async def list_by_status(
        self, status: ComplaintStatus, session: object | None = None
    ) -> Iterable[Complaint]:
        """List complaints by status."""

        return [
            complaint
            for complaint in self.complaints.values()
            if complaint.status == status
        ]


@dataclass
class InMemoryCountryRepository(CountryRepository):
    """In-memory implementation of country repository."""

    countries: Dict[str, Country] = field(default_factory=dict)

    async def list_enabled(
        self, session: object | None = None
    ) -> list[Country]:
        """List enabled countries."""
        return [c for c in self.countries.values() if c.enabled]

    async def get_by_code(
        self, code: str, session: object | None = None
    ) -> Optional[Country]:
        """Fetch country by code."""
        return self.countries.get(code)

    async def get_by_currency_code(
        self, currency_code: str, session: object | None = None
    ) -> Optional[Country]:
        """Fetch any enabled country with the given currency code."""
        for country in self.countries.values():
            if country.enabled and country.currency_code == currency_code:
                return country
        return None


@dataclass
class MemoryLanguageRepository(LanguageRepository):
    """In-memory LanguageRepository for testing."""

    languages: Dict[str, Language] = field(default_factory=dict)

    async def list_enabled(
        self, session: object | None = None
    ) -> list[Language]:
        """List enabled languages."""
        return [lang for lang in self.languages.values() if lang.enabled]

    async def get_by_code(
        self, code: str, session: object | None = None
    ) -> Optional[Language]:
        """Fetch language by code regardless of enabled status.

        This intentionally does not filter by enabled — validation uses
        existence, not enabled status (same as SqlAlchemyLanguageRepository).
        """
        return self.languages.get(code)


@dataclass
class InMemoryManagerOrderRepository(ManagerOrderRepository):
    """In-memory implementation of manager order repository."""

    _assignments: Dict[Tuple[UUID, UUID], ManagerOrder] = field(
        default_factory=dict
    )

    async def list_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> list[ManagerOrder]:
        """List manager assignments for an order."""
        return sorted(
            [
                mo
                for (uid, oid), mo in self._assignments.items()
                if oid == order_id
            ],
            key=lambda x: (x.created_at, x.user_id),
        )

    async def list_by_user(
        self, user_id: UUID, session: object | None = None
    ) -> list[ManagerOrder]:
        """List order assignments for a manager."""
        return sorted(
            [
                mo
                for (uid, oid), mo in self._assignments.items()
                if uid == user_id
            ],
            key=lambda x: x.created_at,
            reverse=True,
        )

    async def list_order_ids_by_user(
        self,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
        session: object | None = None,
    ) -> list[UUID]:
        """List order IDs assigned to a manager with pagination."""
        assignments = await self.list_by_user(user_id, session=session)
        return [mo.order_id for mo in assignments[offset : offset + limit]]

    async def count_by_user(
        self, user_id: UUID, session: object | None = None
    ) -> int:
        """Count orders assigned to a manager."""
        return sum(1 for (uid, _) in self._assignments if uid == user_id)

    async def save(
        self, manager_order: ManagerOrder, session: object | None = None
    ) -> None:
        """Persist manager-order assignment."""
        key = (manager_order.user_id, manager_order.order_id)
        self._assignments[key] = manager_order

    async def delete_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> None:
        """Delete all manager assignments for an order."""
        keys_to_delete = [
            key for key in self._assignments if key[1] == order_id
        ]
        for key in keys_to_delete:
            del self._assignments[key]

    async def exists_for_user(
        self, user_id: UUID, session: object | None = None
    ) -> bool:
        """Check if manager has any order assignments."""
        return any(uid == user_id for (uid, _) in self._assignments)

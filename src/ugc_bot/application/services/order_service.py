"""Service for order creation and validation."""

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from ugc_bot.application.errors import (
    OrderCreationError,
    OrderNotFoundError,
    UserNotFoundError,
)
from ugc_bot.application.geography import (
    get_geometry_queries_from_spec,
    parse_geography,
)
from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    CountryRepository,
    GeocoderPort,
    OrderRepository,
    TransactionManager,
    UserRepository,
)
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicy,
)
from ugc_bot.application.services.paid_item_service import (
    FinancialQuote,
    PaidItemService,
)
from ugc_bot.domain.entities import Order
from ugc_bot.domain.enums import OrderStatus, OrderType, UserStatus
from ugc_bot.infrastructure.db.session import with_optional_tx

logger = logging.getLogger(__name__)


def _validate_order_input(
    product_link: str,
    offer_text: str,
    price: float,
    barter_description: str | None,
    bloggers_needed: int,
    allowed_blogger_counts: frozenset[int],
    max_order_price: float,
) -> tuple[str, str, str | None]:
    """Validate order input. Returns (product_link, offer_text, barter_desc)."""
    product_link_clean = product_link.strip()
    if not product_link_clean:
        raise OrderCreationError("Product link is required.")

    offer_text_clean = offer_text.strip()
    if not offer_text_clean:
        raise OrderCreationError("Offer text is required.")

    barter_clean = (barter_description or "").strip() or None
    if price < 0:
        raise OrderCreationError("Price cannot be negative.")
    if price > max_order_price:
        raise OrderCreationError(
            f"Price exceeds maximum ({max_order_price:,.0f})."
        )
    if price <= 0 and not barter_clean:
        raise OrderCreationError("Price must be positive when no barter.")

    if bloggers_needed not in allowed_blogger_counts:
        raise OrderCreationError("Invalid bloggers count.")

    return product_link_clean, offer_text_clean, barter_clean


@dataclass(slots=True)
class OrderService:
    """Create advertiser orders with validation."""

    user_repo: UserRepository
    advertiser_repo: AdvertiserProfileRepository
    order_repo: OrderRepository
    allowed_blogger_counts: frozenset[int]
    max_order_price: float
    metrics_collector: Optional[Any] = None
    transaction_manager: TransactionManager | None = None
    geocoder: Optional[GeocoderPort] = None
    country_repo: Optional[CountryRepository] = None
    paid_item_service: PaidItemService | None = None

    async def _resolve_currency(
        self, country_code: Optional[str], session: object | None
    ) -> str:
        """Resolve currency code from user country, default to RUB."""
        if country_code and self.country_repo:
            country_obj = await self.country_repo.get_by_code(
                country_code, session=session
            )
            if country_obj:
                return country_obj.currency_code
        return "RUB"

    async def is_new_advertiser(self, advertiser_id: UUID) -> bool:
        """Return True when advertiser has no previous orders."""

        async def _run(session: object | None):
            return (
                await self.order_repo.count_by_advertiser(
                    advertiser_id, session=session
                )
                == 0
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def list_by_advertiser(self, advertiser_id: UUID) -> list[Order]:
        """List orders for advertiser."""

        async def _run(session: object | None):
            return list(
                await self.order_repo.list_by_advertiser(
                    advertiser_id, session=session
                )
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def get_order(self, order_id: UUID) -> Order | None:
        """Fetch order by id within a transaction boundary."""

        async def _run(session: object | None):
            return await self.order_repo.get_by_id(order_id, session=session)

        return await with_optional_tx(self.transaction_manager, _run)

    async def create_order(
        self,
        advertiser_id: UUID,
        order_type: OrderType,
        product_link: str,
        offer_text: str,
        barter_description: Optional[str],
        price: float,
        bloggers_needed: int,
        content_usage: Optional[str] = None,
        deadlines: Optional[str] = None,
        geography: Optional[str] = None,
        product_photo_file_id: Optional[str] = None,
    ) -> Order:
        """Legacy entry point; never implicitly opts into financial v1."""
        return await self._create_order(
            advertiser_id,
            order_type,
            product_link,
            offer_text,
            barter_description,
            price,
            bloggers_needed,
            content_usage,
            deadlines,
            geography,
            product_photo_file_id,
        )

    async def _create_order(
        self,
        advertiser_id: UUID,
        order_type: OrderType,
        product_link: str,
        offer_text: str,
        barter_description: Optional[str],
        price: float,
        bloggers_needed: int,
        content_usage: Optional[str] = None,
        deadlines: Optional[str] = None,
        geography: Optional[str] = None,
        product_photo_file_id: Optional[str] = None,
        *,
        _session: object | None = None,
        _financial_order_id: UUID | None = None,
        _created_at: datetime | None = None,
    ) -> Order:
        """Create an order after validating input."""

        async def _run(session: object | None) -> Order:
            user = await self.user_repo.get_by_id(
                advertiser_id, session=session
            )
            if user is None:
                raise UserNotFoundError("Advertiser not found.")

            advertiser_profile = await self.advertiser_repo.get_by_user_id(
                advertiser_id, session=session
            )
            if advertiser_profile is None:
                raise OrderCreationError("Advertiser profile is not set.")

            if user.status == UserStatus.BLOCKED:
                raise OrderCreationError("Blocked users cannot create orders.")
            if user.status == UserStatus.PAUSE:
                raise OrderCreationError("Paused users cannot create orders.")

            product_link_clean, offer_text_clean, barter_description_clean = (
                _validate_order_input(
                    product_link,
                    offer_text,
                    price,
                    barter_description,
                    bloggers_needed,
                    self.allowed_blogger_counts
                    | ({30} if _financial_order_id else set()),
                    self.max_order_price,
                )
            )

            order_currency = await self._resolve_currency(user.country, session)

            geography_clean = (geography or "").strip() or None
            order_location_geometry = None
            if geography_clean and self.geocoder:
                spec = parse_geography(geography_clean)
                if spec is not None:
                    queries = get_geometry_queries_from_spec(spec)
                    if queries:
                        geocoder = self.geocoder
                        order_location_geometry = (
                            await geocoder.get_multipolygon_wkt_for_queries(
                                queries
                            )
                        )
            order = Order(
                order_id=_financial_order_id or uuid4(),
                advertiser_id=advertiser_id,
                order_type=order_type,
                product_link=product_link_clean,
                offer_text=offer_text_clean,
                barter_description=barter_description_clean,
                price=price,
                bloggers_needed=bloggers_needed,
                status=OrderStatus.NEW,
                created_at=_created_at or datetime.now(timezone.utc),
                completed_at=None,
                content_usage=(content_usage or "").strip() or None,
                deadlines=(deadlines or "").strip() or None,
                geography=geography_clean,
                product_photo_file_id=(
                    (product_photo_file_id or "").strip() or None
                ),
                min_followers=None,
                max_followers=None,
                min_age=None,
                max_age=None,
                min_publications=None,
                max_publications=None,
                required_blogger_gender=None,
                filter_by_price=False,
                price_filter_delta=None,
                filter_by_placement=False,
                filter_by_barter=False,
                location_geometry=order_location_geometry,
                currency=order_currency,
            )
            await self.order_repo.save(order, session=session)

            logger.info(
                "Order created",
                extra={
                    "order_id": str(order.order_id),
                    "advertiser_id": str(order.advertiser_id),
                    "price": float(order.price),
                    "bloggers_needed": order.bloggers_needed,
                    "event_type": "order.created",
                },
            )

            if self.metrics_collector and _financial_order_id is None:
                self.metrics_collector.record_order_created(
                    order_id=str(order.order_id),
                    advertiser_id=str(order.advertiser_id),
                    price=float(order.price),
                    bloggers_needed=order.bloggers_needed,
                )

            return order

        return (
            await _run(_session)
            if _session is not None
            else await with_optional_tx(self.transaction_manager, _run)
        )

    async def create_financial_order(
        self,
        *,
        order_id: UUID,
        advertiser_id: UUID,
        order_type: OrderType,
        product_link: str,
        offer_text: str,
        barter_description: str | None,
        price: float,
        policy: FinancialPolicy | None,
        order_created_at: datetime,
        now: datetime,
        selection_due_at: datetime | None,
        currency: str,
        accompaniment_ordinals: frozenset[int],
        client_contact_reference: str,
        idempotency_key: str,
        session: object | None = None,
    ) -> tuple[Order, FinancialQuote]:
        """Explicit opt-in: validate first, commit order and quote together.

        The order UUID is the caller's stable command identity. No notification,
        referral income is emitted for an unpaid quote. The caller may persist
        a separately requested unpaid accompaniment lead in the same session.
        """
        if self.paid_item_service is None or (
            self.transaction_manager is None and session is None
        ):
            raise ValueError("financial_service_and_transaction_required")
        paid = self.paid_item_service
        quote = paid.prepare_quote(
            policy=policy,
            client_id=advertiser_id,
            order_created_at=order_created_at,
            selection_due_at=selection_due_at,
            currency=currency,
            now=now,
            order_id=order_id,
            accompaniment_ordinals=accompaniment_ordinals,
            client_contact_reference=client_contact_reference,
            idempotency_key=idempotency_key,
        )
        clean_link, clean_offer, clean_barter = _validate_order_input(
            product_link,
            offer_text,
            price,
            barter_description,
            30,
            self.allowed_blogger_counts | {30},
            self.max_order_price,
        )

        async def _run(session: object) -> tuple[Order, FinancialQuote]:
            await paid.repository.lock_order(order_id, session=session)
            existing = await self.order_repo.get_by_id(
                order_id, session=session
            )
            if existing is not None:
                if (
                    existing.advertiser_id,
                    existing.order_type,
                    existing.product_link,
                    existing.offer_text,
                    existing.barter_description,
                    existing.price,
                    existing.bloggers_needed,
                    existing.currency,
                    existing.created_at,
                ) != (
                    advertiser_id,
                    order_type,
                    clean_link,
                    clean_offer,
                    clean_barter,
                    price,
                    30,
                    currency,
                    order_created_at,
                ):
                    raise ValueError("idempotency_payload_conflict")
                # Repository refuses legacy orders; never auto-activate them.
                saved = await paid.repository.save_quote(quote, session=session)
                return existing, saved
            user = await self.user_repo.get_by_id(
                advertiser_id, session=session
            )
            if user is None:
                raise UserNotFoundError("Advertiser not found.")
            if await self._resolve_currency(user.country, session) != currency:
                raise ValueError("unpublished_currency")
            await self._create_order(
                advertiser_id=advertiser_id,
                order_type=order_type,
                product_link=clean_link,
                offer_text=clean_offer,
                barter_description=clean_barter,
                price=price,
                bloggers_needed=30,
                _session=session,
                _financial_order_id=order_id,
                _created_at=order_created_at,
            )
            await paid.repository.activate_new_order(
                order_id, quote.policy_version, session=session
            )
            saved = await paid.repository.save_quote(quote, session=session)
            persisted = await self.order_repo.get_by_id(
                order_id, session=session
            )
            assert persisted is not None
            return persisted, saved

        if session is not None:
            return await _run(session)
        assert self.transaction_manager is not None
        async with self.transaction_manager.transaction() as owned_session:
            return await _run(owned_session)

    _EDITABLE_ORDER_STATUSES = frozenset(
        {OrderStatus.NEW, OrderStatus.PENDING_MODERATION}
    )

    async def update_order(
        self,
        order_id: UUID,
        advertiser_id: UUID,
        product_link: str,
        offer_text: str,
        barter_description: Optional[str],
        price: float,
        bloggers_needed: int,
        order_type: OrderType,
        content_usage: Optional[str] = None,
        deadlines: Optional[str] = None,
        geography: Optional[str] = None,
    ) -> Order:
        """Update order if it belongs to advertiser and status allows edit."""

        async def _run(session: object | None) -> Order:
            order = await self.order_repo.get_by_id(order_id, session=session)
            if order is None:
                raise OrderNotFoundError("Order not found.")
            if order.advertiser_id != advertiser_id:
                raise OrderNotFoundError("Order not found.")
            if order.status not in self._EDITABLE_ORDER_STATUSES:
                raise OrderCreationError(
                    "Order cannot be edited in current status."
                )
            product_link_clean, offer_text_clean, barter_clean = (
                _validate_order_input(
                    product_link,
                    offer_text,
                    price,
                    barter_description,
                    bloggers_needed,
                    self.allowed_blogger_counts,
                    self.max_order_price,
                )
            )
            geography_clean = (geography or "").strip() or None
            order_location_geometry = order.location_geometry
            if geography_clean and self.geocoder:
                spec = parse_geography(geography_clean)
                if spec is not None:
                    queries = get_geometry_queries_from_spec(spec)
                    if queries:
                        geocoder = self.geocoder
                        order_location_geometry = (
                            await geocoder.get_multipolygon_wkt_for_queries(
                                queries
                            )
                        )
            updated = replace(
                order,
                product_link=product_link_clean,
                offer_text=offer_text_clean,
                barter_description=barter_clean,
                price=price,
                bloggers_needed=bloggers_needed,
                order_type=order_type,
                content_usage=(content_usage or "").strip() or None,
                deadlines=(deadlines or "").strip() or None,
                geography=geography_clean,
                location_geometry=order_location_geometry,
            )
            await self.order_repo.save(updated, session=session)
            return updated

        return await with_optional_tx(self.transaction_manager, _run)

"""SQLAlchemy order, payment, and contact pricing repositories."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ugc_bot.application.ports import (
    ContactPricingRepository,
    OrderRepository,
    PaymentRepository,
)
from ugc_bot.domain.entities import ContactPricing, Order, Payment
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.infrastructure.db.models import (
    ContactPricingModel,
    OrderModel,
    PaymentModel,
)
from ugc_bot.infrastructure.db.repositories._shared import (
    _geometry_to_wkt,
    _resolve_session,
    _wkt_to_geometry_element,
)


@dataclass(slots=True)
class SqlAlchemyOrderRepository(OrderRepository):
    """SQLAlchemy-backed order repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get_by_id(
        self,
        order_id: UUID,
        session: object | None = None,
        *,
        for_update: bool = False,
    ) -> Optional[Order]:
        """Fetch order, optionally locking in the caller's write transaction."""
        if for_update:
            if not isinstance(session, AsyncSession):
                raise ValueError("A row lock requires an explicit transaction")
            return await self.get_by_id_for_update(order_id, session=session)
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(OrderModel).where(OrderModel.order_id == order_id)
            )
            result = exec_result.scalar_one_or_none()
            return _to_order_entity(result) if result else None

    async def get_by_ids(
        self,
        order_ids: list[UUID],
        session: object | None = None,
    ) -> list[Order]:
        """Fetch orders by IDs in a single query."""
        if not order_ids:
            return []
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(OrderModel).where(OrderModel.order_id.in_(order_ids))
            )
            by_id = {
                m.order_id: _to_order_entity(m) for m in exec_result.scalars()
            }
            return [by_id[oid] for oid in order_ids if oid in by_id]

    async def get_by_id_for_update(
        self, order_id: UUID, session: object | None = None
    ) -> Optional[Order]:
        """Fetch order by ID with row lock."""
        stmt = (
            select(OrderModel)
            .where(OrderModel.order_id == order_id)
            .with_for_update()
        )
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(stmt)
            result = exec_result.scalar_one_or_none()
            return _to_order_entity(result) if result else None

    async def list_active(
        self, session: object | None = None
    ) -> Iterable[Order]:
        """List active orders."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(OrderModel).where(
                    OrderModel.status == OrderStatus.ACTIVE
                )
            )
            result = exec_result.scalars()
            return [_to_order_entity(item) for item in result]

    async def list_by_advertiser(
        self, advertiser_id: UUID, session: object | None = None
    ) -> Iterable[Order]:
        """List orders by advertiser."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(OrderModel).where(
                    OrderModel.advertiser_id == advertiser_id
                )
            )
            result = exec_result.scalars()
            return [_to_order_entity(item) for item in result]

    async def list_completed_before(
        self, cutoff: datetime, session: object | None = None
    ) -> Iterable[Order]:
        """List orders completed before cutoff."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(OrderModel).where(
                    OrderModel.completed_at.is_not(None),
                    OrderModel.completed_at <= cutoff,
                )
            )
            result = exec_result.scalars()
            return [_to_order_entity(item) for item in result]

    async def count_by_advertiser(
        self, advertiser_id: UUID, session: object | None = None
    ) -> int:
        """Count orders by advertiser."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(func.count())
                .select_from(OrderModel)
                .where(OrderModel.advertiser_id == advertiser_id)
            )
            result = exec_result.scalar_one()
            return int(result)

    async def list_all_paginated(
        self,
        limit: int = 20,
        offset: int = 0,
        session: object | None = None,
    ) -> list[Order]:
        """List all orders with pagination, newest first."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(OrderModel)
                .order_by(OrderModel.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return [_to_order_entity(m) for m in exec_result.scalars()]

    async def count_all(self, session: object | None = None) -> int:
        """Count all orders."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(func.count()).select_from(OrderModel)
            )
            return int(exec_result.scalar_one())

    async def save(self, order: Order, session: object | None = None) -> None:
        """Persist order."""
        model = _to_order_model(order)
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            await db_session.merge(model)


@dataclass(slots=True)
class SqlAlchemyPaymentRepository(PaymentRepository):
    """SQLAlchemy-backed payment repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> Optional[Payment]:
        """Fetch payment by order id."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(PaymentModel).where(PaymentModel.order_id == order_id)
            )
            result = exec_result.scalar_one_or_none()
            return _to_payment_entity(result) if result else None

    async def get_by_external_id(
        self, external_id: str, session: object | None = None
    ) -> Optional[Payment]:
        """Fetch payment by provider external id."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(PaymentModel).where(
                    PaymentModel.external_id == external_id
                )
            )
            result = exec_result.scalar_one_or_none()
            return _to_payment_entity(result) if result else None

    async def save(
        self, payment: Payment, session: object | None = None
    ) -> None:
        """Persist payment."""
        model = _to_payment_model(payment)
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            await db_session.merge(model)


@dataclass(slots=True)
class SqlAlchemyContactPricingRepository(ContactPricingRepository):
    """SQLAlchemy-backed contact pricing repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get_by_bloggers_count(
        self,
        bloggers_count: int,
        country_code: str = "ru",
        session: object | None = None,
    ) -> Optional[ContactPricing]:
        """Fetch pricing by bloggers count and country."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(ContactPricingModel).where(
                    ContactPricingModel.country_code == country_code,
                    ContactPricingModel.bloggers_count == bloggers_count,
                )
            )
            result = exec_result.scalar_one_or_none()
            return _to_contact_pricing_entity(result) if result else None


def _to_order_entity(model: OrderModel) -> Order:
    """Map order ORM model to domain entity."""
    return Order(
        order_id=model.order_id,
        advertiser_id=model.advertiser_id,
        order_type=model.order_type,
        product_link=model.product_link,
        offer_text=model.offer_text,
        barter_description=model.barter_description,
        price=float(model.price),
        bloggers_needed=model.bloggers_needed,
        status=model.status,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
        content_usage=model.content_usage,
        deadlines=model.deadlines,
        geography=model.geography,
        product_photo_file_id=model.product_photo_file_id,
        min_followers=model.min_followers,
        max_followers=model.max_followers,
        min_age=model.min_age,
        max_age=model.max_age,
        min_publications=model.min_publications,
        max_publications=model.max_publications,
        min_rating=(
            float(model.min_rating) if model.min_rating is not None else None
        ),
        required_blogger_gender=model.required_blogger_gender,
        filter_by_price=model.filter_by_price,
        price_filter_delta=(
            float(model.price_filter_delta)
            if model.price_filter_delta is not None
            else None
        ),
        filter_by_placement=model.filter_by_placement,
        filter_by_barter=model.filter_by_barter,
        location_geometry=_geometry_to_wkt(model.location_geometry),
        currency=model.currency,
        last_round_robin_index=model.last_round_robin_index,
        brief_link=model.brief_link,
    )


def _to_order_model(order: Order) -> OrderModel:
    """Map domain order entity to ORM model."""
    return OrderModel(
        order_id=order.order_id,
        advertiser_id=order.advertiser_id,
        order_type=order.order_type,
        product_link=order.product_link,
        offer_text=order.offer_text,
        barter_description=order.barter_description,
        price=order.price,
        bloggers_needed=order.bloggers_needed,
        status=order.status,
        created_at=order.created_at,
        updated_at=order.updated_at or order.created_at,
        completed_at=order.completed_at,
        content_usage=order.content_usage,
        deadlines=order.deadlines,
        geography=order.geography,
        product_photo_file_id=order.product_photo_file_id,
        min_followers=order.min_followers,
        max_followers=order.max_followers,
        min_age=order.min_age,
        max_age=order.max_age,
        min_publications=order.min_publications,
        max_publications=order.max_publications,
        min_rating=order.min_rating,
        required_blogger_gender=order.required_blogger_gender,
        filter_by_price=order.filter_by_price,
        price_filter_delta=order.price_filter_delta,
        filter_by_placement=order.filter_by_placement,
        filter_by_barter=order.filter_by_barter,
        location_geometry=_wkt_to_geometry_element(order.location_geometry),
        currency=order.currency,
        last_round_robin_index=order.last_round_robin_index,
        brief_link=order.brief_link,
    )


def _to_payment_entity(model: PaymentModel) -> Payment:
    """Map payment ORM model to domain entity."""
    return Payment(
        payment_id=model.payment_id,
        order_id=model.order_id,
        provider=model.provider,
        status=model.status,
        amount=float(model.amount),
        currency=model.currency,
        external_id=model.external_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        paid_at=model.paid_at,
    )


def _to_payment_model(payment: Payment) -> PaymentModel:
    """Map domain payment entity to ORM model."""
    return PaymentModel(
        payment_id=payment.payment_id,
        order_id=payment.order_id,
        provider=payment.provider,
        status=payment.status,
        amount=payment.amount,
        currency=payment.currency,
        external_id=payment.external_id,
        created_at=payment.created_at,
        updated_at=payment.updated_at or payment.created_at,
        paid_at=payment.paid_at,
    )


def _to_contact_pricing_entity(model: ContactPricingModel) -> ContactPricing:
    """Map contact pricing ORM model to entity."""
    return ContactPricing(
        country_code=model.country_code,
        bloggers_count=model.bloggers_count,
        price=model.price,
        currency=model.currency,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )

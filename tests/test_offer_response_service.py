"""Tests for offer response service."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.services.offer_response_service import OfferResponseService
from ugc_bot.domain.entities import Order
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryOrderRepository,
    InMemoryOrderResponseRepository,
)


def test_offer_response_success() -> None:
    """Create response for active order."""

    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    service = OfferResponseService(order_repo=order_repo, response_repo=response_repo)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000800"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000801"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    order_repo.save(order)

    response = service.respond(
        order_id=order.order_id,
        blogger_id=UUID("00000000-0000-0000-0000-000000000802"),
    )
    assert response.order_id == order.order_id


def test_offer_response_limit() -> None:
    """Prevent responses above limit."""

    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    service = OfferResponseService(order_repo=order_repo, response_repo=response_repo)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000810"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000811"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    order_repo.save(order)
    service.respond(
        order_id=order.order_id,
        blogger_id=UUID("00000000-0000-0000-0000-000000000812"),
    )

    with pytest.raises(OrderCreationError):
        service.respond(
            order_id=order.order_id,
            blogger_id=UUID("00000000-0000-0000-0000-000000000813"),
        )


def test_offer_response_order_not_found() -> None:
    """Fail when order is missing."""

    service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        response_repo=InMemoryOrderResponseRepository(),
    )

    with pytest.raises(OrderCreationError):
        service.respond(
            order_id=UUID("00000000-0000-0000-0000-000000000820"),
            blogger_id=UUID("00000000-0000-0000-0000-000000000821"),
        )


def test_offer_response_requires_active_order() -> None:
    """Fail when order is not active."""

    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    service = OfferResponseService(order_repo=order_repo, response_repo=response_repo)

    order_repo.save(
        Order(
            order_id=UUID("00000000-0000-0000-0000-000000000830"),
            advertiser_id=UUID("00000000-0000-0000-0000-000000000831"),
            product_link="https://example.com",
            offer_text="Offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=1,
            status=OrderStatus.NEW,
            created_at=datetime.now(timezone.utc),
            contacts_sent_at=None,
        )
    )

    with pytest.raises(OrderCreationError):
        service.respond(
            order_id=UUID("00000000-0000-0000-0000-000000000830"),
            blogger_id=UUID("00000000-0000-0000-0000-000000000832"),
        )

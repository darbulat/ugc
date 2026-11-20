"""Intake has one durable deadline and preserves existing selections."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from ugc_bot.application.errors import OrderNotActiveError
from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
)
from ugc_bot.application.services.offer_response_service import (
    OfferResponseService,
)
from ugc_bot.domain.entities import Order
from ugc_bot.domain.enums import OrderStatus, OrderType, RejectionReason
from ugc_bot.domain.offer_intake import RESERVE_WINDOW, intake_open
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryInteractionRepository,
    InMemoryOfferDispatchRepository,
    InMemoryOrderRepository,
    InMemoryOutboxRepository,
    InMemoryUserRepository,
)


@pytest.mark.parametrize("status", [OrderStatus.ACTIVE, OrderStatus.CLOSED])
def test_intake_boundary_and_manual_stop(status):
    at = datetime.now(timezone.utc)
    assert intake_open(status, False, at, now=at - timedelta(microseconds=1))
    assert not intake_open(status, False, at, now=at)
    assert not intake_open(status, False, at, now=at + timedelta(seconds=1))
    assert not intake_open(status, True, at + RESERVE_WINDOW, now=at)
    assert not intake_open(
        OrderStatus.DELETED, False, at + RESERVE_WINDOW, now=at
    )
    assert not intake_open(OrderStatus.NEW, False, at + RESERVE_WINDOW, now=at)
    assert intake_open(status, False, None, now=at) == (
        status == OrderStatus.ACTIVE
    )


@pytest.mark.asyncio
async def test_legacy_deadline_survives_rebuild_and_never_extends(
    fake_tm,
):
    orders, offers = (
        InMemoryOrderRepository(),
        InMemoryOfferDispatchRepository(),
    )
    now = datetime.now(timezone.utc)
    order = Order(
        uuid4(),
        uuid4(),
        OrderType.UGC_ONLY,
        "test",
        "Offer",
        None,
        500,
        2,
        OrderStatus.ACTIVE,
        now,
    )
    await orders.save(order)
    creators = [uuid4() for _ in range(5)]
    for creator in creators:
        await offers.record_sent(order.order_id, creator)

    def service():
        return OfferResponseService(orders, offers, transaction_manager=fake_tm)

    first = await service().respond_and_finalize(order.order_id, creators[0])
    assert first.order.offer_reserve_until is None
    filled = await service().respond_and_finalize(order.order_id, creators[1])
    deadline = filled.order.offer_reserve_until
    assert deadline == filled.completed_at + RESERVE_WINDOW
    assert filled.order.status == OrderStatus.CLOSED
    reserve = await service().respond_and_finalize(order.order_id, creators[2])
    assert not reserve.accepted and not reserve.response.in_offer
    assert reserve.order.offer_reserve_until == deadline
    assert await offers.count_accepted_by_order(order.order_id) == 2
    # A later vacancy does not restart the reserve window.
    await offers.record_response(order.order_id, creators[0], False, False)
    replacement = await service().respond_and_finalize(
        order.order_id, creators[3]
    )
    assert replacement.accepted
    assert replacement.order.offer_reserve_until == deadline
    await orders.save(replace(replacement.order, offer_reserve_until=now))
    with pytest.raises(OrderNotActiveError):
        await service().respond_and_finalize(order.order_id, creators[4])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "problem", ["expired", "historical", "manual", "deleted"]
)
async def test_closed_intake_cannot_record_prices_or_refusals(problem):
    now = datetime.now(timezone.utc)
    order = Order(
        uuid4(),
        uuid4(),
        OrderType.UGC_ONLY,
        "test",
        "Offer",
        None,
        500,
        1,
        OrderStatus.CLOSED,
        now,
        offer_reserve_until=now + RESERVE_WINDOW,
    )
    if problem == "expired":
        order = replace(order, offer_reserve_until=now)
    elif problem == "historical":
        order = replace(order, offer_reserve_until=None)
    elif problem == "manual":
        order = replace(order, dispatch_stopped=True)
    else:
        order = replace(order, status=OrderStatus.DELETED)
    orders, offers = (
        InMemoryOrderRepository(),
        InMemoryOfferDispatchRepository(),
    )
    outbox, creator = InMemoryOutboxRepository(), uuid4()
    await orders.save(order)
    await offers.record_sent(order.order_id, creator)
    service = OfferDispatchService(
        InMemoryUserRepository(),
        InMemoryBloggerProfileRepository(),
        orders,
        offers,
        InMemoryInteractionRepository(),
        outbox_repo=outbox,
    )
    assert not await service.is_intake_open(order.order_id)
    assert await service.get_order_price_bounds(order.order_id) is None
    price = await service.record_skip(
        order.order_id, creator, RejectionReason.LOW_PRICE, Decimal(5000)
    )
    skip = await service.record_skip(
        order.order_id, creator, RejectionReason.NO_TIME
    )
    assert price.intake_closed and skip.intake_closed
    assert not await offers.exists_responded(order.order_id, creator)
    assert await outbox.get_pending_events() == []

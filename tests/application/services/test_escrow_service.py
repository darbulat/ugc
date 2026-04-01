"""Tests for escrow service."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from tests.conftest import fake_transaction_manager
from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.services.escrow_service import EscrowService
from ugc_bot.domain.entities import Order, Payment
from ugc_bot.domain.enums import (
    EscrowStatus,
    OrderStatus,
    OrderType,
    PaymentStatus,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryEscrowHoldRepository,
)


@pytest.fixture
def escrow_repo() -> InMemoryEscrowHoldRepository:
    return InMemoryEscrowHoldRepository()


@pytest.fixture
def escrow_service(escrow_repo: InMemoryEscrowHoldRepository) -> EscrowService:
    return EscrowService(
        escrow_repo=escrow_repo,
        transaction_manager=fake_transaction_manager(),
    )


def _make_payment(order_id=None) -> Payment:
    return Payment(
        payment_id=uuid4(),
        order_id=order_id or uuid4(),
        provider="yookassa_telegram",
        status=PaymentStatus.PAID,
        amount=3000.0,
        currency="RUB",
        external_id="ext_1",
        created_at=datetime.now(timezone.utc),
    )


def _make_order(advertiser_id=None, price=1000.0, bloggers_needed=3) -> Order:
    return Order(
        order_id=uuid4(),
        advertiser_id=advertiser_id or uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Test",
        barter_description=None,
        price=price,
        bloggers_needed=bloggers_needed,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
    )


# --- create_holds_for_order ---


@pytest.mark.asyncio
async def test_create_holds_for_order(
    escrow_service: EscrowService,
    escrow_repo: InMemoryEscrowHoldRepository,
) -> None:
    order = _make_order(bloggers_needed=3, price=500.0)
    payment = _make_payment(order_id=order.order_id)

    holds = await escrow_service.create_holds_for_order(payment, order)

    assert len(holds) == 3
    for hold in holds:
        assert hold.status == EscrowStatus.HELD
        assert hold.amount == Decimal("500.0")
        assert hold.currency == "RUB"
        assert hold.payment_id == payment.payment_id
        assert hold.order_id == order.order_id
        assert hold.interaction_id is None
    assert len(escrow_repo.holds) == 3


@pytest.mark.asyncio
async def test_create_holds_single_blogger(
    escrow_service: EscrowService,
    escrow_repo: InMemoryEscrowHoldRepository,
) -> None:
    order = _make_order(bloggers_needed=1, price=2000.0)
    payment = _make_payment(order_id=order.order_id)

    holds = await escrow_service.create_holds_for_order(payment, order)

    assert len(holds) == 1
    assert holds[0].amount == Decimal("2000.0")


# --- assign_interaction ---


@pytest.mark.asyncio
async def test_assign_interaction(
    escrow_service: EscrowService,
    escrow_repo: InMemoryEscrowHoldRepository,
) -> None:
    order = _make_order(bloggers_needed=2)
    payment = _make_payment(order_id=order.order_id)
    await escrow_service.create_holds_for_order(payment, order)

    blogger_id = uuid4()
    interaction_id = uuid4()
    result = await escrow_service.assign_interaction(
        order.order_id, blogger_id, interaction_id
    )

    assert result is not None
    assert result.interaction_id == interaction_id
    assert result.blogger_id == blogger_id
    assert result.status == EscrowStatus.HELD


@pytest.mark.asyncio
async def test_assign_interaction_no_unassigned(
    escrow_service: EscrowService,
) -> None:
    result = await escrow_service.assign_interaction(uuid4(), uuid4(), uuid4())
    assert result is None


# --- release_hold ---


@pytest.mark.asyncio
async def test_release_hold(
    escrow_service: EscrowService,
    escrow_repo: InMemoryEscrowHoldRepository,
) -> None:
    order = _make_order(bloggers_needed=1)
    payment = _make_payment(order_id=order.order_id)
    await escrow_service.create_holds_for_order(payment, order)
    interaction_id = uuid4()
    await escrow_service.assign_interaction(
        order.order_id, uuid4(), interaction_id
    )

    result = await escrow_service.release_hold(interaction_id)

    assert result is not None
    assert result.status == EscrowStatus.RELEASED
    assert result.released_at is not None


@pytest.mark.asyncio
async def test_release_hold_not_found(
    escrow_service: EscrowService,
) -> None:
    result = await escrow_service.release_hold(uuid4())
    assert result is None


# --- dispute_hold ---


@pytest.mark.asyncio
async def test_dispute_hold(
    escrow_service: EscrowService,
    escrow_repo: InMemoryEscrowHoldRepository,
) -> None:
    order = _make_order(bloggers_needed=1)
    payment = _make_payment(order_id=order.order_id)
    await escrow_service.create_holds_for_order(payment, order)
    interaction_id = uuid4()
    await escrow_service.assign_interaction(
        order.order_id, uuid4(), interaction_id
    )

    result = await escrow_service.dispute_hold(interaction_id)

    assert result is not None
    assert result.status == EscrowStatus.DISPUTED


# --- refund_hold ---


@pytest.mark.asyncio
async def test_refund_hold(
    escrow_service: EscrowService,
    escrow_repo: InMemoryEscrowHoldRepository,
) -> None:
    order = _make_order(bloggers_needed=1)
    payment = _make_payment(order_id=order.order_id)
    holds = await escrow_service.create_holds_for_order(payment, order)

    result = await escrow_service.refund_hold(holds[0].escrow_id)

    assert result is not None
    assert result.status == EscrowStatus.REFUNDED
    assert result.refunded_at is not None


@pytest.mark.asyncio
async def test_refund_hold_by_interaction(
    escrow_service: EscrowService,
    escrow_repo: InMemoryEscrowHoldRepository,
) -> None:
    order = _make_order(bloggers_needed=1)
    payment = _make_payment(order_id=order.order_id)
    await escrow_service.create_holds_for_order(payment, order)
    interaction_id = uuid4()
    await escrow_service.assign_interaction(
        order.order_id, uuid4(), interaction_id
    )

    result = await escrow_service.refund_hold_by_interaction(interaction_id)

    assert result is not None
    assert result.status == EscrowStatus.REFUNDED


# --- cancel_hold ---


@pytest.mark.asyncio
async def test_cancel_hold_by_interaction(
    escrow_service: EscrowService,
    escrow_repo: InMemoryEscrowHoldRepository,
) -> None:
    order = _make_order(bloggers_needed=1)
    payment = _make_payment(order_id=order.order_id)
    await escrow_service.create_holds_for_order(payment, order)
    interaction_id = uuid4()
    await escrow_service.assign_interaction(
        order.order_id, uuid4(), interaction_id
    )

    result = await escrow_service.cancel_hold_by_interaction(interaction_id)

    assert result is not None
    assert result.status == EscrowStatus.CANCELLED


# --- invalid transitions ---


@pytest.mark.asyncio
async def test_release_already_refunded_raises(
    escrow_service: EscrowService,
    escrow_repo: InMemoryEscrowHoldRepository,
) -> None:
    order = _make_order(bloggers_needed=1)
    payment = _make_payment(order_id=order.order_id)
    await escrow_service.create_holds_for_order(payment, order)
    interaction_id = uuid4()
    await escrow_service.assign_interaction(
        order.order_id, uuid4(), interaction_id
    )
    await escrow_service.refund_hold_by_interaction(interaction_id)

    with pytest.raises(OrderCreationError, match="Invalid escrow transition"):
        await escrow_service.release_hold(interaction_id)


@pytest.mark.asyncio
async def test_dispute_already_released_raises(
    escrow_service: EscrowService,
    escrow_repo: InMemoryEscrowHoldRepository,
) -> None:
    order = _make_order(bloggers_needed=1)
    payment = _make_payment(order_id=order.order_id)
    await escrow_service.create_holds_for_order(payment, order)
    interaction_id = uuid4()
    await escrow_service.assign_interaction(
        order.order_id, uuid4(), interaction_id
    )
    await escrow_service.release_hold(interaction_id)

    with pytest.raises(OrderCreationError, match="Invalid escrow transition"):
        await escrow_service.dispute_hold(interaction_id)


# --- admin force operations ---


@pytest.mark.asyncio
async def test_admin_force_release_from_disputed(
    escrow_service: EscrowService,
    escrow_repo: InMemoryEscrowHoldRepository,
) -> None:
    order = _make_order(bloggers_needed=1)
    payment = _make_payment(order_id=order.order_id)
    await escrow_service.create_holds_for_order(payment, order)
    interaction_id = uuid4()
    await escrow_service.assign_interaction(
        order.order_id, uuid4(), interaction_id
    )
    await escrow_service.dispute_hold(interaction_id)

    hold = await escrow_repo.get_by_interaction(interaction_id)
    assert hold is not None
    result = await escrow_service.admin_force_release(hold.escrow_id)

    assert result is not None
    assert result.status == EscrowStatus.RELEASED
    assert result.released_at is not None


@pytest.mark.asyncio
async def test_admin_force_refund_from_disputed(
    escrow_service: EscrowService,
    escrow_repo: InMemoryEscrowHoldRepository,
) -> None:
    order = _make_order(bloggers_needed=1)
    payment = _make_payment(order_id=order.order_id)
    await escrow_service.create_holds_for_order(payment, order)
    interaction_id = uuid4()
    await escrow_service.assign_interaction(
        order.order_id, uuid4(), interaction_id
    )
    await escrow_service.dispute_hold(interaction_id)

    hold = await escrow_repo.get_by_interaction(interaction_id)
    assert hold is not None
    result = await escrow_service.admin_force_refund(hold.escrow_id)

    assert result is not None
    assert result.status == EscrowStatus.REFUNDED
    assert result.refunded_at is not None


# --- list operations ---


@pytest.mark.asyncio
async def test_list_by_order(
    escrow_service: EscrowService,
    escrow_repo: InMemoryEscrowHoldRepository,
) -> None:
    order = _make_order(bloggers_needed=3)
    payment = _make_payment(order_id=order.order_id)
    await escrow_service.create_holds_for_order(payment, order)

    holds = await escrow_repo.list_by_order(order.order_id)
    assert len(holds) == 3


@pytest.mark.asyncio
async def test_list_by_payment(
    escrow_service: EscrowService,
    escrow_repo: InMemoryEscrowHoldRepository,
) -> None:
    order = _make_order(bloggers_needed=2)
    payment = _make_payment(order_id=order.order_id)
    await escrow_service.create_holds_for_order(payment, order)

    holds = await escrow_repo.list_by_payment(payment.payment_id)
    assert len(holds) == 2

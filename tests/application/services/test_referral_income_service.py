"""Tests for ReferralIncomeService."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from ugc_bot.application.services.referral_income_service import (
    ReferralIncomeService,
    UserReferralStats,
)
from ugc_bot.domain.entities import (
    Interaction,
    Order,
    OrderResponse,
    Payment,
    PayoutRequest,
    User,
    UserReferralBinding,
)
from ugc_bot.domain.enums import (
    InteractionStatus,
    MessengerType,
    OrderStatus,
    OrderType,
    PaymentStatus,
    PayoutRequestStatus,
    UserStatus,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryInteractionRepository,
    InMemoryOrderRepository,
    InMemoryOrderResponseRepository,
    InMemoryPaymentRepository,
    InMemoryPayoutRequestRepository,
    InMemoryUserReferralBindingRepository,
    InMemoryUserRepository,
)


@pytest.mark.asyncio
async def test_get_user_referral_stats_empty_returns_zeros() -> None:
    """get_user_referral_stats returns zeros when user has no referrals."""
    binding_repo = InMemoryUserReferralBindingRepository()
    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    order_response_repo = InMemoryOrderResponseRepository()
    payment_repo = InMemoryPaymentRepository()
    interaction_repo = InMemoryInteractionRepository()

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        order_response_repo=order_response_repo,
        order_repo=order_repo,
        payment_repo=payment_repo,
        interaction_repo=interaction_repo,
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
    )
    user_id = uuid4()
    stats = await service.get_user_referral_stats(user_id)
    assert isinstance(stats, UserReferralStats)
    assert stats.creators_count == 0
    assert stats.orders_count == 0
    assert stats.income_current_month == 0.0
    assert stats.income_total == 0.0
    assert stats.paid_total == 0.0
    assert stats.has_pending_payout is False
    assert stats.has_request_today is False


@pytest.mark.asyncio
async def test_count_completed_orders_for_user_returns_zero_when_none() -> None:
    """count_completed_orders_for_user returns 0 when user has no completed."""
    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    order_response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()

    service = ReferralIncomeService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        order_response_repo=order_response_repo,
        order_repo=order_repo,
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=interaction_repo,
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
    )
    user_id = uuid4()
    count = await service.count_completed_orders_for_user(user_id)
    assert count == 0


@pytest.mark.asyncio
async def test_get_user_referral_stats_with_one_binding_no_orders() -> None:
    """get_user_referral_stats with one referred user and no orders."""
    from datetime import datetime, timezone

    from ugc_bot.domain.entities import User, UserReferralBinding
    from ugc_bot.domain.enums import MessengerType, UserStatus

    user_repo = InMemoryUserRepository()
    referrer_id = uuid4()
    referred_id = uuid4()
    await user_repo.save(
        User(
            user_id=referred_id,
            external_id="refd",
            messenger_type=MessengerType.TELEGRAM,
            username="referred",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
        )
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=referred_id,
            created_at=datetime.now(timezone.utc),
        )
    )
    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        order_response_repo=InMemoryOrderResponseRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
    )
    stats = await service.get_user_referral_stats(referrer_id)
    assert stats.creators_count == 1
    assert stats.orders_count == 0
    assert stats.income_total == 0.0
    assert stats.paid_total == 0.0
    assert stats.has_pending_payout is False
    assert stats.has_request_today is False


@pytest.mark.asyncio
async def test_get_user_referral_stats_with_completed_order_counts_income() -> (
    None
):
    """get_user_referral_stats counts one completed order and income."""
    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    referred_id = uuid4()
    advertiser_id = uuid4()
    order_id = uuid4()

    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=referred_id,
            external_id="r",
            messenger_type=MessengerType.TELEGRAM,
            username="ref",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now,
        )
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=referred_id,
            created_at=now,
        )
    )
    order_repo = InMemoryOrderRepository()
    await order_repo.save(
        Order(
            order_id=order_id,
            advertiser_id=advertiser_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://x.com",
            offer_text="Offer",
            barter_description=None,
            price=3000.0,
            bloggers_needed=3,
            status=OrderStatus.CLOSED,
            created_at=now,
            completed_at=now,
        )
    )
    order_response_repo = InMemoryOrderResponseRepository()
    await order_response_repo.save(
        OrderResponse(
            response_id=uuid4(),
            order_id=order_id,
            blogger_id=referred_id,
            responded_at=now,
        )
    )
    payment_repo = InMemoryPaymentRepository()
    await payment_repo.save(
        Payment(
            payment_id=uuid4(),
            order_id=order_id,
            provider="test",
            status=PaymentStatus.PAID,
            amount=3000.0,
            currency="RUB",
            external_id="ext",
            created_at=now,
            paid_at=now,
        )
    )
    interaction_repo = InMemoryInteractionRepository()
    await interaction_repo.save(
        Interaction(
            interaction_id=uuid4(),
            order_id=order_id,
            blogger_id=referred_id,
            advertiser_id=advertiser_id,
            status=InteractionStatus.OK,
            from_advertiser=None,
            from_blogger=None,
            postpone_count=0,
            next_check_at=None,
            created_at=now,
            updated_at=now,
        )
    )

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        order_response_repo=order_response_repo,
        order_repo=order_repo,
        payment_repo=payment_repo,
        interaction_repo=interaction_repo,
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
    )
    stats = await service.get_user_referral_stats(referrer_id)
    assert stats.creators_count == 1
    assert stats.orders_count == 1
    assert stats.income_total > 0
    assert stats.paid_total == 0.0
    assert stats.has_pending_payout is False
    assert stats.has_request_today is False


@pytest.mark.asyncio
async def test_count_completed_orders_for_user_with_one_completed_order() -> (
    None
):
    """count_completed_orders_for_user returns 1 when user has one OK order."""
    now = datetime.now(timezone.utc)
    user_id = uuid4()
    advertiser_id = uuid4()
    order_id = uuid4()

    order_repo = InMemoryOrderRepository()
    await order_repo.save(
        Order(
            order_id=order_id,
            advertiser_id=advertiser_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://x.com",
            offer_text="Offer",
            barter_description=None,
            price=1000.0,
            bloggers_needed=1,
            status=OrderStatus.CLOSED,
            created_at=now,
            completed_at=now,
        )
    )
    order_response_repo = InMemoryOrderResponseRepository()
    await order_response_repo.save(
        OrderResponse(
            response_id=uuid4(),
            order_id=order_id,
            blogger_id=user_id,
            responded_at=now,
        )
    )
    interaction_repo = InMemoryInteractionRepository()
    await interaction_repo.save(
        Interaction(
            interaction_id=uuid4(),
            order_id=order_id,
            blogger_id=user_id,
            advertiser_id=advertiser_id,
            status=InteractionStatus.OK,
            from_advertiser=None,
            from_blogger=None,
            postpone_count=0,
            next_check_at=None,
            created_at=now,
            updated_at=now,
        )
    )

    service = ReferralIncomeService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        order_response_repo=order_response_repo,
        order_repo=order_repo,
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=interaction_repo,
        user_repo=InMemoryUserRepository(),
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
    )
    count = await service.count_completed_orders_for_user(user_id)
    assert count == 1


@pytest.mark.asyncio
async def test_get_user_referral_stats_paid_total_sums_paid_payouts() -> None:
    """paid_total is sum of amounts of payout requests with status PAID."""
    now = datetime.now(timezone.utc)
    user_id = uuid4()

    payout_repo = InMemoryPayoutRequestRepository()
    await payout_repo.save(
        PayoutRequest(
            request_id=uuid4(),
            user_id=user_id,
            requested_at=now,
            status=PayoutRequestStatus.PAID,
            amount=Decimal("100.50"),
        )
    )
    await payout_repo.save(
        PayoutRequest(
            request_id=uuid4(),
            user_id=user_id,
            requested_at=now,
            status=PayoutRequestStatus.PAID,
            amount=Decimal("49.50"),
        )
    )
    await payout_repo.save(
        PayoutRequest(
            request_id=uuid4(),
            user_id=user_id,
            requested_at=now,
            status=PayoutRequestStatus.PENDING,
            amount=Decimal("200.00"),
        )
    )

    service = ReferralIncomeService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        order_response_repo=InMemoryOrderResponseRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=payout_repo,
        transaction_manager=None,
    )
    stats = await service.get_user_referral_stats(user_id)
    assert stats.paid_total == 150.0
    assert stats.income_total == 0.0
    assert stats.has_pending_payout is True
    assert stats.has_request_today is True


@pytest.mark.asyncio
async def test_get_user_referral_stats_has_pending_payout_when_pending() -> (
    None
):
    """has_pending_payout is True when user has at least one PENDING request."""
    now = datetime.now(timezone.utc)
    user_id = uuid4()

    payout_repo = InMemoryPayoutRequestRepository()
    await payout_repo.save(
        PayoutRequest(
            request_id=uuid4(),
            user_id=user_id,
            requested_at=now,
            status=PayoutRequestStatus.PENDING,
            amount=Decimal("50.00"),
        )
    )

    service = ReferralIncomeService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        order_response_repo=InMemoryOrderResponseRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=payout_repo,
        transaction_manager=None,
    )
    stats = await service.get_user_referral_stats(user_id)
    assert stats.has_pending_payout is True
    assert stats.has_request_today is True
    assert stats.paid_total == 0.0


@pytest.mark.asyncio
async def test_has_request_today_false_when_request_yesterday() -> None:
    """has_request_today is False when only request is from yesterday."""
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    user_id = uuid4()

    payout_repo = InMemoryPayoutRequestRepository()
    await payout_repo.save(
        PayoutRequest(
            request_id=uuid4(),
            user_id=user_id,
            requested_at=yesterday,
            status=PayoutRequestStatus.PENDING,
            amount=Decimal("10.00"),
        )
    )

    service = ReferralIncomeService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        order_response_repo=InMemoryOrderResponseRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=payout_repo,
        transaction_manager=None,
    )
    stats = await service.get_user_referral_stats(user_id)
    assert stats.has_request_today is False
    assert stats.has_pending_payout is True

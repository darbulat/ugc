"""Tests for ReferralIncomeService."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
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
async def test_get_user_referral_stats_binding_without_user_skipped() -> None:
    """When referred user has no User record, that binding is skipped."""
    referrer_id = uuid4()
    referred_id = uuid4()
    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=referred_id,
            created_at=datetime.now(timezone.utc),
        )
    )
    user_repo = InMemoryUserRepository()
    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        order_response_repo=InMemoryOrderResponseRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_order_income_loader=None,
    )
    stats = await service.get_user_referral_stats(referrer_id)
    assert stats.creators_count == 1
    assert stats.orders_count == 0
    assert stats.income_total == 0.0


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
    order_response_repo = InMemoryOrderResponseRepository(
        order_repo=order_repo, interaction_repo=interaction_repo
    )
    await order_response_repo.save(
        OrderResponse(
            response_id=uuid4(),
            order_id=order_id,
            blogger_id=user_id,
            responded_at=now,
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
async def test_count_completed_orders_for_user_skips_non_closed_order() -> None:
    """count_completed_orders_for_user skips orders that are not CLOSED."""
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
            status=OrderStatus.ACTIVE,
            created_at=now,
            completed_at=None,
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
    service = ReferralIncomeService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        order_response_repo=order_response_repo,
        order_repo=order_repo,
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
    )
    count = await service.count_completed_orders_for_user(user_id)
    assert count == 0


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


@pytest.mark.asyncio
async def test_get_user_referral_stats_stats_limit_zero_unlimited() -> None:
    """get_user_referral_stats with stats_limit=0 uses unlimited limit."""
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
    stats = await service.get_user_referral_stats(referrer_id, stats_limit=0)
    assert stats.creators_count == 1


@pytest.mark.asyncio
async def test_count_completed_orders_for_user_with_session() -> None:
    """count_completed_orders_for_user with session uses it (no new tx)."""
    service = ReferralIncomeService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        order_response_repo=InMemoryOrderResponseRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
    )
    user_id = uuid4()
    count = await service.count_completed_orders_for_user(
        user_id, session=MagicMock()
    )
    assert count == 0


@pytest.mark.asyncio
async def test_count_completed_orders_by_user_ids_returns_dict() -> None:
    """count_completed_orders_by_user_ids returns counts per user id."""
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
    order_response_repo = InMemoryOrderResponseRepository(
        order_repo=order_repo, interaction_repo=interaction_repo
    )
    await order_response_repo.save(
        OrderResponse(
            response_id=uuid4(),
            order_id=order_id,
            blogger_id=user_id,
            responded_at=now,
        )
    )
    other_id = uuid4()
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
    counts = await service.count_completed_orders_by_user_ids(
        [user_id, other_id]
    )
    assert counts == {user_id: 1, other_id: 0}


@pytest.mark.asyncio
async def test_count_completed_orders_by_user_ids_with_session() -> None:
    """count_completed_orders_by_user_ids with session uses it."""
    service = ReferralIncomeService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        order_response_repo=InMemoryOrderResponseRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
    )
    counts = await service.count_completed_orders_by_user_ids(
        [uuid4()], session=MagicMock()
    )
    assert counts == {} or list(counts.values())[0] == 0


@pytest.mark.asyncio
async def test_get_user_referral_stats_uses_loader_when_provided() -> None:
    """When loader and session are set, stats use loader (single-query path)."""
    from contextlib import asynccontextmanager

    from ugc_bot.domain.entities import ReferralOrderIncomeRow

    referrer_id = uuid4()
    order_id = uuid4()
    now = datetime.now(timezone.utc)
    creator_created = now - timedelta(days=100)
    order_completed = now - timedelta(days=10)
    row = ReferralOrderIncomeRow(
        creator_created_at=creator_created,
        order_completed_at=order_completed,
        payment_amount=100.0,
        bloggers_needed=1,
        order_id=order_id,
    )
    mock_loader = MagicMock()
    mock_loader.load_referral_order_income_rows = AsyncMock(return_value=[row])
    mock_loader.load_referral_order_income_rows_advertisers = AsyncMock(
        return_value=[]
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    referred_id = uuid4()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=referred_id,
            created_at=datetime.now(timezone.utc),
        )
    )

    @asynccontextmanager
    async def fake_tx():
        yield object()

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        order_response_repo=InMemoryOrderResponseRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=MagicMock(transaction=lambda: fake_tx()),
        referral_order_income_loader=mock_loader,
    )
    stats = await service.get_user_referral_stats(referrer_id)
    assert stats.creators_count == 1
    assert stats.orders_count == 1
    assert stats.income_total == 10.0
    mock_loader.load_referral_order_income_rows.assert_called_once()


@pytest.mark.asyncio
async def test_stats_uses_combined_loader_when_available() -> None:
    """When loader has async combined method, it is used for stats."""
    from contextlib import asynccontextmanager

    from ugc_bot.domain.entities import ReferralOrderIncomeRow

    referrer_id = uuid4()
    order_id = uuid4()
    now = datetime.now(timezone.utc)
    creator_created = now - timedelta(days=100)
    order_completed = now - timedelta(days=10)
    row = ReferralOrderIncomeRow(
        creator_created_at=creator_created,
        order_completed_at=order_completed,
        payment_amount=100.0,
        bloggers_needed=1,
        order_id=order_id,
    )

    class CombinedLoader:
        async def load_referral_order_income_rows(
            self, referrer_user_id, limit, session=None
        ):
            return []

        async def load_referral_order_income_rows_advertisers(
            self, referrer_user_id, limit, session=None
        ):
            return []

        async def load_referral_order_income_rows_combined(
            self, referrer_user_id, limit, session=None
        ):
            return [row]

    binding_repo = InMemoryUserReferralBindingRepository()
    referred_id = uuid4()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=referred_id,
            created_at=datetime.now(timezone.utc),
        )
    )

    @asynccontextmanager
    async def fake_tx():
        yield object()

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        order_response_repo=InMemoryOrderResponseRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=MagicMock(transaction=lambda: fake_tx()),
        referral_order_income_loader=CombinedLoader(),
    )
    stats = await service.get_user_referral_stats(referrer_id)
    assert stats.creators_count == 1
    assert stats.orders_count == 1
    assert stats.income_total == 10.0


@pytest.mark.asyncio
async def test_get_user_referral_stats_loader_rate_after_first_year() -> None:
    """When order is exactly 1 year after creator registration, rate is 3%."""
    from contextlib import asynccontextmanager

    from ugc_bot.domain.entities import ReferralOrderIncomeRow

    referrer_id = uuid4()
    order_id = uuid4()
    now = datetime.now(timezone.utc)
    creator_created = now - timedelta(days=366)
    order_completed = now
    row = ReferralOrderIncomeRow(
        creator_created_at=creator_created,
        order_completed_at=order_completed,
        payment_amount=100.0,
        bloggers_needed=1,
        order_id=order_id,
    )
    mock_loader = MagicMock()
    mock_loader.load_referral_order_income_rows = AsyncMock(return_value=[row])
    mock_loader.load_referral_order_income_rows_advertisers = AsyncMock(
        return_value=[]
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    referred_id = uuid4()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=referred_id,
            created_at=datetime.now(timezone.utc),
        )
    )

    @asynccontextmanager
    async def fake_tx():
        yield object()

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        order_response_repo=InMemoryOrderResponseRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=MagicMock(transaction=lambda: fake_tx()),
        referral_order_income_loader=mock_loader,
    )
    stats = await service.get_user_referral_stats(referrer_id)
    assert stats.income_total == 3.0


@pytest.mark.asyncio
async def test_get_user_referral_stats_uses_custom_rate_when_set() -> None:
    """When referrer has referral_payout_rate set, income uses that rate."""
    from contextlib import asynccontextmanager

    from ugc_bot.domain.entities import ReferralOrderIncomeRow

    referrer_id = uuid4()
    order_id = uuid4()
    now = datetime.now(timezone.utc)
    creator_created = now - timedelta(days=100)
    order_completed = now - timedelta(days=10)
    row = ReferralOrderIncomeRow(
        creator_created_at=creator_created,
        order_completed_at=order_completed,
        payment_amount=100.0,
        bloggers_needed=1,
        order_id=order_id,
    )
    mock_loader = MagicMock()
    mock_loader.load_referral_order_income_rows = AsyncMock(return_value=[row])
    mock_loader.load_referral_order_income_rows_advertisers = AsyncMock(
        return_value=[]
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    referred_id = uuid4()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=referred_id,
            created_at=datetime.now(timezone.utc),
        )
    )
    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=referrer_id,
            external_id="ref",
            messenger_type=MessengerType.TELEGRAM,
            username="referrer",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
            referral_payout_rate=Decimal("0.15"),
        )
    )

    @asynccontextmanager
    async def fake_tx():
        yield object()

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        order_response_repo=InMemoryOrderResponseRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=MagicMock(transaction=lambda: fake_tx()),
        referral_order_income_loader=mock_loader,
    )
    stats = await service.get_user_referral_stats(referrer_id)
    assert stats.creators_count == 1
    assert stats.orders_count == 1
    assert stats.income_total == 15.0


@pytest.mark.asyncio
async def test_get_user_referral_stats_custom_rate_none_keeps_default() -> None:
    """When referrer has no referral_payout_rate, default 10%%/3%% is used."""
    from contextlib import asynccontextmanager

    from ugc_bot.domain.entities import ReferralOrderIncomeRow

    referrer_id = uuid4()
    order_id = uuid4()
    now = datetime.now(timezone.utc)
    creator_created = now - timedelta(days=100)
    order_completed = now - timedelta(days=10)
    row = ReferralOrderIncomeRow(
        creator_created_at=creator_created,
        order_completed_at=order_completed,
        payment_amount=100.0,
        bloggers_needed=1,
        order_id=order_id,
    )
    mock_loader = MagicMock()
    mock_loader.load_referral_order_income_rows = AsyncMock(return_value=[row])
    mock_loader.load_referral_order_income_rows_advertisers = AsyncMock(
        return_value=[]
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    referred_id = uuid4()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=referred_id,
            created_at=datetime.now(timezone.utc),
        )
    )
    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=referrer_id,
            external_id="ref",
            messenger_type=MessengerType.TELEGRAM,
            username="referrer",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
            referral_payout_rate=None,
        )
    )

    @asynccontextmanager
    async def fake_tx():
        yield object()

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        order_response_repo=InMemoryOrderResponseRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=MagicMock(transaction=lambda: fake_tx()),
        referral_order_income_loader=mock_loader,
    )
    stats = await service.get_user_referral_stats(referrer_id)
    assert stats.income_total == 10.0


@pytest.mark.asyncio
async def test_get_user_referral_stats_counts_advertiser_order_income() -> None:
    """Referred advertiser CLOSED order with PAID payment counts as income."""
    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    advertiser_id = uuid4()
    order_id = uuid4()

    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=advertiser_id,
            external_id="adv",
            messenger_type=MessengerType.TELEGRAM,
            username="advertiser",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now - timedelta(days=100),
        )
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=advertiser_id,
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
            price=5000.0,
            bloggers_needed=2,
            status=OrderStatus.CLOSED,
            created_at=now,
            completed_at=now,
        )
    )
    payment_repo = InMemoryPaymentRepository()
    await payment_repo.save(
        Payment(
            payment_id=uuid4(),
            order_id=order_id,
            provider="test",
            status=PaymentStatus.PAID,
            amount=Decimal("5000.0"),
            currency="RUB",
            external_id="ext",
            created_at=now,
            paid_at=now,
        )
    )
    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        order_response_repo=InMemoryOrderResponseRepository(),
        order_repo=order_repo,
        payment_repo=payment_repo,
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_order_income_loader=None,
    )
    stats = await service.get_user_referral_stats(referrer_id)
    assert stats.creators_count == 1
    assert stats.orders_count == 1
    assert stats.income_total == 500.0


@pytest.mark.asyncio
async def test_get_user_referral_stats_loader_includes_advertiser_rows() -> (
    None
):
    """Loader advertiser rows are included in income and orders_count."""
    from contextlib import asynccontextmanager

    from ugc_bot.domain.entities import ReferralOrderIncomeRow

    referrer_id = uuid4()
    order_id = uuid4()
    now = datetime.now(timezone.utc)
    creator_created = now - timedelta(days=200)
    order_completed = now - timedelta(days=5)
    row = ReferralOrderIncomeRow(
        creator_created_at=creator_created,
        order_completed_at=order_completed,
        payment_amount=2000.0,
        bloggers_needed=1,
        order_id=order_id,
    )
    mock_loader = MagicMock()
    mock_loader.load_referral_order_income_rows = AsyncMock(return_value=[])
    mock_loader.load_referral_order_income_rows_advertisers = AsyncMock(
        return_value=[row]
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    referred_id = uuid4()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=referred_id,
            created_at=datetime.now(timezone.utc),
        )
    )

    @asynccontextmanager
    async def fake_tx():
        yield object()

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        order_response_repo=InMemoryOrderResponseRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=MagicMock(transaction=lambda: fake_tx()),
        referral_order_income_loader=mock_loader,
    )
    stats = await service.get_user_referral_stats(referrer_id)
    assert stats.orders_count == 1
    assert stats.income_total == 200.0


@pytest.mark.asyncio
async def test_advertiser_order_ignored_when_payment_not_paid() -> None:
    """Referred advertiser order with non-PAID payment is not counted."""
    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    advertiser_id = uuid4()
    order_id = uuid4()

    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=advertiser_id,
            external_id="adv",
            messenger_type=MessengerType.TELEGRAM,
            username="advertiser",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now - timedelta(days=50),
        )
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=advertiser_id,
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
            price=1000.0,
            bloggers_needed=1,
            status=OrderStatus.CLOSED,
            created_at=now,
            completed_at=now,
        )
    )
    payment_repo = InMemoryPaymentRepository()
    await payment_repo.save(
        Payment(
            payment_id=uuid4(),
            order_id=order_id,
            provider="test",
            status=PaymentStatus.PENDING,
            amount=Decimal("1000.0"),
            currency="RUB",
            external_id="ext",
            created_at=now,
            paid_at=None,
        )
    )
    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        order_response_repo=InMemoryOrderResponseRepository(),
        order_repo=order_repo,
        payment_repo=payment_repo,
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_order_income_loader=None,
    )
    stats = await service.get_user_referral_stats(referrer_id)
    assert stats.creators_count == 1
    assert stats.orders_count == 0
    assert stats.income_total == 0.0

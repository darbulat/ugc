"""Tests for ReferralIncomeService."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ugc_bot.application.services.referral_income_service import (
    MultiCurrencyReferralStats,
    ReferralIncomeService,
    UserReferralStats,
)
from ugc_bot.domain.entities import (
    ContactPricing,
    Interaction,
    Order,
    Payment,
    PayoutRequest,
    ReferralOrderIncomeRow,
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
    ReferralIncomeType,
    UserStatus,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryContactPricingRepository,
    InMemoryInteractionRepository,
    InMemoryOfferDispatchRepository,
    InMemoryOrderRepository,
    InMemoryPaymentRepository,
    InMemoryPayoutRequestRepository,
    InMemoryReferralIncomeEntryRepository,
    InMemoryUserReferralBindingRepository,
    InMemoryUserRepository,
)


@pytest.mark.asyncio
async def test_get_user_referral_stats_empty_returns_zeros() -> None:
    """get_user_referral_stats returns zeros when user has no referrals."""
    binding_repo = InMemoryUserReferralBindingRepository()
    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    payment_repo = InMemoryPaymentRepository()
    interaction_repo = InMemoryInteractionRepository()

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        offer_dispatch_repo=offer_dispatch_repo,
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
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    interaction_repo = InMemoryInteractionRepository()

    service = ReferralIncomeService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        offer_dispatch_repo=offer_dispatch_repo,
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
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
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
            telegram_id="refd",
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
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
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
            telegram_id="r",
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
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    await offer_dispatch_repo.record_sent(order_id, referred_id)
    await offer_dispatch_repo.record_response(
        order_id, referred_id, accepted=True, in_offer=True
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
        offer_dispatch_repo=offer_dispatch_repo,
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
    offer_dispatch_repo = InMemoryOfferDispatchRepository(
        order_repo=order_repo, interaction_repo=interaction_repo
    )
    await offer_dispatch_repo.record_sent(order_id, user_id)
    await offer_dispatch_repo.record_response(
        order_id, user_id, accepted=True, in_offer=True
    )

    service = ReferralIncomeService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        offer_dispatch_repo=offer_dispatch_repo,
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
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    await offer_dispatch_repo.record_sent(order_id, user_id)
    await offer_dispatch_repo.record_response(
        order_id, user_id, accepted=True, in_offer=True
    )
    service = ReferralIncomeService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        offer_dispatch_repo=offer_dispatch_repo,
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

    yesterday = now - timedelta(days=1)
    payout_repo = InMemoryPayoutRequestRepository()
    await payout_repo.save(
        PayoutRequest(
            request_id=uuid4(),
            user_id=user_id,
            requested_at=yesterday,
            status=PayoutRequestStatus.PAID,
            amount=Decimal("100.50"),
        )
    )
    await payout_repo.save(
        PayoutRequest(
            request_id=uuid4(),
            user_id=user_id,
            requested_at=now - timedelta(days=2),
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
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
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
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
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
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
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
            telegram_id="refd",
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
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
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
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
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
    offer_dispatch_repo = InMemoryOfferDispatchRepository(
        order_repo=order_repo, interaction_repo=interaction_repo
    )
    await offer_dispatch_repo.record_sent(order_id, user_id)
    await offer_dispatch_repo.record_response(
        order_id, user_id, accepted=True, in_offer=True
    )
    other_id = uuid4()
    service = ReferralIncomeService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        offer_dispatch_repo=offer_dispatch_repo,
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
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
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
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
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

        async def load_referral_order_income_rows_combined_batch(
            self, referrer_user_ids, limit=None, session=None
        ):
            return []

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
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
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
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
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
            telegram_id="ref",
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
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
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
            telegram_id="ref",
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
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
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
            telegram_id="adv",
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
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
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
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
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
            telegram_id="adv",
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
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
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


@pytest.mark.asyncio
async def test_get_referral_balances_batch_empty_returns_empty() -> None:
    """get_referral_balances_batch with empty user_ids returns {}."""
    service = ReferralIncomeService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
    )
    result = await service.get_referral_balances_batch([])
    assert result == {}


@pytest.mark.asyncio
async def test_get_referral_balances_batch_uses_income_entries() -> None:
    """get_referral_balances_batch uses income_entries (source of truth)."""
    from ugc_bot.domain.entities import ReferralIncomeEntry

    user_id = uuid4()
    now = datetime.now(timezone.utc)
    entry_repo = InMemoryReferralIncomeEntryRepository()
    await entry_repo.save(
        ReferralIncomeEntry(
            entry_id=uuid4(),
            referrer_user_id=user_id,
            referred_user_id=uuid4(),
            order_id=uuid4(),
            income_type=ReferralIncomeType.CREATOR,
            currency="RUB",
            platform_revenue=Decimal("100.00"),
            commission_rate=Decimal("0.10"),
            commission_amount=Decimal("10.00"),
            created_at=now,
        )
    )
    payout_repo = InMemoryPayoutRequestRepository()
    await payout_repo.save(
        PayoutRequest(
            request_id=uuid4(),
            user_id=user_id,
            requested_at=now,
            status=PayoutRequestStatus.PAID,
            amount=Decimal("10.00"),
        )
    )
    service = ReferralIncomeService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=payout_repo,
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
    )
    result = await service.get_referral_balances_batch([user_id])
    assert result == {user_id: (10.0, 10.0)}
    sess = MagicMock()
    result2 = await service.get_referral_balances_batch([user_id], session=sess)
    assert result2 == {user_id: (10.0, 10.0)}


@pytest.mark.asyncio
async def test_get_referral_balances_batch_fallback_when_no_batch_loader() -> (
    None
):
    """No batch loader: falls back to get_user_referral_stats per user."""
    user_id = uuid4()
    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=user_id,
            telegram_id="e1",
            telegram="u1",
            username="u1",
            status=UserStatus.ACTIVE,
            messenger_type=MessengerType.TELEGRAM,
            referral_code="r1",
            issue_count=0,
            created_at=datetime.now(timezone.utc),
        )
    )
    loader_no_batch = MagicMock(
        spec=["load_referral_order_income_rows_combined"]
    )
    loader_no_batch.load_referral_order_income_rows_combined = AsyncMock(
        return_value=[]
    )
    service = ReferralIncomeService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_order_income_loader=loader_no_batch,
    )
    result = await service.get_referral_balances_batch([user_id])
    assert result == {user_id: (0.0, 0.0)}


@pytest.mark.asyncio
async def test_record_creator_referral_income_creates_entry() -> None:
    """Creator has a referrer — entry created with correct commission."""
    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    creator_id = uuid4()
    advertiser_id = uuid4()
    order_id = uuid4()

    # Repos
    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=creator_id,
            telegram_id="creator1",
            messenger_type=MessengerType.TELEGRAM,
            username="creator1",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now - timedelta(days=30),
        )
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=creator_id,
            created_at=now - timedelta(days=30),
        )
    )
    pricing_repo = InMemoryContactPricingRepository()
    await pricing_repo.save(
        ContactPricing(
            country_code="ru",
            bloggers_count=3,
            price=Decimal("9000"),
            currency="RUB",
            updated_at=now,
        )
    )
    payment_repo = InMemoryPaymentRepository()
    await payment_repo.save(
        Payment(
            payment_id=uuid4(),
            order_id=order_id,
            provider="test",
            status=PaymentStatus.PAID,
            amount=9000.0,
            currency="RUB",
            external_id="ext1",
            created_at=now,
        )
    )
    entry_repo = InMemoryReferralIncomeEntryRepository()

    order = Order(
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

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=payment_repo,
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
        contact_pricing_repo=pricing_repo,
    )

    await service.record_creator_referral_income(
        order=order,
        creator_id=creator_id,
        advertiser_country_code="ru",
    )

    assert len(entry_repo.entries) == 1
    entry = entry_repo.entries[0]
    assert entry.referrer_user_id == referrer_id
    assert entry.referred_user_id == creator_id
    assert entry.order_id == order_id
    assert entry.income_type == ReferralIncomeType.CREATOR
    assert entry.currency == "RUB"
    # platform_revenue = payment.amount / bloggers_needed = 9000 / 3 = 3000
    # rate = 0.10, commission = 300.00
    assert entry.platform_revenue == Decimal("3000")
    assert entry.commission_rate == Decimal("0.10")
    assert entry.commission_amount == Decimal("300.00")


@pytest.mark.asyncio
async def test_record_creator_referral_income_no_binding() -> None:
    """Creator has no referrer — no entry created."""
    now = datetime.now(timezone.utc)
    creator_id = uuid4()

    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=creator_id,
            telegram_id="creator2",
            messenger_type=MessengerType.TELEGRAM,
            username="creator2",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now,
        )
    )
    entry_repo = InMemoryReferralIncomeEntryRepository()
    pricing_repo = InMemoryContactPricingRepository()

    order = Order(
        order_id=uuid4(),
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://x.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.CLOSED,
        created_at=now,
        completed_at=now,
    )

    service = ReferralIncomeService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
        contact_pricing_repo=pricing_repo,
    )

    await service.record_creator_referral_income(
        order=order,
        creator_id=creator_id,
        advertiser_country_code="ru",
    )

    assert len(entry_repo.entries) == 0


@pytest.mark.asyncio
async def test_record_advertiser_referral_income_creates_entry() -> None:
    """Advertiser has a referrer — entry with full platform_revenue."""
    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    advertiser_id = uuid4()
    order_id = uuid4()

    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=advertiser_id,
            telegram_id="adv1",
            messenger_type=MessengerType.TELEGRAM,
            username="adv1",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now - timedelta(days=30),
        )
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=advertiser_id,
            created_at=now - timedelta(days=30),
        )
    )
    pricing_repo = InMemoryContactPricingRepository()
    await pricing_repo.save(
        ContactPricing(
            country_code="ru",
            bloggers_count=3,
            price=Decimal("9000"),
            currency="RUB",
            updated_at=now,
        )
    )
    payment_repo = InMemoryPaymentRepository()
    await payment_repo.save(
        Payment(
            payment_id=uuid4(),
            order_id=order_id,
            provider="test",
            status=PaymentStatus.PAID,
            amount=9000.0,
            currency="RUB",
            external_id="ext2",
            created_at=now,
        )
    )
    entry_repo = InMemoryReferralIncomeEntryRepository()

    order = Order(
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

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=payment_repo,
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
        contact_pricing_repo=pricing_repo,
    )

    await service.record_advertiser_referral_income(
        order=order,
        advertiser_id=advertiser_id,
        advertiser_country_code="ru",
    )

    assert len(entry_repo.entries) == 1
    entry = entry_repo.entries[0]
    assert entry.referrer_user_id == referrer_id
    assert entry.referred_user_id == advertiser_id
    assert entry.order_id == order_id
    assert entry.income_type == ReferralIncomeType.ADVERTISER
    assert entry.currency == "RUB"
    # platform_revenue = payment.amount = 9000, rate = 0.10, commission = 900.00
    assert entry.platform_revenue == Decimal("9000")
    assert entry.commission_rate == Decimal("0.10")
    assert entry.commission_amount == Decimal("900.00")


@pytest.mark.asyncio
async def test_record_creator_referral_income_idempotent() -> None:
    """Calling twice for the same order — only one entry saved."""
    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    creator_id = uuid4()
    order_id = uuid4()

    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=creator_id,
            telegram_id="creator3",
            messenger_type=MessengerType.TELEGRAM,
            username="creator3",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now - timedelta(days=30),
        )
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=creator_id,
            created_at=now - timedelta(days=30),
        )
    )
    pricing_repo = InMemoryContactPricingRepository()
    await pricing_repo.save(
        ContactPricing(
            country_code="ru",
            bloggers_count=3,
            price=Decimal("9000"),
            currency="RUB",
            updated_at=now,
        )
    )
    payment_repo = InMemoryPaymentRepository()
    await payment_repo.save(
        Payment(
            payment_id=uuid4(),
            order_id=order_id,
            provider="test",
            status=PaymentStatus.PAID,
            amount=9000.0,
            currency="RUB",
            external_id="ext3",
            created_at=now,
        )
    )
    entry_repo = InMemoryReferralIncomeEntryRepository()

    order = Order(
        order_id=order_id,
        advertiser_id=uuid4(),
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

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=payment_repo,
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
        contact_pricing_repo=pricing_repo,
    )

    await service.record_creator_referral_income(
        order=order,
        creator_id=creator_id,
        advertiser_country_code="ru",
    )
    await service.record_creator_referral_income(
        order=order,
        creator_id=creator_id,
        advertiser_country_code="ru",
    )

    assert len(entry_repo.entries) == 1


def _make_multicurrency_service(
    binding_repo: InMemoryUserReferralBindingRepository | None = None,
    entry_repo: InMemoryReferralIncomeEntryRepository | None = None,
    payout_repo: InMemoryPayoutRequestRepository | None = None,
) -> ReferralIncomeService:
    """Create a ReferralIncomeService for stats tests."""
    return ReferralIncomeService(
        user_referral_binding_repo=binding_repo
        or InMemoryUserReferralBindingRepository(),
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=payout_repo or InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo
        or InMemoryReferralIncomeEntryRepository(),
    )


@pytest.mark.asyncio
async def test_get_multicurrency_stats_empty() -> None:
    """Empty stats when no data."""
    service = _make_multicurrency_service()
    user_id = uuid4()

    stats = await service.get_multicurrency_stats(user_id)

    assert isinstance(stats, MultiCurrencyReferralStats)
    assert stats.creators_count == 0
    assert stats.income_by_currency == {}
    assert stats.orders_by_currency == {}
    assert stats.paid_by_currency == {}
    assert stats.pending_by_currency == {}
    assert stats.available_by_currency == {}
    assert stats.has_request_today_by_currency == {}


@pytest.mark.asyncio
async def test_get_multicurrency_stats_with_entries() -> None:
    """Stats with entries: income, paid, available."""
    referrer_id = uuid4()
    referred_id = uuid4()
    order_id = uuid4()
    now = datetime.now(timezone.utc)

    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=referred_id,
            created_at=now,
        )
    )

    entry_repo = InMemoryReferralIncomeEntryRepository()
    from ugc_bot.domain.entities import ReferralIncomeEntry

    await entry_repo.save(
        ReferralIncomeEntry(
            entry_id=uuid4(),
            referrer_user_id=referrer_id,
            referred_user_id=referred_id,
            order_id=order_id,
            income_type=ReferralIncomeType.CREATOR,
            currency="RUB",
            platform_revenue=Decimal("1000.00"),
            commission_rate=Decimal("0.10"),
            commission_amount=Decimal("100.00"),
            created_at=now,
        )
    )

    payout_repo = InMemoryPayoutRequestRepository()
    await payout_repo.save(
        PayoutRequest(
            request_id=uuid4(),
            user_id=referrer_id,
            requested_at=now - timedelta(days=1),
            status=PayoutRequestStatus.PAID,
            amount=Decimal("30.00"),
            currency="RUB",
        )
    )

    service = _make_multicurrency_service(
        binding_repo=binding_repo,
        entry_repo=entry_repo,
        payout_repo=payout_repo,
    )

    stats = await service.get_multicurrency_stats(referrer_id)

    assert stats.creators_count == 1
    assert stats.income_by_currency == {"RUB": Decimal("100.00")}
    assert stats.orders_by_currency == {"RUB": 1}
    assert stats.paid_by_currency == {"RUB": Decimal("30.00")}
    assert stats.pending_by_currency == {}
    assert stats.available_by_currency == {"RUB": Decimal("70.00")}


@pytest.mark.asyncio
async def test_get_multicurrency_stats_available_excludes_pending() -> None:
    """available = income - paid - pending, minimum 0."""
    referrer_id = uuid4()
    referred_id = uuid4()
    now = datetime.now(timezone.utc)

    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=referred_id,
            created_at=now,
        )
    )

    entry_repo = InMemoryReferralIncomeEntryRepository()
    from ugc_bot.domain.entities import ReferralIncomeEntry

    await entry_repo.save(
        ReferralIncomeEntry(
            entry_id=uuid4(),
            referrer_user_id=referrer_id,
            referred_user_id=referred_id,
            order_id=uuid4(),
            income_type=ReferralIncomeType.CREATOR,
            currency="USD",
            platform_revenue=Decimal("500.00"),
            commission_rate=Decimal("0.10"),
            commission_amount=Decimal("50.00"),
            created_at=now,
        )
    )

    payout_repo = InMemoryPayoutRequestRepository()
    await payout_repo.save(
        PayoutRequest(
            request_id=uuid4(),
            user_id=referrer_id,
            requested_at=now,
            status=PayoutRequestStatus.PENDING,
            amount=Decimal("20.00"),
            currency="USD",
        )
    )

    service = _make_multicurrency_service(
        binding_repo=binding_repo,
        entry_repo=entry_repo,
        payout_repo=payout_repo,
    )

    stats = await service.get_multicurrency_stats(referrer_id)

    assert stats.income_by_currency == {"USD": Decimal("50.00")}
    assert stats.pending_by_currency == {"USD": Decimal("20.00")}
    assert stats.paid_by_currency == {}
    assert stats.available_by_currency == {"USD": Decimal("30.00")}
    assert stats.has_request_today_by_currency == {"USD": True}


@pytest.mark.asyncio
async def test_record_creator_no_binding_skips() -> None:
    """No binding for creator — entry_repo stays empty."""
    now = datetime.now(timezone.utc)
    creator_id = uuid4()

    entry_repo = InMemoryReferralIncomeEntryRepository()
    pricing_repo = InMemoryContactPricingRepository()
    await pricing_repo.save(
        ContactPricing(
            country_code="ru",
            bloggers_count=3,
            price=Decimal("9000"),
            currency="RUB",
            updated_at=now,
        )
    )
    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=creator_id,
            telegram_id="c1",
            messenger_type=MessengerType.TELEGRAM,
            username="c1",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now,
        )
    )

    order = Order(
        order_id=uuid4(),
        advertiser_id=uuid4(),
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

    service = ReferralIncomeService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
        contact_pricing_repo=pricing_repo,
    )

    await service.record_creator_referral_income(
        order=order,
        creator_id=creator_id,
        advertiser_country_code="ru",
    )

    assert len(entry_repo.entries) == 0


@pytest.mark.asyncio
async def test_record_creator_no_pricing_skips() -> None:
    """Binding exists but no matching pricing — entry_repo stays empty."""
    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    creator_id = uuid4()

    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=creator_id,
            created_at=now,
        )
    )
    # Pre-populate with a non-matching key so defaults are skipped
    _dummy_key: dict = {
        ("us", 99): ContactPricing(
            country_code="us",
            bloggers_count=99,
            price=Decimal("1"),
            currency="USD",
            updated_at=now,
        )
    }
    pricing_repo = InMemoryContactPricingRepository(prices=_dummy_key)
    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=creator_id,
            telegram_id="c2",
            messenger_type=MessengerType.TELEGRAM,
            username="c2",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now,
        )
    )
    entry_repo = InMemoryReferralIncomeEntryRepository()

    order = Order(
        order_id=uuid4(),
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://x.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.CLOSED,
        created_at=now,
        completed_at=now,
    )

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
        contact_pricing_repo=pricing_repo,
    )

    await service.record_creator_referral_income(
        order=order,
        creator_id=creator_id,
        advertiser_country_code="ru",
    )

    assert len(entry_repo.entries) == 0


@pytest.mark.asyncio
async def test_record_creator_no_user_skips() -> None:
    """Binding, pricing, and payment exist but creator not in user_repo."""
    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    creator_id = uuid4()
    order_id = uuid4()

    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=creator_id,
            created_at=now,
        )
    )
    pricing_repo = InMemoryContactPricingRepository()
    await pricing_repo.save(
        ContactPricing(
            country_code="ru",
            bloggers_count=3,
            price=Decimal("9000"),
            currency="RUB",
            updated_at=now,
        )
    )
    payment_repo = InMemoryPaymentRepository()
    await payment_repo.save(
        Payment(
            payment_id=uuid4(),
            order_id=order_id,
            provider="test",
            status=PaymentStatus.PAID,
            amount=9000.0,
            currency="RUB",
            external_id="ext_no_user",
            created_at=now,
        )
    )
    # creator is NOT saved to user_repo
    entry_repo = InMemoryReferralIncomeEntryRepository()

    order = Order(
        order_id=order_id,
        advertiser_id=uuid4(),
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

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=payment_repo,
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
        contact_pricing_repo=pricing_repo,
    )

    await service.record_creator_referral_income(
        order=order,
        creator_id=creator_id,
        advertiser_country_code="ru",
    )

    assert len(entry_repo.entries) == 0


@pytest.mark.asyncio
async def test_record_advertiser_no_binding_skips() -> None:
    """No binding for advertiser — entry_repo stays empty."""
    now = datetime.now(timezone.utc)
    advertiser_id = uuid4()

    pricing_repo = InMemoryContactPricingRepository()
    await pricing_repo.save(
        ContactPricing(
            country_code="ru",
            bloggers_count=3,
            price=Decimal("9000"),
            currency="RUB",
            updated_at=now,
        )
    )
    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=advertiser_id,
            telegram_id="adv2",
            messenger_type=MessengerType.TELEGRAM,
            username="adv2",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now,
        )
    )
    entry_repo = InMemoryReferralIncomeEntryRepository()

    order = Order(
        order_id=uuid4(),
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

    service = ReferralIncomeService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
        contact_pricing_repo=pricing_repo,
    )

    await service.record_advertiser_referral_income(
        order=order,
        advertiser_id=advertiser_id,
        advertiser_country_code="ru",
    )

    assert len(entry_repo.entries) == 0


@pytest.mark.asyncio
async def test_record_advertiser_no_pricing_skips() -> None:
    """Binding exists but no matching pricing — entry_repo stays empty."""
    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    advertiser_id = uuid4()

    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=advertiser_id,
            created_at=now,
        )
    )
    # Pre-populate with non-matching key so defaults are skipped
    _dummy_key2: dict = {
        ("us", 99): ContactPricing(
            country_code="us",
            bloggers_count=99,
            price=Decimal("1"),
            currency="USD",
            updated_at=now,
        )
    }
    pricing_repo = InMemoryContactPricingRepository(prices=_dummy_key2)
    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=advertiser_id,
            telegram_id="adv3",
            messenger_type=MessengerType.TELEGRAM,
            username="adv3",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now,
        )
    )
    entry_repo = InMemoryReferralIncomeEntryRepository()

    order = Order(
        order_id=uuid4(),
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

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
        contact_pricing_repo=pricing_repo,
    )

    await service.record_advertiser_referral_income(
        order=order,
        advertiser_id=advertiser_id,
        advertiser_country_code="ru",
    )

    assert len(entry_repo.entries) == 0


@pytest.mark.asyncio
async def test_record_advertiser_no_user_skips() -> None:
    """Binding, pricing, and payment exist but advertiser not in user_repo."""
    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    advertiser_id = uuid4()
    order_id = uuid4()

    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=advertiser_id,
            created_at=now,
        )
    )
    pricing_repo = InMemoryContactPricingRepository()
    await pricing_repo.save(
        ContactPricing(
            country_code="ru",
            bloggers_count=3,
            price=Decimal("9000"),
            currency="RUB",
            updated_at=now,
        )
    )
    payment_repo = InMemoryPaymentRepository()
    await payment_repo.save(
        Payment(
            payment_id=uuid4(),
            order_id=order_id,
            provider="test",
            status=PaymentStatus.PAID,
            amount=9000.0,
            currency="RUB",
            external_id="ext_adv_no_user",
            created_at=now,
        )
    )
    # advertiser is NOT saved to user_repo
    entry_repo = InMemoryReferralIncomeEntryRepository()

    order = Order(
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

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=payment_repo,
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
        contact_pricing_repo=pricing_repo,
    )

    await service.record_advertiser_referral_income(
        order=order,
        advertiser_id=advertiser_id,
        advertiser_country_code="ru",
    )

    assert len(entry_repo.entries) == 0


@pytest.mark.asyncio
async def test_record_creator_custom_rate() -> None:
    """Creator's referrer has custom rate — commission uses that rate."""
    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    creator_id = uuid4()
    order_id = uuid4()

    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=creator_id,
            telegram_id="c_custom",
            messenger_type=MessengerType.TELEGRAM,
            username="c_custom",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now - timedelta(days=30),
            referral_payout_rate=Decimal("0.15"),
        )
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=creator_id,
            created_at=now - timedelta(days=30),
        )
    )
    pricing_repo = InMemoryContactPricingRepository()
    await pricing_repo.save(
        ContactPricing(
            country_code="ru",
            bloggers_count=3,
            price=Decimal("9000"),
            currency="RUB",
            updated_at=now,
        )
    )
    payment_repo = InMemoryPaymentRepository()
    await payment_repo.save(
        Payment(
            payment_id=uuid4(),
            order_id=order_id,
            provider="test",
            status=PaymentStatus.PAID,
            amount=9000.0,
            currency="RUB",
            external_id="ext_c_custom",
            created_at=now,
        )
    )
    entry_repo = InMemoryReferralIncomeEntryRepository()

    order = Order(
        order_id=order_id,
        advertiser_id=uuid4(),
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

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=payment_repo,
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
        contact_pricing_repo=pricing_repo,
    )

    await service.record_creator_referral_income(
        order=order,
        creator_id=creator_id,
        advertiser_country_code="ru",
    )

    assert len(entry_repo.entries) == 1
    entry = entry_repo.entries[0]
    assert entry.commission_rate == Decimal("0.15")
    # platform_revenue = payment.amount / bloggers_needed = 9000 / 3 = 3000
    # commission = 3000 * 0.15 = 450.00
    assert entry.commission_amount == Decimal("450.00")


@pytest.mark.asyncio
async def test_record_advertiser_custom_rate() -> None:
    """Advertiser's referrer has custom rate — commission uses that rate."""
    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    advertiser_id = uuid4()
    order_id = uuid4()

    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=advertiser_id,
            telegram_id="adv_custom",
            messenger_type=MessengerType.TELEGRAM,
            username="adv_custom",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now - timedelta(days=30),
            referral_payout_rate=Decimal("0.20"),
        )
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=advertiser_id,
            created_at=now - timedelta(days=30),
        )
    )
    pricing_repo = InMemoryContactPricingRepository()
    await pricing_repo.save(
        ContactPricing(
            country_code="ru",
            bloggers_count=3,
            price=Decimal("9000"),
            currency="RUB",
            updated_at=now,
        )
    )
    payment_repo = InMemoryPaymentRepository()
    await payment_repo.save(
        Payment(
            payment_id=uuid4(),
            order_id=order_id,
            provider="test",
            status=PaymentStatus.PAID,
            amount=9000.0,
            currency="RUB",
            external_id="ext_adv_custom",
            created_at=now,
        )
    )
    entry_repo = InMemoryReferralIncomeEntryRepository()

    order = Order(
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

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=payment_repo,
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
        contact_pricing_repo=pricing_repo,
    )

    await service.record_advertiser_referral_income(
        order=order,
        advertiser_id=advertiser_id,
        advertiser_country_code="ru",
    )

    assert len(entry_repo.entries) == 1
    entry = entry_repo.entries[0]
    assert entry.commission_rate == Decimal("0.20")
    # platform_revenue = payment.amount = 9000
    # commission = 9000 * 0.20 = 1800.00
    assert entry.commission_amount == Decimal("1800.00")


@pytest.mark.asyncio
async def test_record_creator_zero_bloggers_skips() -> None:
    """Creator income skipped when bloggers_needed is 0."""
    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    creator_id = uuid4()
    order_id = uuid4()

    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=creator_id,
            telegram_id="c_zero",
            messenger_type=MessengerType.TELEGRAM,
            username="c_zero",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now - timedelta(days=30),
        )
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=creator_id,
            created_at=now,
        )
    )
    pricing_repo = InMemoryContactPricingRepository()
    await pricing_repo.save(
        ContactPricing(
            country_code="ru",
            bloggers_count=0,
            price=Decimal("5000"),
            currency="RUB",
            updated_at=now,
        )
    )
    payment_repo = InMemoryPaymentRepository()
    await payment_repo.save(
        Payment(
            payment_id=uuid4(),
            order_id=order_id,
            provider="test",
            status=PaymentStatus.PAID,
            amount=5000.0,
            currency="RUB",
            external_id="ext_zero",
            created_at=now,
        )
    )
    entry_repo = InMemoryReferralIncomeEntryRepository()

    order = Order(
        order_id=order_id,
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://x.com",
        offer_text="Offer",
        barter_description=None,
        price=5000.0,
        bloggers_needed=0,
        status=OrderStatus.CLOSED,
        created_at=now,
        completed_at=now,
    )

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=payment_repo,
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
        contact_pricing_repo=pricing_repo,
    )

    await service.record_creator_referral_income(
        order=order,
        creator_id=creator_id,
        advertiser_country_code="ru",
    )

    assert len(entry_repo.entries) == 0


@pytest.mark.asyncio
async def test_cancelled_payout_does_not_block_same_day_request() -> None:
    """CANCELLED payout request today should not block new requests."""
    repo = InMemoryPayoutRequestRepository()
    user_id = uuid4()
    now = datetime.now(timezone.utc)

    cancelled = PayoutRequest(
        request_id=uuid4(),
        user_id=user_id,
        requested_at=now,
        status=PayoutRequestStatus.CANCELLED,
        amount=Decimal("100.00"),
        currency="RUB",
    )
    await repo.save(cancelled)

    result = await repo.has_request_today_by_currency(user_id)
    # CANCELLED should NOT block — should return empty dict
    assert result == {}


@pytest.mark.asyncio
async def test_pending_payout_blocks_same_day_same_currency() -> None:
    """PENDING payout today should block new requests for that currency."""
    repo = InMemoryPayoutRequestRepository()
    user_id = uuid4()
    now = datetime.now(timezone.utc)

    pending = PayoutRequest(
        request_id=uuid4(),
        user_id=user_id,
        requested_at=now,
        status=PayoutRequestStatus.PENDING,
        amount=Decimal("100.00"),
        currency="RUB",
    )
    await repo.save(pending)

    result = await repo.has_request_today_by_currency(user_id)
    assert result == {"RUB": True}


@pytest.mark.asyncio
async def test_duplicate_active_payout_request_same_day_raises() -> None:
    """Duplicate active payout request for same user+currency+day must fail."""
    repo = InMemoryPayoutRequestRepository()
    user_id = uuid4()
    now = datetime.now(timezone.utc)

    req1 = PayoutRequest(
        request_id=uuid4(),
        user_id=user_id,
        requested_at=now,
        status=PayoutRequestStatus.PENDING,
        amount=Decimal("500.00"),
        currency="RUB",
    )
    req2 = PayoutRequest(
        request_id=uuid4(),
        user_id=user_id,
        requested_at=now,
        status=PayoutRequestStatus.PENDING,
        amount=Decimal("500.00"),
        currency="RUB",
    )
    await repo.save(req1)
    with pytest.raises(ValueError):
        await repo.save(req2)


@pytest.mark.asyncio
async def test_cancelled_then_new_payout_same_day_allowed() -> None:
    """After CANCELLED request, a new request on same day is allowed."""
    repo = InMemoryPayoutRequestRepository()
    user_id = uuid4()
    now = datetime.now(timezone.utc)

    cancelled = PayoutRequest(
        request_id=uuid4(),
        user_id=user_id,
        requested_at=now,
        status=PayoutRequestStatus.CANCELLED,
        amount=Decimal("500.00"),
        currency="RUB",
    )
    new_req = PayoutRequest(
        request_id=uuid4(),
        user_id=user_id,
        requested_at=now,
        status=PayoutRequestStatus.PENDING,
        amount=Decimal("500.00"),
        currency="RUB",
    )
    await repo.save(cancelled)
    # Should NOT raise
    await repo.save(new_req)
    assert new_req.request_id in repo._requests


@pytest.mark.asyncio
async def test_batch_balances_use_income_entries() -> None:
    """get_referral_balances_batch uses income_entries, not loader."""
    from ugc_bot.application.services.referral_stats_service import (
        ReferralStatsService,
    )
    from ugc_bot.domain.entities import ReferralIncomeEntry

    referrer_id = uuid4()
    referred_id = uuid4()
    order_id = uuid4()
    now = datetime.now(timezone.utc)

    entry_repo = InMemoryReferralIncomeEntryRepository()
    await entry_repo.save(
        ReferralIncomeEntry(
            entry_id=uuid4(),
            referrer_user_id=referrer_id,
            referred_user_id=referred_id,
            order_id=order_id,
            income_type=ReferralIncomeType.CREATOR,
            currency="RUB",
            platform_revenue=Decimal("1000.00"),
            commission_rate=Decimal("0.10"),
            commission_amount=Decimal("100.00"),
            created_at=now,
        )
    )

    service = ReferralStatsService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
    )

    result = await service.get_referral_balances_batch([referrer_id])

    assert referrer_id in result
    income_total, paid_total = result[referrer_id]
    assert income_total == 100.0
    assert paid_total == 0.0


@pytest.mark.asyncio
async def test_get_user_referral_stats_uses_income_entries() -> None:
    """get_user_referral_stats uses income_entries as primary path."""
    from ugc_bot.application.services.referral_stats_service import (
        ReferralStatsService,
    )
    from ugc_bot.domain.entities import ReferralIncomeEntry

    referrer_id = uuid4()
    referred_id = uuid4()
    now = datetime.now(timezone.utc)

    entry_repo = InMemoryReferralIncomeEntryRepository()
    await entry_repo.save(
        ReferralIncomeEntry(
            entry_id=uuid4(),
            referrer_user_id=referrer_id,
            referred_user_id=referred_id,
            order_id=uuid4(),
            income_type=ReferralIncomeType.CREATOR,
            currency="RUB",
            platform_revenue=Decimal("500.00"),
            commission_rate=Decimal("0.10"),
            commission_amount=Decimal("50.00"),
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

    service = ReferralStatsService(
        user_referral_binding_repo=binding_repo,
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
    )

    stats = await service.get_user_referral_stats(referrer_id)
    assert stats.creators_count == 1
    assert stats.income_total == 50.0
    assert stats.orders_count == 1
    assert stats.paid_total == 0.0


@pytest.mark.asyncio
async def test_record_creator_no_payment_skips() -> None:
    """Binding and pricing exist but no payment — entry not created."""
    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    creator_id = uuid4()

    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=creator_id,
            telegram_id="c_nopay",
            messenger_type=MessengerType.TELEGRAM,
            username="c_nopay",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now - timedelta(days=30),
        )
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=creator_id,
            created_at=now,
        )
    )
    pricing_repo = InMemoryContactPricingRepository()
    await pricing_repo.save(
        ContactPricing(
            country_code="ru",
            bloggers_count=3,
            price=Decimal("9000"),
            currency="RUB",
            updated_at=now,
        )
    )
    entry_repo = InMemoryReferralIncomeEntryRepository()

    order = Order(
        order_id=uuid4(),
        advertiser_id=uuid4(),
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

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
        contact_pricing_repo=pricing_repo,
    )

    await service.record_creator_referral_income(
        order=order,
        creator_id=creator_id,
        advertiser_country_code="ru",
    )

    assert len(entry_repo.entries) == 0


@pytest.mark.asyncio
async def test_record_advertiser_no_payment_skips() -> None:
    """Binding and pricing exist but no payment — entry not created."""
    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    advertiser_id = uuid4()

    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=advertiser_id,
            telegram_id="adv_nopay",
            messenger_type=MessengerType.TELEGRAM,
            username="adv_nopay",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now - timedelta(days=30),
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
    pricing_repo = InMemoryContactPricingRepository()
    await pricing_repo.save(
        ContactPricing(
            country_code="ru",
            bloggers_count=3,
            price=Decimal("9000"),
            currency="RUB",
            updated_at=now,
        )
    )
    entry_repo = InMemoryReferralIncomeEntryRepository()

    order = Order(
        order_id=uuid4(),
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

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
        contact_pricing_repo=pricing_repo,
    )

    await service.record_advertiser_referral_income(
        order=order,
        advertiser_id=advertiser_id,
        advertiser_country_code="ru",
    )

    assert len(entry_repo.entries) == 0


@pytest.mark.asyncio
async def test_commission_rate_uses_registration_date_not_binding_date() -> (
    None
):
    """Commission rate uses user registration date, not binding date.

    User registered 2 years ago → gets 3% (based on user.created_at).
    Binding created 6 months ago → irrelevant for rate calculation.
    """
    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    creator_id = uuid4()
    advertiser_id = uuid4()
    order_id = uuid4()

    # User registered 2 years ago → should get 3%
    user_repo = InMemoryUserRepository()
    await user_repo.save(
        User(
            user_id=creator_id,
            telegram_id="old_creator",
            messenger_type=MessengerType.TELEGRAM,
            username="old_creator",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now - timedelta(days=730),  # 2 years ago
        )
    )

    # Binding created only 6 months ago — irrelevant for rate
    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=creator_id,
            created_at=now - timedelta(days=180),  # 6 months ago
        )
    )

    pricing_repo = InMemoryContactPricingRepository()
    await pricing_repo.save(
        ContactPricing(
            country_code="ru",
            bloggers_count=1,
            price=Decimal("3000"),
            currency="RUB",
            updated_at=now,
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
            external_id="ext_binding_date",
            created_at=now,
        )
    )
    entry_repo = InMemoryReferralIncomeEntryRepository()

    order = Order(
        order_id=order_id,
        advertiser_id=advertiser_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://x.com",
        offer_text="Offer",
        barter_description=None,
        price=3000.0,
        bloggers_needed=1,
        status=OrderStatus.CLOSED,
        created_at=now,
        completed_at=now,
    )

    service = ReferralIncomeService(
        user_referral_binding_repo=binding_repo,
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=payment_repo,
        interaction_repo=InMemoryInteractionRepository(),
        user_repo=user_repo,
        payout_request_repo=InMemoryPayoutRequestRepository(),
        transaction_manager=None,
        referral_income_entry_repo=entry_repo,
        contact_pricing_repo=pricing_repo,
    )

    await service.record_creator_referral_income(
        order=order,
        creator_id=creator_id,
        advertiser_country_code="ru",
    )

    assert len(entry_repo.entries) == 1
    entry = entry_repo.entries[0]
    # User registered 2 years ago → after-first-year rate (3%)
    assert entry.commission_rate == Decimal("0.03")


def test_aggregate_cancelled_does_not_set_has_request_today() -> None:
    """CANCELLED request today should not set has_request_today=True."""
    from ugc_bot.application.services.referral_commission import (
        aggregate_payout_requests,
    )

    now = datetime.now(timezone.utc)
    requests = [
        PayoutRequest(
            request_id=uuid4(),
            user_id=uuid4(),
            requested_at=now,
            status=PayoutRequestStatus.CANCELLED,
            amount=Decimal("100"),
            currency="RUB",
        ),
    ]
    _, _, has_request_today, _ = aggregate_payout_requests(requests, now)
    assert has_request_today is False


def test_aggregate_payout_requests_returns_paid_by_currency() -> None:
    """aggregate_payout_requests should return per-currency paid breakdown."""
    from datetime import datetime, timezone
    from decimal import Decimal
    from uuid import uuid4

    from ugc_bot.application.services.referral_commission import (
        aggregate_payout_requests,
    )
    from ugc_bot.domain.entities import PayoutRequest
    from ugc_bot.domain.enums import PayoutRequestStatus

    now = datetime.now(timezone.utc)
    uid = uuid4()
    requests = [
        PayoutRequest(
            request_id=uuid4(),
            user_id=uid,
            requested_at=now,
            status=PayoutRequestStatus.PAID,
            amount=Decimal("100"),
            currency="USD",
        ),
        PayoutRequest(
            request_id=uuid4(),
            user_id=uid,
            requested_at=now,
            status=PayoutRequestStatus.PAID,
            amount=Decimal("5000"),
            currency="RUB",
        ),
    ]
    paid_total, has_pending, has_request_today, paid_by_currency = (
        aggregate_payout_requests(requests, now)
    )
    assert paid_by_currency == {"USD": 100.0, "RUB": 5000.0}
    assert paid_total == 5100.0


@pytest.mark.asyncio
async def test_compute_income_from_loader_uses_decimal_precision() -> None:
    """Loader fallback should produce same result as Decimal arithmetic."""
    from datetime import datetime, timedelta, timezone
    from unittest.mock import AsyncMock, MagicMock
    from uuid import uuid4

    from ugc_bot.application.services.referral_stats_service import (
        ReferralStatsService,
    )
    from ugc_bot.domain.entities import ReferralOrderIncomeRow
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryOfferDispatchRepository,
        InMemoryOrderRepository,
        InMemoryPaymentRepository,
        InMemoryPayoutRequestRepository,
        InMemoryUserReferralBindingRepository,
        InMemoryUserRepository,
    )

    now = datetime.now(timezone.utc)
    order_id = uuid4()
    row = ReferralOrderIncomeRow(
        creator_created_at=now - timedelta(days=30),
        order_completed_at=now,
        payment_amount=333.0,
        bloggers_needed=3,
        order_id=order_id,
    )

    loader = MagicMock()
    loader.load_referral_order_income_rows_combined = AsyncMock(
        return_value=[row]
    )

    service = ReferralStatsService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=MagicMock(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=InMemoryPayoutRequestRepository(),
        referral_order_income_loader=loader,
    )

    session = MagicMock()
    (
        income_cm,
        income_total,
        orders_count,
    ) = await service._compute_income_from_loader(
        uuid4(), limit=100, now=now, session=session
    )
    assert income_total == 11.1
    assert orders_count == 1


@pytest.mark.asyncio
async def test_income_entry_exists_returns_true_when_present() -> None:
    """exists() should return True when entry already recorded."""
    from datetime import datetime, timezone
    from decimal import Decimal
    from uuid import uuid4

    from ugc_bot.domain.entities import ReferralIncomeEntry
    from ugc_bot.domain.enums import ReferralIncomeType
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryReferralIncomeEntryRepository,
    )

    repo = InMemoryReferralIncomeEntryRepository()
    referrer_id = uuid4()
    order_id = uuid4()

    entry = ReferralIncomeEntry(
        entry_id=uuid4(),
        referrer_user_id=referrer_id,
        referred_user_id=uuid4(),
        order_id=order_id,
        income_type=ReferralIncomeType.CREATOR,
        currency="RUB",
        platform_revenue=Decimal("1000"),
        commission_rate=Decimal("0.10"),
        commission_amount=Decimal("100"),
        created_at=datetime.now(timezone.utc),
    )
    await repo.save(entry)

    assert await repo.exists(order_id, referrer_id, "creator") is True
    assert await repo.exists(order_id, referrer_id, "advertiser") is False
    assert await repo.exists(uuid4(), referrer_id, "creator") is False


@pytest.mark.asyncio
async def test_record_creator_skips_when_already_exists() -> None:
    """record_creator_referral_income should skip if entry already exists."""
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from ugc_bot.application.services.referral_income_recorder import (
        ReferralIncomeRecorder,
    )
    from ugc_bot.domain.entities import (
        Order,
        ReferralIncomeEntry,
        UserReferralBinding,
    )
    from ugc_bot.domain.enums import OrderStatus, OrderType, ReferralIncomeType
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryReferralIncomeEntryRepository,
    )

    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    creator_id = uuid4()
    order_id = uuid4()

    binding = UserReferralBinding(
        referrer_user_id=referrer_id,
        referred_user_id=creator_id,
        created_at=now - timedelta(days=30),
    )
    order = Order(
        order_id=order_id,
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://x.com",
        offer_text="Offer",
        barter_description=None,
        price=100.0,
        bloggers_needed=1,
        status=OrderStatus.CLOSED,
        created_at=now,
        completed_at=now,
    )

    income_repo = InMemoryReferralIncomeEntryRepository()
    entry = ReferralIncomeEntry(
        entry_id=uuid4(),
        referrer_user_id=referrer_id,
        referred_user_id=creator_id,
        order_id=order_id,
        income_type=ReferralIncomeType.CREATOR,
        currency="RUB",
        platform_revenue=Decimal("100"),
        commission_rate=Decimal("0.10"),
        commission_amount=Decimal("10"),
        created_at=now,
    )
    await income_repo.save(entry)

    binding_repo = AsyncMock()
    binding_repo.get_by_referred_user = AsyncMock(return_value=binding)
    user_repo = AsyncMock()
    pricing_repo = AsyncMock()
    payment_repo = AsyncMock()

    recorder = ReferralIncomeRecorder(
        user_referral_binding_repo=binding_repo,
        user_repo=user_repo,
        referral_income_entry_repo=income_repo,
        contact_pricing_repo=pricing_repo,
        payment_repo=payment_repo,
    )

    await recorder.record_creator_referral_income(
        order=order, creator_id=creator_id, advertiser_country_code="ru"
    )

    # Early exit: these repos should NOT be called
    pricing_repo.get_by_bloggers_count.assert_not_called()
    payment_repo.get_by_order.assert_not_called()
    user_repo.get_by_id.assert_not_called()

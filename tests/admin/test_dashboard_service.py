"""Tests for admin dashboard service."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ugc_bot.admin.dashboard_service import (
    AdminDashboardService,
    DelayThresholds,
)
from ugc_bot.domain.enums import (
    OrderStatus,
    OrderType,
    PayoutRequestStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.models import OrderModel, UserModel


class _FakeResult:
    """Fake SQLAlchemy result supporting scalar, all, one_or_none."""

    def __init__(
        self,
        scalar_value=None,
        all_rows=None,
        one_or_none_value=None,
    ) -> None:
        self._scalar = scalar_value
        self._all = all_rows
        self._one_or_none = one_or_none_value

    def scalar(self):
        return self._scalar

    def all(self):
        return self._all if self._all is not None else []

    def one_or_none(self):
        return self._one_or_none


class _FakeSession:
    """Fake async session returning a sequence of results."""

    def __init__(self, results: list) -> None:
        self._results = list(results)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, *_args, **_kwargs):
        if not self._results:
            return _FakeResult(scalar_value=0, all_rows=[])
        return self._results.pop(0)


def _make_session_factory(*results):
    """Create session factory yielding FakeSession with given results."""

    class Factory:
        def __call__(self):
            return _FakeSession(list(results))

    return Factory()


def _make_order(
    order_id=None,
    bloggers_needed=10,
    status=OrderStatus.ACTIVE,
    created_at=None,
    completed_at=None,
) -> OrderModel:
    """Create OrderModel for tests."""
    if created_at is None:
        created_at = datetime.now(timezone.utc) - timedelta(hours=48)
    return OrderModel(
        order_id=order_id or uuid4(),
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Test",
        barter_description=None,
        price=100.0,
        bloggers_needed=bloggers_needed,
        status=status,
        created_at=created_at,
        completed_at=completed_at,
    )


def _make_user(user_id=None, status=UserStatus.ACTIVE) -> UserModel:
    """Create UserModel for tests."""
    return UserModel(
        user_id=user_id or uuid4(),
        external_id="ext1",
        messenger_type="telegram",
        username="user1",
        status=status,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def thresholds() -> DelayThresholds:
    """Default delay thresholds."""
    return DelayThresholds(
        active_days=7,
        no_responses_hours=24,
        low_picked_hours=48,
        archive_days=7,
    )


@pytest.fixture
def service(thresholds) -> AdminDashboardService:
    """Dashboard service with fake session factory."""

    def _factory(results):
        return AdminDashboardService(
            session_factory=_make_session_factory(*results),
            timezone_name="UTC",
            thresholds=thresholds,
        )

    return _factory


@pytest.mark.asyncio
async def test_get_dashboard_returns_structure(service) -> None:
    """get_dashboard returns expected structure."""
    results = [
        _FakeResult(scalar_value=2),
        _FakeResult(scalar_value=1),
        _FakeResult(scalar_value=3),
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
    ]
    svc = service(results)
    data = await svc.get_dashboard("today")
    assert data["period"] == "today"
    assert "registrations" in data
    assert "creators" in data["registrations"]
    assert "advertisers" in data["registrations"]
    assert data["registrations"]["creators"]["count"] == 2
    assert data["registrations"]["creators"]["change_pct"] == 100.0  # 1->2
    assert data["registrations"]["advertisers"]["count"] == 3
    assert "orders" in data
    assert "problems" in data
    assert "open_complaints" in data["problems"]
    assert "delays" in data["problems"]
    assert "delayed_orders" in data
    assert "referrals" in data
    assert "referrers" in data["referrals"]
    assert "total_earned" in data["referrals"]
    assert "total_balance" in data["referrals"]
    assert "payout_requests" in data


@pytest.mark.asyncio
async def test_get_dashboard_includes_referral_referrers(service) -> None:
    """get_dashboard includes referral analytics per referrer."""
    ref_user_id = uuid4()
    ref_row = SimpleNamespace(
        user_id=ref_user_id,
        username="manager1",
        referral_code="mgr1",
        total_referred=5,
        referred_creators=3,
        referred_advertisers=2,
        new_in_period=1,
    )
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[ref_row]),
        _FakeResult(all_rows=[]),
    ]
    svc = service(results)
    data = await svc.get_dashboard("today")
    referrers = data["referrals"]["referrers"]
    assert len(referrers) == 1
    assert referrers[0]["username"] == "manager1"
    assert referrers[0]["referral_code"] == "mgr1"
    assert referrers[0]["total_referred"] == 5
    assert referrers[0]["referred_creators"] == 3
    assert referrers[0]["referred_advertisers"] == 2
    assert referrers[0]["new_in_period"] == 1
    assert "balance" in referrers[0]
    assert referrers[0]["balance"] is None  # no referral_income_service in test
    assert data["referrals"]["total_earned"] is None
    assert data["referrals"]["total_balance"] is None


@pytest.mark.asyncio
async def test_get_dashboard_includes_payout_requests(service) -> None:
    """get_dashboard includes payout requests list."""
    req_id = uuid4()
    payout_row = SimpleNamespace(
        request_id=req_id,
        user_id=uuid4(),
        username="referrer1",
        requested_at=datetime.now(timezone.utc),
        status=PayoutRequestStatus.PENDING,
        amount=Decimal("100.50"),
    )
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[payout_row]),
    ]
    svc = service(results)
    data = await svc.get_dashboard("today")
    payouts = data["payout_requests"]
    assert len(payouts) == 1
    assert payouts[0]["username"] == "referrer1"
    assert payouts[0]["status"] == "pending"
    assert payouts[0]["status_label"] == "Ожидает"
    assert payouts[0]["amount"] == 100.50


@pytest.mark.asyncio
async def test_get_dashboard_referrers_balance_and_sort_when_income_service_set(
    thresholds,
) -> None:
    """With referral_income_service, referrers get balance and sort by it."""
    ref_user_id = uuid4()
    ref_row = SimpleNamespace(
        user_id=ref_user_id,
        username="manager1",
        referral_code="mgr1",
        total_referred=5,
        referred_creators=3,
        referred_advertisers=2,
        new_in_period=1,
    )
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[ref_row]),
        _FakeResult(all_rows=[]),
    ]
    mock_income = AsyncMock()
    mock_income.get_user_referral_stats = AsyncMock(
        return_value=SimpleNamespace(income_total=100.0, paid_total=30.0)
    )
    svc = AdminDashboardService(
        session_factory=_make_session_factory(*results),
        timezone_name="UTC",
        thresholds=thresholds,
        referral_income_service=mock_income,
    )
    data = await svc.get_dashboard("today")
    referrers = data["referrals"]["referrers"]
    assert len(referrers) == 1
    assert referrers[0]["balance"] == 70.0
    assert referrers[0]["user_id"] == str(ref_user_id)
    assert data["referrals"]["total_earned"] == 100.0
    assert data["referrals"]["total_balance"] == 70.0


@pytest.mark.asyncio
async def test_get_dashboard_build_delta_previous_zero(service) -> None:
    """When previous count is 0, change_pct is None."""
    results = [
        _FakeResult(scalar_value=5),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=2),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
    ]
    svc = service(results)
    data = await svc.get_dashboard("today")
    assert data["registrations"]["creators"]["change_pct"] is None
    assert data["registrations"]["advertisers"]["change_pct"] is None


@pytest.mark.asyncio
async def test_get_dashboard_order_cards_counts(service) -> None:
    """Order cards aggregate active, completed, archived."""
    order1 = _make_order(bloggers_needed=10, status=OrderStatus.ACTIVE)
    order2 = _make_order(bloggers_needed=5, status=OrderStatus.CLOSED)
    order3 = _make_order(
        bloggers_needed=3,
        status=OrderStatus.CLOSED,
        completed_at=datetime.now(timezone.utc) - timedelta(days=14),
    )
    # responses: order1=2 (active), order2=5 (completed), order3=3 (archived)
    rows = [
        (order1, 2, 0),
        (order2, 5, 0),
        (order3, 3, 0),
    ]
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=rows),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
    ]
    svc = service(results)
    data = await svc.get_dashboard("today")
    assert data["orders"]["active"] == 1
    assert data["orders"]["completed"] == 1
    assert data["orders"]["archived"] == 1


@pytest.mark.asyncio
async def test_build_period_window_today(service) -> None:
    """_build_period_window for today."""
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
    ]
    svc = service(results)
    data = await svc.get_dashboard("today")
    assert data["period"] == "today"


@pytest.mark.asyncio
async def test_build_period_window_yesterday(service) -> None:
    """_build_period_window for yesterday."""
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
    ]
    svc = service(results)
    data = await svc.get_dashboard("yesterday")
    assert data["period"] == "yesterday"


@pytest.mark.asyncio
async def test_build_period_window_7d(service) -> None:
    """_build_period_window for 7d."""
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
    ]
    svc = service(results)
    data = await svc.get_dashboard("7d")
    assert data["period"] == "7d"


@pytest.mark.asyncio
async def test_build_period_window_30d(service) -> None:
    """_build_period_window for 30d."""
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
    ]
    svc = service(results)
    data = await svc.get_dashboard("30d")
    assert data["period"] == "30d"


@pytest.mark.asyncio
async def test_build_period_window_raises_for_invalid(service) -> None:
    """_build_period_window raises for invalid period."""
    svc = service([])
    with pytest.raises(ValueError, match="Unsupported period"):
        svc._build_period_window("invalid")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_list_creators(service) -> None:
    """list_creators returns creator rows."""
    user = _make_user()
    rows = [
        (
            user,
            "https://instagram.com/u1",
            5,
            1,
        ),
    ]
    results = [_FakeResult(all_rows=rows)]
    svc = service(results)
    creators = await svc.list_creators(
        "today", only_new=False, only_with_complaints=False
    )
    assert len(creators) == 1
    assert creators[0]["username"] == "user1"
    assert creators[0]["instagram"] == "https://instagram.com/u1"
    assert creators[0]["responses"] == 5
    assert creators[0]["complaints"] == 1
    assert creators[0]["status"] in ("active", "limited")


@pytest.mark.asyncio
async def test_list_advertisers(service) -> None:
    """list_advertisers returns advertiser rows."""
    user = _make_user()
    rows = [
        (user, "Brand", 10, 5, 0),
    ]
    results = [_FakeResult(all_rows=rows)]
    svc = service(results)
    advertisers = await svc.list_advertisers()
    assert len(advertisers) == 1
    assert advertisers[0]["name"] == "Brand"
    assert advertisers[0]["orders_total"] == 10
    assert advertisers[0]["orders_completed"] == 5
    assert advertisers[0]["complaints"] == 0


@pytest.mark.asyncio
async def test_list_orders(service) -> None:
    """list_orders returns order rows with status labels."""
    order = _make_order()
    rows = [
        (order, 3, 0, "Advertiser1"),
    ]
    results = [_FakeResult(all_rows=rows)]
    svc = service(results)
    orders = await svc.list_orders("today", status_filter=None)
    assert len(orders) == 1
    assert orders[0]["order_id"] == str(order.order_id)
    assert orders[0]["advertiser"] == "Advertiser1"
    assert orders[0]["status_label"] in (
        "active",
        "completed",
        "archive",
        "complaint",
    )
    assert orders[0]["picked_count"] == 3
    assert orders[0]["needed_count"] == order.bloggers_needed
    assert "status_age_hours" in orders[0]
    assert "has_problem" in orders[0]


@pytest.mark.asyncio
async def test_list_orders_with_status_filter(service) -> None:
    """list_orders filters by status_label when provided."""
    order = _make_order(bloggers_needed=3, status=OrderStatus.CLOSED)
    rows = [(order, 3, 0, "Advertiser")]
    results = [_FakeResult(all_rows=rows)]
    svc = service(results)
    orders = await svc.list_orders("today", status_filter="completed")
    assert len(orders) == 1
    assert orders[0]["status_label"] == "completed"


@pytest.mark.asyncio
async def test_get_order_card_returns_detail(service) -> None:
    """get_order_card returns full order detail."""
    order_id = uuid4()
    order = _make_order(order_id=order_id, bloggers_needed=10)
    row = (order, 5, 0, "Brand Inc")
    results = [_FakeResult(one_or_none_value=row)]
    svc = service(results)
    card = await svc.get_order_card(order_id)
    assert card is not None
    assert card["order_id"] == str(order_id)
    assert card["advertiser"] == "Brand Inc"
    assert card["description"] == "Test"
    assert card["order_type"] == "ugc_only"
    assert card["bloggers_needed"] == 10
    assert card["picked_count"] == 5
    assert card["progress"] == 0.5
    assert card["status_label"] == "active"
    assert "status_age_hours" in card
    assert card["has_problem"] is False


@pytest.mark.asyncio
async def test_get_order_card_returns_none_when_not_found(service) -> None:
    """get_order_card returns None when order not found."""
    results = [_FakeResult(one_or_none_value=None)]
    svc = service(results)
    card = await svc.get_order_card(uuid4())
    assert card is None


@pytest.mark.asyncio
async def test_list_delayed_orders_includes_reasons(
    service, thresholds
) -> None:
    """Delayed orders list includes orders with delay reasons."""
    order = _make_order(
        bloggers_needed=10,
        created_at=datetime.now(timezone.utc) - timedelta(days=8),
    )
    rows = [
        (order, 0, 0, "AdvertiserX"),
    ]
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=rows),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
    ]
    svc = service(results)
    data = await svc.get_dashboard("today")
    assert len(data["delayed_orders"]) >= 1
    delayed = data["delayed_orders"][0]
    assert (
        "active_overdue" in delayed["reasons"]
        or "no_responses" in delayed["reasons"]
    )
    assert delayed["advertiser"] == "AdvertiserX"
    assert delayed["picked_count"] == 0
    assert delayed["needed_count"] == 10


@pytest.mark.asyncio
async def test_count_open_complaints(service) -> None:
    """Open complaints count is included in dashboard."""
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=3),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
    ]
    svc = service(results)
    data = await svc.get_dashboard("today")
    assert data["problems"]["open_complaints"] == 3


@pytest.mark.asyncio
async def test_user_status_label_active(service) -> None:
    """_user_status_label returns active for ACTIVE status."""
    user = _make_user(status=UserStatus.ACTIVE)
    rows = [(user, "url", 0, 0)]
    results = [_FakeResult(all_rows=rows)]
    svc = service(results)
    creators = await svc.list_creators("today", False, False)
    assert creators[0]["status"] == "active"


@pytest.mark.asyncio
async def test_user_status_label_limited(service) -> None:
    """_user_status_label returns limited for non-ACTIVE status."""
    user = _make_user(status=UserStatus.BLOCKED)
    rows = [(user, "url", 0, 0)]
    results = [_FakeResult(all_rows=rows)]
    svc = service(results)
    creators = await svc.list_creators("today", False, False)
    assert creators[0]["status"] == "limited"


@pytest.mark.asyncio
async def test_order_status_complaint_when_open_complaints(service) -> None:
    """Order status is complaint when open_complaints > 0."""
    order = _make_order()
    rows = [(order, 5, 1, "Advertiser")]
    results = [_FakeResult(all_rows=rows)]
    svc = service(results)
    orders = await svc.list_orders("today", None)
    assert orders[0]["status_label"] == "complaint"
    assert orders[0]["has_problem"] is True


@pytest.mark.asyncio
async def test_order_status_completed_when_enough_responses(service) -> None:
    """Order status is completed when picked >= needed."""
    order = _make_order(bloggers_needed=5)
    rows = [(order, 5, 0, "Advertiser")]
    results = [_FakeResult(all_rows=rows)]
    svc = service(results)
    orders = await svc.list_orders("today", None)
    assert orders[0]["status_label"] == "completed"


@pytest.mark.asyncio
async def test_build_delta_negative_change(service) -> None:
    """_build_delta handles negative change."""
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(scalar_value=3),
        _FakeResult(scalar_value=2),
        _FakeResult(scalar_value=4),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
    ]
    svc = service(results)
    data = await svc.get_dashboard("today")
    assert data["registrations"]["creators"]["change_pct"] == pytest.approx(
        -66.67, rel=0.1
    )
    assert data["registrations"]["advertisers"]["change_pct"] == pytest.approx(
        -50.0, rel=0.1
    )


@pytest.mark.asyncio
async def test_progress_ratio_capped_at_one(service) -> None:
    """Progress ratio is capped at 1.0."""
    order = _make_order(bloggers_needed=5)
    row = (order, 10, 0, "Advertiser")
    results = [_FakeResult(one_or_none_value=row)]
    svc = service(results)
    card = await svc.get_order_card(order.order_id)
    assert card is not None
    assert card["progress"] == 1.0


@pytest.mark.asyncio
async def test_advertiser_fallback_to_username_when_no_brand(service) -> None:
    """Advertiser name falls back to username when brand is None."""
    user = _make_user()
    rows = [(user, None, 0, 0, 0)]
    results = [_FakeResult(all_rows=rows)]
    svc = service(results)
    advertisers = await svc.list_advertisers()
    assert advertisers[0]["name"] == "user1"


@pytest.mark.asyncio
async def test_list_creators_only_new_filter(service) -> None:
    """list_creators with only_new=True applies date filter."""
    user = _make_user()
    rows = [(user, "url", 0, 0)]
    results = [_FakeResult(all_rows=rows)]
    svc = service(results)
    creators = await svc.list_creators(
        "today", only_new=True, only_with_complaints=False
    )
    assert len(creators) == 1


@pytest.mark.asyncio
async def test_list_creators_only_with_complaints_filter(service) -> None:
    """list_creators with only_with_complaints=True filters by complaints."""
    user = _make_user()
    rows = [(user, "url", 0, 2)]
    results = [_FakeResult(all_rows=rows)]
    svc = service(results)
    creators = await svc.list_creators(
        "today", only_new=False, only_with_complaints=True
    )
    assert len(creators) == 1
    assert creators[0]["complaints"] == 2


@pytest.mark.asyncio
async def test_is_archived_false_when_open_complaints(service) -> None:
    """Order is not archived when it has open complaints."""
    order = _make_order(
        bloggers_needed=5,
        status=OrderStatus.CLOSED,
        completed_at=datetime.now(timezone.utc) - timedelta(days=14),
    )
    order_rows = [(order, 5, 1)]
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=order_rows),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
    ]
    svc = service(results)
    data = await svc.get_dashboard("today")
    assert data["orders"]["completed"] == 1
    assert data["orders"]["archived"] == 0


@pytest.mark.asyncio
async def test_order_status_archive_when_old_and_no_complaints(service) -> None:
    """Order status is archive when completed, old, and no complaints."""
    order = _make_order(
        bloggers_needed=5,
        status=OrderStatus.CLOSED,
        completed_at=datetime.now(timezone.utc) - timedelta(days=14),
    )
    rows = [(order, 5, 0, "Advertiser")]
    results = [_FakeResult(all_rows=rows)]
    svc = service(results)
    orders = await svc.list_orders("today", None)
    assert orders[0]["status_label"] == "archive"


@pytest.mark.asyncio
async def test_delayed_orders_skips_when_no_reasons(service) -> None:
    """Delayed orders list skips orders with no delay reasons."""
    order = _make_order(
        bloggers_needed=10,
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    rows = [(order, 8, 0, "Advertiser")]
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=rows),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
    ]
    svc = service(results)
    data = await svc.get_dashboard("today")
    assert len(data["delayed_orders"]) == 0


@pytest.mark.asyncio
async def test_progress_ratio_zero_when_needed_zero(service) -> None:
    """Progress ratio returns 0 when needed is 0."""
    order = _make_order(bloggers_needed=0)
    row = (order, 5, 0, "Advertiser")
    results = [_FakeResult(one_or_none_value=row)]
    svc = service(results)
    card = await svc.get_order_card(order.order_id)
    assert card is not None
    assert card["progress"] == 0.0

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
    PaymentStatus,
    PayoutRequestStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.models import OrderModel, UserModel


class _ChartRow:
    """Row-like for chart queries: .day, .amount (turnover), [1] for count."""

    def __init__(self, day, count_or_amount) -> None:
        self.day = day
        self.currency = "RUB"
        self._value = count_or_amount
        self.amount = (
            count_or_amount
            if isinstance(count_or_amount, (Decimal, float))
            else None
        )

    def __getitem__(self, i: int):
        if i == 1:
            return self._value
        raise IndexError(i)


class _FakeResult:
    """Fake SQLAlchemy result supporting scalar, all, one, one_or_none."""

    def __init__(
        self,
        scalar_value=None,
        all_rows=None,
        one_or_none_value=None,
    ) -> None:
        self._scalar = scalar_value
        self._all = all_rows if all_rows is not None else []
        self._one_or_none = one_or_none_value

    def scalar(self):
        return self._scalar

    def all(self):
        return self._all

    def one(self):
        if len(self._all) != 1:
            raise ValueError("one() requires exactly one row")
        return self._all[0]

    def one_or_none(self):
        return self._one_or_none

    def scalars(self):
        """Return object with all() for result.scalars().all()."""
        _all = self._all

        class _ScalarResult:
            def all(self):
                return _all

        return _ScalarResult()


class _FakeSession:
    """Fake async session returning a sequence of results."""

    def __init__(self, results: list) -> None:
        self._results = list(results)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

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
        telegram_id="ext1",
        messenger_type="telegram",
        username="user1",
        status=status,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )


def _order_cards_row(active: int = 0, completed: int = 0, archived: int = 0):
    """Single row for _get_order_cards aggregate query."""
    return SimpleNamespace(
        active=active, completed=completed, archived=archived
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
    creators_by_city_rows = [
        ("Moscow", 5),
        ("Санкт-Петербург", 2),
    ]
    results = [
        _FakeResult(scalar_value=2),
        _FakeResult(scalar_value=1),
        _FakeResult(scalar_value=3),
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=creators_by_city_rows),
        _FakeResult(scalar_value=42),
    ]
    svc = service(results)
    data = await svc.get_dashboard("today")
    assert data["period"] == "today"
    assert data["picked_creators_count"] == 42
    assert data["picked_creators_target"] == 1000
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
    assert "open_complaints_list" in data
    assert "referrals" in data
    assert "referrers" in data["referrals"]
    assert "total_earned" in data["referrals"]
    assert "total_balance" in data["referrals"]
    assert "payout_requests" in data
    assert "turnover_period" in data
    assert "creators_by_city" in data
    assert data["creators_by_city"] == [
        {"city": "Moscow", "count": 5},
        {"city": "Санкт-Петербург", "count": 2},
    ]
    assert "picked_creators_count" in data
    assert "picked_creators_target" in data


@pytest.mark.asyncio
async def test_get_creators_by_city_public_method(service) -> None:
    """get_creators_by_city returns list from session."""
    creators_by_city_rows = [("Moscow", 3), ("SPb", 1)]
    results = [_FakeResult(all_rows=creators_by_city_rows)]
    svc = AdminDashboardService(
        session_factory=_make_session_factory(*results),
        timezone_name="UTC",
        thresholds=DelayThresholds(
            active_days=7,
            no_responses_hours=24,
            low_picked_hours=48,
            archive_days=7,
        ),
    )
    out = await svc.get_creators_by_city()
    assert out == [{"city": "Moscow", "count": 3}, {"city": "SPb", "count": 1}]


@pytest.mark.asyncio
async def test_get_creators_by_city_returns_sorted_and_handles_empty_city(
    service,
) -> None:
    """creators_by_city sorted by count desc; empty city in payload."""
    creators_by_city_rows = [
        ("Moscow", 10),
        ("", 3),
        ("Казань", 2),
    ]
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=creators_by_city_rows),
        _FakeResult(scalar_value=0),
    ]
    svc = service(results)
    data = await svc.get_dashboard("today")
    by_city = data["creators_by_city"]
    assert len(by_city) == 3
    assert by_city[0] == {"city": "Moscow", "count": 10}
    assert by_city[1] == {"city": "", "count": 3}
    assert by_city[2] == {"city": "Казань", "count": 2}


@pytest.mark.asyncio
async def test_get_dashboard_includes_referral_referrers(service) -> None:
    """get_dashboard includes referral analytics per referrer."""
    ref_user_id = uuid4()
    ref_row = SimpleNamespace(
        user_id=ref_user_id,
        username="manager1",
        telegram="@manager1",
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
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[ref_row]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
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
        telegram="@referrer1",
        requested_at=datetime.now(timezone.utc),
        status=PayoutRequestStatus.PENDING,
        currency="RUB",
        amount=Decimal("100.50"),
    )
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[payout_row]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
    ]
    svc = service(results)
    data = await svc.get_dashboard("today")
    payouts = data["payout_requests"]
    assert len(payouts) == 1
    assert payouts[0]["username"] == "referrer1"
    assert payouts[0]["telegram"] == "@referrer1"
    assert payouts[0]["status"] == "pending"
    assert payouts[0]["status_label"] == "Ожидает"
    assert payouts[0]["amount"] == 100.50


@pytest.mark.asyncio
async def test_get_user_card_returns_none_for_unknown_user(service) -> None:
    """get_user_card returns None when user does not exist."""
    svc = service([_FakeResult(one_or_none_value=None)])
    card = await svc.get_user_card(uuid4())
    assert card is None


@pytest.mark.asyncio
async def test_get_user_card_returns_user_data(service) -> None:
    """get_user_card returns user dict with all fields when user exists."""
    uid = uuid4()
    created = datetime.now(timezone.utc)
    user_ns = SimpleNamespace(
        user_id=uid,
        telegram_id="ext123",
        max_id=None,
        messenger_type=SimpleNamespace(value="telegram"),
        username="john",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=created,
        role_chosen_at=None,
        last_role_reminder_at=None,
        telegram="@john",
        admin=False,
        referral_code="ref1",
    )
    svc = service([_FakeResult(one_or_none_value=(user_ns, None, None))])
    card = await svc.get_user_card(uid)
    assert card is not None
    assert card["user_id"] == str(uid)
    assert card["username"] == "john"
    assert card["telegram"] == "@john"
    assert card["telegram_id"] == "ext123"
    assert card["referral_code"] == "ref1"
    assert card["blogger_profile"] is None
    assert card["advertiser_profile"] is None


@pytest.mark.asyncio
async def test_get_user_card_includes_blogger_and_advertiser_profiles(
    service,
) -> None:
    """get_user_card includes blogger and advertiser profiles when present."""
    uid = uuid4()
    created = datetime.now(timezone.utc)
    user_ns = SimpleNamespace(
        user_id=uid,
        telegram_id="ext1",
        max_id=None,
        messenger_type=SimpleNamespace(value="telegram"),
        username="jane",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=created,
        role_chosen_at=created,
        last_role_reminder_at=None,
        telegram="@jane",
        admin=False,
        referral_code=None,
    )
    blogger_ns = SimpleNamespace(
        instagram_url="https://instagram.com/jane",
        confirmed=True,
        city="Moscow",
        topics={"fashion": True},
        audience_gender=SimpleNamespace(value="female"),
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="RU",
        price=100.0,
        barter=True,
        work_format=SimpleNamespace(value="ugc_only"),
        wanted_to_change_terms_count=0,
        updated_at=created,
    )
    advertiser_ns = SimpleNamespace(
        contact="+79001234567",
        brand="Brand",
        site_link="https://brand.com",
        city="SPB",
        company_activity="Retail",
    )
    svc = service(
        [_FakeResult(one_or_none_value=(user_ns, blogger_ns, advertiser_ns))]
    )
    card = await svc.get_user_card(uid)
    assert card is not None
    assert card["username"] == "jane"
    assert card["blogger_profile"] is not None
    assert card["blogger_profile"]["instagram_url"] == blogger_ns.instagram_url
    assert card["blogger_profile"]["city"] == "Moscow"
    assert card["advertiser_profile"] is not None
    assert card["advertiser_profile"]["contact"] == "+79001234567"
    assert card["advertiser_profile"]["brand"] == "Brand"


@pytest.mark.asyncio
async def test_get_dashboard_referrers_balance_and_sort_when_income_service_set(
    thresholds,
) -> None:
    """With referral_income_service, referrers get balance and sort by it."""
    ref_user_id = uuid4()
    ref_row = SimpleNamespace(
        user_id=ref_user_id,
        username="manager1",
        telegram="@manager1",
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
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[ref_row]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
    ]
    mock_income = AsyncMock()
    mock_income.get_referral_balances_batch = AsyncMock(
        return_value={ref_user_id: (100.0, 30.0)}
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
async def test_get_dashboard_filter_top_by_balance_enriches_all(
    thresholds,
) -> None:
    """With referrers_filter=top_by_balance we enrich all then filter."""
    ref_user_id = uuid4()
    ref_row = SimpleNamespace(
        user_id=ref_user_id,
        username="ref1",
        telegram="@ref1",
        referral_code="r1",
        total_referred=2,
        referred_creators=1,
        referred_advertisers=1,
        new_in_period=0,
    )
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[ref_row]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
    ]
    mock_income = AsyncMock()
    mock_income.get_referral_balances_batch = AsyncMock(
        return_value={ref_user_id: (50.0, 10.0)}
    )
    svc = AdminDashboardService(
        session_factory=_make_session_factory(*results),
        timezone_name="UTC",
        thresholds=thresholds,
        referral_income_service=mock_income,
    )
    data = await svc.get_dashboard("today", referrers_filter="top_by_balance")
    referrers = data["referrals"]["referrers"]
    assert len(referrers) == 1
    assert referrers[0]["balance"] == 40.0
    assert data["referrals"]["total_earned"] == 50.0
    assert data["referrals"]["total_balance"] == 40.0
    mock_income.get_referral_balances_batch.assert_called_once()


@pytest.mark.asyncio
async def test_get_dashboard_filter_top_by_balance_no_service(
    thresholds,
) -> None:
    """top_by_balance with no income service: balance None, filter yields 0."""
    ref_user_id = uuid4()
    ref_row = SimpleNamespace(
        user_id=ref_user_id,
        username="ref1",
        telegram="@ref1",
        referral_code="r1",
        total_referred=1,
        referred_creators=1,
        referred_advertisers=0,
        new_in_period=0,
    )
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[ref_row]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
    ]
    svc = AdminDashboardService(
        session_factory=_make_session_factory(*results),
        timezone_name="UTC",
        thresholds=thresholds,
        referral_income_service=None,
    )
    data = await svc.get_dashboard("today", referrers_filter="top_by_balance")
    referrers = data["referrals"]["referrers"]
    assert data["referrals"]["referrers_total"] == 0
    assert len(referrers) == 0


@pytest.mark.asyncio
async def test_get_dashboard_filter_top_by_balance_zero_referrers(
    thresholds,
) -> None:
    """top_by_balance with 0 referrers from query hits early return."""
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
    ]
    svc = AdminDashboardService(
        session_factory=_make_session_factory(*results),
        timezone_name="UTC",
        thresholds=thresholds,
        referral_income_service=AsyncMock(),
    )
    data = await svc.get_dashboard("today", referrers_filter="top_by_balance")
    assert data["referrals"]["referrers_total"] == 0
    assert data["referrals"]["referrers"] == []


@pytest.mark.asyncio
async def test_is_archived_with_open_complaints_returns_false(
    thresholds,
) -> None:
    """_is_archived returns False when open_complaints > 0."""
    svc = AdminDashboardService(
        session_factory=_make_session_factory(),
        timezone_name="UTC",
        thresholds=thresholds,
    )
    order = _make_order(
        status=OrderStatus.CLOSED,
        completed_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    assert (
        svc._is_archived(order, is_completed=True, open_complaints=1) is False
    )


@pytest.mark.asyncio
async def test_get_dashboard_include_timings(service) -> None:
    """With include_timings=True, result includes _timings_ms."""
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
    ]
    svc = service(results)
    data = await svc.get_dashboard("today", include_timings=True)
    assert "_timings_ms" in data
    assert "enrich_referrers" in data["_timings_ms"]


@pytest.mark.asyncio
async def test_get_dashboard_build_delta_previous_zero(service) -> None:
    """When previous count is 0, change_pct is None."""
    results = [
        _FakeResult(scalar_value=5),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=2),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
    ]
    svc = service(results)
    data = await svc.get_dashboard("today")
    assert data["registrations"]["creators"]["change_pct"] is None
    assert data["registrations"]["advertisers"]["change_pct"] is None


@pytest.mark.asyncio
async def test_get_dashboard_order_cards_counts(service) -> None:
    """Order cards: active/completed/archived from single aggregate row."""
    # _get_order_cards now returns one row: (active, completed, archived)
    order_cards_row = SimpleNamespace(active=1, completed=1, archived=1)
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[order_cards_row]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
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
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
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
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
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
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
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
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
    ]
    svc = service(results)
    data = await svc.get_dashboard("30d")
    assert data["period"] == "30d"


@pytest.mark.asyncio
async def test_build_period_window_all(service) -> None:
    """_build_period_window for all returns epoch start and no
    previous range."""
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
    ]
    svc = service(results)
    data = await svc.get_dashboard("all")
    assert data["period"] == "all"
    window = svc._build_period_window("all")
    assert window.current_start.year == 2000
    assert window.previous_start == window.previous_end


@pytest.mark.asyncio
async def test_build_period_window_raises_for_invalid(service) -> None:
    """_build_period_window raises for invalid period."""
    svc = service([])
    with pytest.raises(ValueError, match="Unsupported period"):
        svc._build_period_window("invalid")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_list_creators(service) -> None:
    """list_creators returns creator rows with city."""
    user = _make_user()
    rows = [
        (
            user,
            "https://instagram.com/u1",
            "Moscow",
            None,
            5,
            1,
        ),
    ]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_creators(
        "today", only_new=False, only_with_complaints=False
    )
    assert result["total"] == 1
    assert result["page"] == 1
    assert result["per_page"] == 25
    assert result["total_pages"] == 1
    creators = result["items"]
    assert len(creators) == 1
    assert creators[0]["username"] == "user1"
    assert creators[0]["instagram"] == "https://instagram.com/u1"
    assert creators[0]["city"] == "Moscow"
    assert creators[0]["responses"] == 5
    assert creators[0]["complaints"] == 1
    assert creators[0]["status"] in ("active", "limited")


@pytest.mark.asyncio
async def test_list_advertisers(service) -> None:
    """list_advertisers returns advertiser rows."""
    user = _make_user()
    rows = [
        (user, "Brand", 10, 5, 0, user.created_at),
    ]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_advertisers()
    assert result["total"] == 1
    assert "items" in result
    advertisers = result["items"]
    assert len(advertisers) == 1
    assert advertisers[0]["name"] == "Brand"
    assert advertisers[0]["orders_total"] == 10
    assert advertisers[0]["orders_completed"] == 5
    assert advertisers[0]["last_order_at"] == user.created_at
    assert advertisers[0]["complaints"] == 0


@pytest.mark.asyncio
async def test_list_orders(service) -> None:
    """list_orders returns order rows with status labels."""
    order = _make_order()
    rows = [
        (order, 3, 0, "Advertiser1", "adv1", 3, 3),
    ]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_orders("today", status_filter=None)
    assert result["total"] == 1
    orders = result["items"]
    assert len(orders) == 1
    assert orders[0]["order_id"] == str(order.order_id)
    assert orders[0]["advertiser"] == "Advertiser1"
    assert orders[0]["advertiser_telegram"] == "adv1"
    assert orders[0]["status_label"] in (
        "active",
        "completed",
        "archive",
        "complaint",
    )
    assert orders[0]["picked_count"] == 3
    assert orders[0]["needed_count"] == order.bloggers_needed
    assert orders[0]["dispatched_count"] == 3
    assert orders[0]["accepted_count"] == 3
    assert "status_age_hours" in orders[0]
    assert "has_problem" in orders[0]


@pytest.mark.asyncio
async def test_list_orders_with_status_filter(service) -> None:
    """list_orders filters by status_label when provided."""
    order = _make_order(bloggers_needed=3, status=OrderStatus.CLOSED)
    rows = [(order, 3, 0, "Advertiser", "adv", 3, 3)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_orders("today", status_filter="completed")
    orders = result["items"]
    assert len(orders) == 1
    assert orders[0]["status_label"] == "completed"


@pytest.mark.asyncio
async def test_list_orders_status_filter_complaint_branch(service) -> None:
    """list_orders with status_filter=complaint builds complaint condition."""
    order = _make_order()
    rows = [(order, 1, 1, "Advertiser", "adv", 1, 1)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_orders("today", status_filter="complaint")
    assert result["total"] == 1
    assert result["items"][0]["status_label"] == "complaint"


@pytest.mark.asyncio
async def test_list_orders_status_filter_active_branch(service) -> None:
    """list_orders with status_filter=active builds active SQL condition."""
    order = _make_order()
    rows = [(order, 0, 0, "Advertiser", "adv", 0, 0)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_orders("today", status_filter="active")
    assert len(result["items"]) == 1
    assert result["items"][0]["status_label"] == "active"


@pytest.mark.asyncio
async def test_list_orders_status_filter_archive_branch(service) -> None:
    """list_orders with status_filter=archive builds archive SQL condition."""
    order = _make_order(
        bloggers_needed=5,
        status=OrderStatus.CLOSED,
        completed_at=datetime.now(timezone.utc) - timedelta(days=14),
    )
    rows = [(order, 5, 0, "Advertiser", "adv", 5, 5)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_orders("today", status_filter="archive")
    assert len(result["items"]) == 1
    assert result["items"][0]["status_label"] == "archive"


@pytest.mark.asyncio
async def test_list_orders_status_filter_unknown_returns_none_condition(
    service,
) -> None:
    """list_orders with unknown status_filter applies no extra SQL condition."""
    order = _make_order()
    rows = [(order, 0, 0, "Advertiser", "adv", 0, 0)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_orders("today", status_filter="unknown")
    assert result["total"] == 1
    assert len(result["items"]) == 1


@pytest.mark.asyncio
async def test_get_order_card_returns_detail(service) -> None:
    """get_order_card returns full order detail."""
    order_id = uuid4()
    order = _make_order(order_id=order_id, bloggers_needed=10)
    row = (order, False, 5, 0, "Brand Inc", 5, 5)
    results = [
        _FakeResult(one_or_none_value=row),
        _FakeResult(all_rows=[]),
    ]
    svc = service(results)
    card = await svc.get_order_card(order_id)
    assert card is not None
    assert card["order_id"] == str(order_id)
    assert card["advertiser"] == "Brand Inc"
    assert card["description"] == "Test"
    assert card["order_type"] == "ugc_only"
    assert card["bloggers_needed"] == 10
    assert card["picked_count"] == 5
    assert card["dispatched_count"] == 5
    assert card["accepted_count"] == 5
    assert card["progress"] == 0.5
    assert card["status_label"] == "active"
    assert "status_age_hours" in card
    assert card["has_problem"] is False
    assert card["responses_list"] == []


@pytest.mark.asyncio
async def test_get_order_card_returns_none_when_not_found(service) -> None:
    """get_order_card returns None when order not found."""
    results = [_FakeResult(one_or_none_value=None)]
    svc = service(results)
    card = await svc.get_order_card(uuid4())
    assert card is None


@pytest.mark.asyncio
async def test_get_order_card_includes_eligible_creators_count_for_new_order(
    thresholds,
) -> None:
    """get_order_card includes eligible_creators_count for NEW order."""
    order_id = uuid4()
    order = _make_order(
        order_id=order_id,
        bloggers_needed=5,
        status=OrderStatus.NEW,
    )
    row = (order, True, 0, 0, "Brand", 0, 0)
    mock_dispatch = AsyncMock()
    mock_dispatch.count_eligible_bloggers = AsyncMock(return_value=42)
    svc = AdminDashboardService(
        session_factory=_make_session_factory(
            _FakeResult(one_or_none_value=row),
            _FakeResult(all_rows=[]),
        ),
        timezone_name="UTC",
        thresholds=thresholds,
        offer_dispatch_service=mock_dispatch,
    )
    card = await svc.get_order_card(order_id)
    assert card is not None
    assert card["eligible_creators_count"] == 42
    mock_dispatch.count_eligible_bloggers.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_order_card_eligible_creators_count_none_when_dispatch_raises(
    thresholds,
) -> None:
    """get_order_card sets eligible_creators_count to None when count raises."""
    order_id = uuid4()
    order = _make_order(
        order_id=order_id,
        bloggers_needed=5,
        status=OrderStatus.PENDING_MODERATION,
    )
    row = (order, True, 0, 0, "Brand", 0, 0)
    mock_dispatch = AsyncMock()
    mock_dispatch.count_eligible_bloggers = AsyncMock(
        side_effect=RuntimeError("db error")
    )
    svc = AdminDashboardService(
        session_factory=_make_session_factory(
            _FakeResult(one_or_none_value=row),
            _FakeResult(all_rows=[]),
        ),
        timezone_name="UTC",
        thresholds=thresholds,
        offer_dispatch_service=mock_dispatch,
    )
    card = await svc.get_order_card(order_id)
    assert card is not None
    assert card["eligible_creators_count"] is None


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
        (order, 0, 0, "AdvertiserX", PaymentStatus.PAID, False, False),
        (
            _make_order(status=OrderStatus.NEW, created_at=order.created_at),
            0,
            0,
            "Unpaid advertiser",
            None,
            None,
            True,
        ),
        (
            _make_order(status=OrderStatus.PENDING_MODERATION),
            0,
            0,
            "Moderation advertiser",
            PaymentStatus.PAID,
            None,
            False,
        ),
        (
            _make_order(bloggers_needed=1, created_at=order.created_at),
            1,
            0,
            "Selection complete",
            PaymentStatus.PAID,
            False,
            False,
        ),
    ]
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=rows),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
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
    assert data["problems"]["delays"] == 1
    attention = data["order_attention"]
    assert attention["active"] == 2
    assert attention["unpaid"][0]["advertiser"] == "Unpaid advertiser"
    assert attention["moderation"][0]["reasons"] == ["waiting_moderation"]
    assert delayed["needed_count"] == 10


@pytest.mark.asyncio
async def test_count_open_complaints(service) -> None:
    """Open complaints count is included in dashboard."""
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=3),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
    ]
    svc = service(results)
    data = await svc.get_dashboard("today")
    assert data["problems"]["open_complaints"] == 3


@pytest.mark.asyncio
async def test_user_status_label_active(service) -> None:
    """_user_status_label returns active for ACTIVE status."""
    user = _make_user(status=UserStatus.ACTIVE)
    rows = [(user, "url", "", None, 0, 0)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_creators("today", False, False)
    assert result["items"][0]["status"] == "active"


@pytest.mark.asyncio
async def test_user_status_label_limited(service) -> None:
    """_user_status_label returns limited for non-ACTIVE status."""
    user = _make_user(status=UserStatus.BLOCKED)
    rows = [(user, "url", "", None, 0, 0)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_creators("today", False, False)
    assert result["items"][0]["status"] == "limited"


@pytest.mark.asyncio
async def test_order_status_complaint_when_open_complaints(service) -> None:
    """Order status is complaint when open_complaints > 0."""
    order = _make_order()
    rows = [(order, 5, 1, "Advertiser", "adv", 5, 5)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_orders("today", None)
    orders = result["items"]
    assert orders[0]["status_label"] == "complaint"
    assert orders[0]["has_problem"] is True


@pytest.mark.asyncio
async def test_order_status_completed_when_enough_responses(service) -> None:
    """Order status is completed when picked >= needed."""
    order = _make_order(bloggers_needed=5)
    rows = [(order, 5, 0, "Advertiser", "adv", 5, 5)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_orders("today", None)
    assert result["items"][0]["status_label"] == "completed"


@pytest.mark.asyncio
async def test_build_delta_negative_change(service) -> None:
    """_build_delta handles negative change."""
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(scalar_value=3),
        _FakeResult(scalar_value=2),
        _FakeResult(scalar_value=4),
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
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
    row = (order, False, 10, 0, "Advertiser", 10, 10)
    results = [
        _FakeResult(one_or_none_value=row),
        _FakeResult(all_rows=[]),
    ]
    svc = service(results)
    card = await svc.get_order_card(order.order_id)
    assert card is not None
    assert card["progress"] == 1.0


@pytest.mark.asyncio
async def test_advertiser_fallback_to_username_when_no_brand(service) -> None:
    """Advertiser name falls back to username when brand is None."""
    user = _make_user()
    rows = [(user, None, 0, 0, 0, None)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_advertisers()
    assert result["items"][0]["name"] == "user1"


@pytest.mark.asyncio
async def test_list_creators_only_new_filter(service) -> None:
    """list_creators with only_new=True applies date filter."""
    user = _make_user()
    rows = [(user, "url", "", None, 0, 0)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_creators(
        "today", only_new=True, only_with_complaints=False
    )
    assert len(result["items"]) == 1


@pytest.mark.asyncio
async def test_list_creators_only_with_complaints_filter(service) -> None:
    """list_creators with only_with_complaints=True filters by complaints."""
    user = _make_user()
    rows = [(user, "url", "", None, 0, 2)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_creators(
        "today", only_new=False, only_with_complaints=True
    )
    assert len(result["items"]) == 1
    assert result["items"][0]["complaints"] == 2


@pytest.mark.asyncio
async def test_is_archived_false_when_open_complaints(service) -> None:
    """Order is not archived when it has open complaints."""
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[_order_cards_row(0, 1, 0)]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
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
    rows = [(order, 5, 0, "Advertiser", "adv", 5, 5)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_orders("today", None)
    assert result["items"][0]["status_label"] == "archive"


@pytest.mark.asyncio
async def test_delayed_orders_skips_when_no_reasons(service) -> None:
    """Delayed orders list skips orders with no delay reasons."""
    order = _make_order(
        bloggers_needed=10,
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    rows = [(order, 8, 0, "Advertiser", PaymentStatus.PAID, False, False)]
    results = [
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[_order_cards_row()]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=rows),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
        _FakeResult(all_rows=[]),
        _FakeResult(scalar_value=0),
    ]
    svc = service(results)
    data = await svc.get_dashboard("today")
    assert len(data["delayed_orders"]) == 0


@pytest.mark.asyncio
async def test_progress_ratio_zero_when_needed_zero(service) -> None:
    """Progress ratio returns 0 when needed is 0."""
    order = _make_order(bloggers_needed=0)
    row = (order, False, 5, 0, "Advertiser", 5, 5)
    results = [
        _FakeResult(one_or_none_value=row),
        _FakeResult(all_rows=[]),
    ]
    svc = service(results)
    card = await svc.get_order_card(order.order_id)
    assert card is not None
    assert card["progress"] == 0.0


@pytest.mark.asyncio
async def test_get_dashboard_charts_returns_structure(service) -> None:
    """get_dashboard_charts returns time-series data for all charts."""
    day_creators = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    # Rows: .day and [1] for count; .day and .amount for turnover
    row_reg = _ChartRow(day_creators, 5)
    row_orders = _ChartRow(day_creators, 3)
    row_turnover = _ChartRow(day_creators, Decimal("100.50"))
    results = [
        _FakeResult(all_rows=[row_reg]),
        _FakeResult(all_rows=[row_reg]),
        _FakeResult(all_rows=[row_orders]),
        _FakeResult(all_rows=[row_turnover]),
    ]
    svc = service(results)
    data = await svc.get_dashboard_charts("7d")
    assert "registrations_creators" in data
    assert "registrations_advertisers" in data
    assert "orders" in data
    assert "turnover" in data
    assert len(data["registrations_creators"]) == 1
    assert data["registrations_creators"][0]["date"] == day_creators.strftime(
        "%Y-%m-%d"
    )
    assert data["registrations_creators"][0]["count"] == 5
    assert data["orders"][0]["count"] == 3
    assert data["turnover"][0]["amount"] == 100.5
    assert data["turnover"][0]["currency"] == "RUB"


@pytest.mark.asyncio
async def test_search_users_returns_matches(service) -> None:
    """search_users returns users matching username/telegram."""
    uid = uuid4()
    row = SimpleNamespace(
        user_id=uid,
        username="john",
        telegram="@john",
        telegram_id="123",
        max_id=None,
    )
    svc = service([_FakeResult(all_rows=[row])])
    result = await svc.search_users("john", limit=10)
    assert len(result) == 1
    assert result[0]["user_id"] == str(uid)
    assert result[0]["username"] == "john"
    assert result[0]["telegram"] == "@john"
    assert result[0]["telegram_id"] == "123"


@pytest.mark.asyncio
async def test_search_users_empty_query_returns_empty(service) -> None:
    """search_users returns [] for empty or whitespace query."""
    svc = service([])
    assert await svc.search_users("") == []
    assert await svc.search_users("   ") == []


@pytest.mark.asyncio
async def test_search_users_by_uuid(service) -> None:
    """search_users includes UUID condition when query is valid UUID."""
    uid = uuid4()
    row = SimpleNamespace(
        user_id=uid,
        username="u",
        telegram="@u",
        telegram_id="1",
        max_id=None,
    )
    svc = service([_FakeResult(all_rows=[row])])
    result = await svc.search_users(str(uid))
    assert len(result) == 1
    assert result[0]["user_id"] == str(uid)


@pytest.mark.asyncio
async def test_search_users_by_digit_telegram_id(service) -> None:
    """search_users includes telegram_id when query is digit."""
    uid = uuid4()
    row = SimpleNamespace(
        user_id=uid,
        username="u",
        telegram="@u",
        telegram_id="999",
        max_id=None,
    )
    svc = service([_FakeResult(all_rows=[row])])
    result = await svc.search_users("999")
    assert len(result) == 1
    assert result[0]["telegram_id"] == "999"


@pytest.mark.asyncio
async def test_list_creators_with_sort_and_search(service) -> None:
    """list_creators with sort and search query uses correct params."""
    user = _make_user()
    rows = [(user, "https://instagram.com/u", "", None, 2, 0)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_creators(
        "today",
        only_new=False,
        only_with_complaints=False,
        sort="username",
        order="asc",
        q="john",
    )
    assert result["total"] == 1
    assert result["items"][0]["username"] == "user1"


@pytest.mark.asyncio
async def test_list_advertisers_with_sort_and_search(service) -> None:
    """list_advertisers with sort and search uses correct params."""
    user = _make_user()
    rows = [(user, "Brand", 10, 5, 0, user.created_at)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_advertisers(
        sort="orders_total",
        order="desc",
        q="brand",
    )
    assert result["total"] == 1
    assert result["items"][0]["orders_total"] == 10


@pytest.mark.asyncio
async def test_list_orders_with_sort(service) -> None:
    """list_orders with sort uses correct order column."""
    order = _make_order()
    rows = [(order, 2, 0, "AdvertiserA", "adv_a", 2, 2)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_orders(
        "today",
        status_filter=None,
        sort="advertiser",
        order="asc",
    )
    assert result["total"] == 1
    assert result["items"][0]["advertiser"] == "AdvertiserA"


@pytest.mark.asyncio
async def test_apply_referrers_filter_active_in_period(service) -> None:
    """_apply_referrers_filter keeps only referrers with new_in_period > 0."""
    referrers = [
        {"user_id": "1", "new_in_period": 2, "balance": 0},
        {"user_id": "2", "new_in_period": 0, "balance": 10},
    ]
    filtered = service([])._apply_referrers_filter(
        referrers, "active_in_period"
    )
    assert len(filtered) == 1
    assert filtered[0]["user_id"] == "1"


@pytest.mark.asyncio
async def test_apply_referrers_filter_top_by_balance(service) -> None:
    """_apply_referrers_filter keeps only referrers with balance > 0."""
    referrers = [
        {"user_id": "1", "balance": 50},
        {"user_id": "2", "balance": 0},
    ]
    filtered = service([])._apply_referrers_filter(referrers, "top_by_balance")
    assert len(filtered) == 1
    assert filtered[0]["user_id"] == "1"


@pytest.mark.asyncio
async def test_referrers_filter_default_sort(service) -> None:
    """_referrers_filter_default_sort returns correct key per filter."""
    svc = service([])
    assert (
        svc._referrers_filter_default_sort("top_by_referred")
        == "total_referred"
    )
    assert (
        svc._referrers_filter_default_sort("active_in_period")
        == "new_in_period"
    )
    assert svc._referrers_filter_default_sort("top_by_balance") == "balance"
    assert (
        svc._referrers_filter_default_sort("top_by_earnings_period")
        == "balance"
    )
    assert svc._referrers_filter_default_sort("all") is None


@pytest.mark.asyncio
async def test_sort_referrers_by_balance_and_creators(service) -> None:
    """_sort_referrers sorts by balance and creators."""
    referrers = [
        {"user_id": "a", "balance": 10, "referred_creators": 1},
        {"user_id": "b", "balance": 50, "referred_creators": 2},
    ]
    svc = service([])
    desc = svc._sort_referrers(referrers, "balance", "desc")
    assert desc[0]["user_id"] == "b"
    asc_creators = svc._sort_referrers(referrers, "creators", "asc")
    assert asc_creators[0]["user_id"] == "a"


@pytest.mark.asyncio
async def test_sort_referrers_unknown_key_returns_unchanged(service) -> None:
    """_sort_referrers returns referrers unchanged for unknown sort key."""
    referrers = [{"user_id": "a", "earned_in_period": 10}]
    svc = service([])
    result = svc._sort_referrers(referrers, "earned_in_period", "desc")
    assert result == referrers


@pytest.mark.asyncio
async def test_apply_referrers_filter_top_by_earnings_period(service) -> None:
    """Filter top_by_earnings_period keeps referrers with balance."""
    referrers = [
        {"user_id": "1", "balance": 20},
        {"user_id": "2", "balance": 0},
    ]
    filtered = service([])._apply_referrers_filter(
        referrers, "top_by_earnings_period"
    )
    assert len(filtered) == 1
    assert filtered[0]["user_id"] == "1"


@pytest.mark.asyncio
async def test_list_creators_with_digit_search_hits_user_search_condition(
    service,
) -> None:
    """list_creators with digit q uses _user_search_condition (telegram_id)."""
    user = _make_user()
    rows = [(user, "https://instagram.com/u", "", None, 0, 0)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_creators(
        "today", only_new=False, only_with_complaints=False, q="999"
    )
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_list_orders_sort_picked_count(service) -> None:
    """list_orders with sort=picked_count uses responses coalesce."""
    order = _make_order()
    rows = [(order, 2, 0, "Ad", "ad", 2, 2)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_orders(
        "today", status_filter=None, sort="picked_count", order="desc"
    )
    assert result["items"][0]["picked_count"] == 2


@pytest.mark.asyncio
async def test_list_orders_sort_status_age_hours(service) -> None:
    """list_orders with sort=status_age_hours uses completed_at/created_at."""
    order = _make_order()
    rows = [(order, 1, 0, "Ad", "ad", 1, 1)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_orders(
        "today", status_filter=None, sort="status_age_hours", order="asc"
    )
    assert len(result["items"]) == 1


@pytest.mark.asyncio
async def test_list_advertisers_sort_complaints(service) -> None:
    """list_advertisers with sort=complaints uses complaints column."""
    user = _make_user()
    rows = [(user, "B", 5, 2, 1, None)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_advertisers(sort="complaints", order="desc")
    assert result["items"][0]["complaints"] == 1


@pytest.mark.asyncio
async def test_list_advertisers_sort_orders_completed(service) -> None:
    """list_advertisers with sort=orders_completed uses orders_completed."""
    user = _make_user()
    rows = [(user, "B", 10, 7, 0, None)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_advertisers(sort="orders_completed", order="desc")
    assert result["items"][0]["orders_completed"] == 7


@pytest.mark.asyncio
async def test_apply_referrers_filter_top_by_referred_returns_all(
    service,
) -> None:
    """_apply_referrers_filter with top_by_referred returns all referrers."""
    referrers = [{"user_id": "1", "total_referred": 5}]
    result = service([])._apply_referrers_filter(referrers, "top_by_referred")
    assert result == referrers


@pytest.mark.asyncio
async def test_apply_referrers_filter_unknown_returns_unchanged(
    service,
) -> None:
    """Unknown referrers_filter returns referrers unchanged."""
    referrers = [{"user_id": "1"}]
    result = service([])._apply_referrers_filter(referrers, "unknown")
    assert result == referrers


@pytest.mark.asyncio
async def test_list_creators_sort_responses(service) -> None:
    """list_creators with sort=responses uses responses column."""
    user = _make_user()
    rows = [(user, "https://instagram.com/u", "", None, 10, 0)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_creators(
        "today", False, False, sort="responses", order="desc"
    )
    assert result["items"][0]["responses"] == 10


@pytest.mark.asyncio
async def test_list_creators_sort_complaints(service) -> None:
    """list_creators with sort=complaints uses complaints column."""
    user = _make_user()
    rows = [(user, "url", "", None, 0, 3)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_creators(
        "today", False, False, sort="complaints", order="desc"
    )
    assert result["items"][0]["complaints"] == 3


@pytest.mark.asyncio
async def test_list_creators_unknown_sort_uses_default(service) -> None:
    """list_creators with unknown sort uses default order (created_at desc)."""
    user = _make_user()
    rows = [(user, "url", "", None, 0, 0)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_creators(
        "today", False, False, sort="unknown_sort", order="asc"
    )
    assert len(result["items"]) == 1


@pytest.mark.asyncio
async def test_list_advertisers_sort_name(service) -> None:
    """list_advertisers with sort=name uses brand/username."""
    user = _make_user()
    rows = [(user, "BrandName", 0, 0, 0, None)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_advertisers(sort="name", order="asc")
    assert result["items"][0]["name"] == "BrandName"


@pytest.mark.asyncio
async def test_list_advertisers_unknown_sort_uses_default(service) -> None:
    """list_advertisers with unknown sort uses default order."""
    user = _make_user()
    rows = [(user, "B", 0, 0, 0, None)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_advertisers(sort="unknown_sort")
    assert len(result["items"]) == 1


@pytest.mark.asyncio
async def test_list_orders_unknown_sort_uses_created_at(service) -> None:
    """list_orders with unknown sort uses created_at order."""
    order = _make_order()
    rows = [(order, 0, 0, "Ad", "ad", 0, 0)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_orders(
        "today", status_filter=None, sort="unknown", order="asc"
    )
    assert len(result["items"]) == 1


@pytest.mark.asyncio
async def test_list_creators_sort_user_id_city_media_status(service) -> None:
    """list_creators with sort=user_id/city/status uses correct column."""
    user = _make_user()
    rows = [
        (user, "url", "Moscow", 100, 0, 0),
    ]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    for sort_key in ("user_id", "city", "status"):
        result = await svc.list_creators(
            "today", False, False, sort=sort_key, order="asc"
        )
        assert len(result["items"]) == 1


@pytest.mark.asyncio
async def test_list_advertisers_sort_user_id(service) -> None:
    """list_advertisers with sort=user_id uses user_id column."""
    user = _make_user()
    rows = [(user, "B", 0, 0, 0, None)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_advertisers(sort="user_id", order="asc")
    assert len(result["items"]) == 1


@pytest.mark.asyncio
async def test_list_orders_sort_order_id_status_dispatched_open_complaints(
    service,
) -> None:
    """list_orders sort=order_id, status, dispatched_count, open_complaints."""
    order = _make_order()
    rows = [(order, 1, 0, "Ad", "ad", 2, 1)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    for sort_key in (
        "order_id",
        "status",
        "dispatched_count",
        "open_complaints",
    ):
        result = await svc.list_orders(
            "today", status_filter=None, sort=sort_key, order="desc"
        )
        assert len(result["items"]) == 1


@pytest.mark.asyncio
async def test_list_orders_sort_responses(service) -> None:
    """list_orders sort=responses uses responses column (like picked_count)."""
    order = _make_order()
    rows = [(order, 3, 0, "Ad", "ad", 1, 1)]
    results = [
        _FakeResult(scalar_value=1),
        _FakeResult(all_rows=rows),
    ]
    svc = service(results)
    result = await svc.list_orders(
        "today", status_filter=None, sort="responses", order="desc"
    )
    assert result["items"][0]["picked_count"] == 3


@pytest.mark.asyncio
async def test_sort_referrers_manager_and_code(service) -> None:
    """_sort_referrers sorts by manager (telegram/username) and code."""
    referrers = [
        {
            "user_id": "a",
            "telegram": "@b",
            "username": "user_b",
            "referral_code": "BBB",
        },
        {
            "user_id": "b",
            "telegram": None,
            "username": "user_a",
            "referral_code": "AAA",
        },
    ]
    svc = service([])
    by_manager = svc._sort_referrers(referrers, "manager", "asc")
    assert by_manager[0]["user_id"] == "a"  # "@b" < "user_a" alphabetically
    by_code = svc._sort_referrers(referrers, "code", "asc")
    assert by_code[0]["referral_code"] == "AAA"

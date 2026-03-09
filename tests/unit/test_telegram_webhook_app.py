"""Tests for Telegram webhook application."""

import time
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramRetryAfter
from fastapi import HTTPException
from fastapi.testclient import TestClient

from tests.unit.test_miniapp_auth import _make_valid_init_data
from ugc_bot.application.errors import (
    AdvertiserRegistrationError,
    BloggerRegistrationError,
    OrderCreationError,
    OrderNotFoundError,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import (
    AdvertiserProfile,
    BloggerProfile,
    Order,
    User,
)
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    OrderStatus,
    OrderType,
    UserStatus,
    WorkFormat,
)
from ugc_bot.telegram_webhook_app import (
    _http_metrics_middleware,
    _set_webhook_with_retry,
    app,
)


def _test_config() -> AppConfig:
    """Create minimal config for webhook app."""
    return AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "WEBHOOK_BASE_URL": "https://test.example.com",
            "WEBHOOK_SECRET": "test_secret",
        }
    )


@pytest.fixture
def client() -> TestClient:
    """Create test client with mocked lifespan dependencies."""
    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage

    with (
        patch(
            "ugc_bot.telegram_webhook_app.load_config",
            return_value=_test_config(),
        ),
        patch(
            "ugc_bot.telegram_webhook_app.create_storage",
            new_callable=AsyncMock,
        ) as mock_storage,
        patch("ugc_bot.telegram_webhook_app.build_dispatcher") as mock_build,
        patch("ugc_bot.telegram_webhook_app.Bot") as MockBot,
    ):
        mock_storage.return_value = MemoryStorage()
        dp = Dispatcher(storage=MemoryStorage())
        mock_bot_texts = MagicMock()
        mock_bot_texts.load_from_db = AsyncMock(return_value=None)
        mock_bot_texts.get_many = AsyncMock(return_value={})
        dp["bot_texts_service"] = mock_bot_texts
        mock_build.return_value = dp
        fake_bot = MagicMock()
        fake_bot.set_webhook = AsyncMock(return_value=True)
        fake_bot.delete_webhook = AsyncMock(return_value=True)
        fake_bot.session = MagicMock()
        fake_bot.session.close = AsyncMock()
        MockBot.return_value = fake_bot

        with TestClient(
            app,
            headers={"X-Telegram-Bot-Api-Secret-Token": "test_secret"},
        ) as c:
            yield c


@pytest.mark.asyncio
async def test_http_metrics_middleware_records_500_when_call_next_raises() -> (
    None
):
    """Middleware except block runs when call_next raises non-HTTPException."""
    request = MagicMock()
    request.method = "GET"
    request.url.path = "/health"

    async def failing_next(_: object) -> None:
        raise RuntimeError("downstream error")

    with patch(
        "ugc_bot.telegram_webhook_app.record_http_request"
    ) as mock_record:
        with pytest.raises(RuntimeError, match="downstream error"):
            await _http_metrics_middleware(request, failing_next)
        mock_record.assert_called_once()
        call_kw = mock_record.call_args[1]
        assert call_kw.get("status_code") == 500


@pytest.mark.asyncio
async def test_http_metrics_middleware_records_4xx_on_http_exception() -> None:
    """Middleware except HTTPException branch runs when call_next raises it."""
    request = MagicMock()
    request.method = "GET"
    request.url.path = "/missing"

    async def http_404_next(_: object) -> None:
        raise HTTPException(status_code=404, detail="Not found")

    with patch(
        "ugc_bot.telegram_webhook_app.record_http_request"
    ) as mock_record:
        with pytest.raises(HTTPException):
            await _http_metrics_middleware(request, http_404_next)
        mock_record.assert_called_once()
        call_kw = mock_record.call_args[1]
        assert call_kw.get("status_code") == 404


def test_webhook_health(client: TestClient) -> None:
    """Health endpoint returns ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_miniapp_api_me_requires_init_data(client: TestClient) -> None:
    """POST /miniapp/api/me with empty init_data returns 401."""
    response = client.post(
        "/miniapp/api/me",
        json={"init_data": ""},
    )
    assert response.status_code == 401


def test_miniapp_api_me_rejects_invalid_signature(client: TestClient) -> None:
    """POST /miniapp/api/me with invalid init_data signature returns 401."""
    response = client.post(
        "/miniapp/api/me",
        json={"init_data": "auth_date=1&hash=wrong&user=%7B%22id%22%3A1%7D"},
    )
    assert response.status_code == 401


def test_miniapp_api_me_success_returns_user_and_profiles(
    client: TestClient,
) -> None:
    """POST /miniapp/api/me with valid init_data returns user_id and role."""
    telegram_id = 12345
    init_data = _make_valid_init_data("test_token", telegram_id)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id=str(telegram_id),
        messenger_type=MessengerType.TELEGRAM,
        username="testuser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.set_user = AsyncMock(return_value=None)
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=None)
    mock_ps.get_blogger_profile = AsyncMock(return_value=None)
    mock_ps.get_user_by_external = AsyncMock(return_value=user)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    response = client.post(
        "/miniapp/api/me",
        json={"init_data": init_data},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == str(user_id)
    assert data["external_id"] == str(telegram_id)
    assert data["role"] is None
    assert data["has_advertiser_profile"] is False
    assert data["has_blogger_profile"] is False


def test_miniapp_api_me_500_when_user_still_missing_after_set(
    client: TestClient,
) -> None:
    """POST /miniapp/api/me returns 500 when user missing after set_user."""
    init_data = _make_valid_init_data("test_token", 11115)
    mock_urs = MagicMock()
    mock_urs.set_user = AsyncMock(return_value=None)
    mock_urs.get_user = AsyncMock(return_value=None)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    response = client.post(
        "/miniapp/api/me",
        json={"init_data": init_data},
    )
    assert response.status_code == 500
    assert "Failed" in response.json().get("detail", "")


def test_miniapp_api_me_404_when_user_not_found_by_external(
    client: TestClient,
) -> None:
    """POST /miniapp/api/me returns 404 when user not found by external."""
    init_data = _make_valid_init_data("test_token", 11116)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="11116",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=None)
    mock_ps.get_blogger_profile = AsyncMock(return_value=None)
    mock_ps.get_user_by_external = AsyncMock(return_value=None)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    response = client.post("/miniapp/api/me", json={"init_data": init_data})
    assert response.status_code == 404


def test_miniapp_api_me_creates_user_when_missing(client: TestClient) -> None:
    """POST /miniapp/api/me when user not in DB creates user via set_user."""
    telegram_id = 99999
    init_data = _make_valid_init_data("test_token", telegram_id)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id=str(telegram_id),
        messenger_type=MessengerType.TELEGRAM,
        username="testuser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.set_user = AsyncMock(return_value=None)
    mock_urs.get_user = AsyncMock(side_effect=[None, user])
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=None)
    mock_ps.get_blogger_profile = AsyncMock(return_value=None)
    mock_ps.get_user_by_external = AsyncMock(return_value=user)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    response = client.post(
        "/miniapp/api/me",
        json={"init_data": init_data},
    )
    assert response.status_code == 200
    mock_urs.set_user.assert_called_once()
    assert response.json()["user_id"] == str(user_id)


def test_miniapp_api_me_returns_advertiser_role(client: TestClient) -> None:
    """POST /miniapp/api/me when user has advertiser profile returns role."""
    init_data = _make_valid_init_data("test_token", 11113)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="11113",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    adv = AdvertiserProfile(
        user_id=user_id,
        phone="+7900",
        brand="B",
        site_link=None,
        city=None,
        company_activity=None,
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=adv)
    mock_ps.get_blogger_profile = AsyncMock(return_value=None)
    mock_ps.get_user_by_external = AsyncMock(return_value=user)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    response = client.post("/miniapp/api/me", json={"init_data": init_data})
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "advertiser"
    assert data["has_advertiser_profile"] is True
    assert "advertiser_profile" in data
    assert data["advertiser_profile"]["phone"] == "+7900"
    assert data["advertiser_profile"]["brand"] == "B"
    assert data["advertiser_profile"]["display_name"] == "u"


def test_miniapp_api_me_returns_blogger_role(client: TestClient) -> None:
    """POST /miniapp/api/me when user has blogger profile returns role."""
    init_data = _make_valid_init_data("test_token", 11114)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="11114",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=None)
    mock_ps.get_blogger_profile = AsyncMock(return_value=MagicMock())
    mock_ps.get_user_by_external = AsyncMock(return_value=user)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    response = client.post("/miniapp/api/me", json={"init_data": init_data})
    assert response.status_code == 200
    assert response.json()["role"] == "blogger"
    assert response.json()["has_blogger_profile"] is True


def test_miniapp_api_me_returns_blogger_profile_with_birth_date(
    client: TestClient,
) -> None:
    """POST /me with blogger returns birth_date and topics in profile."""
    init_data = _make_valid_init_data("test_token", 11115)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="11115",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger_u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/u",
        confirmed=True,
        city="Moscow",
        topics={"selected": ["beauty", "fashion"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="РФ",
        price=5000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
        birth_date=date(1995, 5, 15),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=None)
    mock_ps.get_blogger_profile = AsyncMock(return_value=blogger)
    mock_ps.get_user_by_external = AsyncMock(return_value=user)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    response = client.post("/miniapp/api/me", json={"init_data": init_data})
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "blogger"
    prof = data.get("blogger_profile")
    assert prof is not None
    assert prof.get("birth_date") == "15.05.1995"
    assert prof.get("topics") == ["beauty", "fashion"]
    assert prof.get("display_name") == "blogger_u"


def test_miniapp_api_register_advertiser_user_not_found_404(
    client: TestClient,
) -> None:
    """POST register/advertiser when service raises UserNotFoundError -> 404."""
    from ugc_bot.application.errors import UserNotFoundError

    init_data = _make_valid_init_data("test_token", 99998)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="99998",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.set_user = AsyncMock(return_value=user)
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_adv = MagicMock()
    mock_adv.register_advertiser = AsyncMock(
        side_effect=UserNotFoundError("User not found")
    )
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["advertiser_registration_service"] = mock_adv
    response = client.post(
        "/miniapp/api/register/advertiser",
        json={
            "init_data": init_data,
            "phone": "+79001234567",
            "brand": "TestBrand",
        },
    )
    assert response.status_code == 404
    assert "detail" in response.json()


def test_miniapp_api_register_advertiser_registration_error_400(
    client: TestClient,
) -> None:
    """register/advertiser when service raises AdvertiserRegistrationError."""
    init_data = _make_valid_init_data("test_token", 99997)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="99997",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.set_user = AsyncMock(return_value=user)
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_adv = MagicMock()
    mock_adv.register_advertiser = AsyncMock(
        side_effect=AdvertiserRegistrationError("Invalid phone")
    )
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["advertiser_registration_service"] = mock_adv
    response = client.post(
        "/miniapp/api/register/advertiser",
        json={
            "init_data": init_data,
            "phone": "+79001234567",
            "brand": "TestBrand",
        },
    )
    assert response.status_code == 400
    assert "detail" in response.json()


def test_miniapp_api_register_advertiser_success(
    client: TestClient,
) -> None:
    """POST /miniapp/api/register/advertiser with valid data returns 200."""
    init_data = _make_valid_init_data("test_token", 99999)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="99999",
        messenger_type=MessengerType.TELEGRAM,
        username="advuser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    profile = AdvertiserProfile(
        user_id=user_id,
        phone="+79001234567",
        brand="TestBrand",
        site_link=None,
        city=None,
        company_activity=None,
    )
    mock_urs = MagicMock()
    mock_urs.set_user = AsyncMock(return_value=user)
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_adv = MagicMock()
    mock_adv.register_advertiser = AsyncMock(return_value=profile)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["advertiser_registration_service"] = mock_adv
    response = client.post(
        "/miniapp/api/register/advertiser",
        json={
            "init_data": init_data,
            "phone": "+79001234567",
            "brand": "TestBrand",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("ok") is True
    assert data.get("user_id") == str(user_id)


def test_miniapp_api_create_order_success(client: TestClient) -> None:
    """POST /miniapp/api/orders with valid data returns 200."""
    init_data = _make_valid_init_data("test_token", 88888)
    user_id = uuid4()
    order_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="88888",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    advertiser = AdvertiserProfile(
        user_id=user_id,
        phone="+79001111111",
        brand="Brand",
        site_link=None,
        city=None,
        company_activity=None,
    )
    order = Order(
        order_id=order_id,
        advertiser_id=user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com/p",
        offer_text="Valid offer text with at least twenty chars.",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=advertiser)
    mock_order_svc = MagicMock()
    mock_order_svc.create_order = AsyncMock(return_value=order)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    dispatcher["order_service"] = mock_order_svc
    response = client.post(
        "/miniapp/api/orders",
        json={
            "init_data": init_data,
            "product_link": "https://example.com/p",
            "offer_text": "Valid offer text with at least twenty chars.",
            "price": 1000,
            "bloggers_needed": 3,
            "order_type": "ugc_only",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("ok") is True
    assert data.get("order_id") == str(order_id)
    assert data.get("status") == OrderStatus.NEW.value
    assert "payment_link" in data


def test_miniapp_api_cities_returns_list(client: TestClient) -> None:
    """GET /miniapp/api/cities returns list of cities with id and label."""
    response = client.get("/miniapp/api/cities")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if data:
        assert "id" in data[0]
        assert "label" in data[0]


def test_miniapp_api_config_success(client: TestClient) -> None:
    """POST /miniapp/api/config returns allowed_blogger_counts and options."""
    init_data = _make_valid_init_data("test_token", 55555)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="55555",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    response = client.post(
        "/miniapp/api/config",
        json={"init_data": init_data},
    )
    assert response.status_code == 200
    data = response.json()
    assert "allowed_blogger_counts" in data
    assert "content_usage_options" in data
    assert "bot_username" in data


def test_miniapp_api_create_order_invalid_bloggers_needed_400(
    client: TestClient,
) -> None:
    """Create order with bloggers_needed not in allowed set returns 400."""
    init_data = _make_valid_init_data("test_token", 88882)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="88882",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    adv = AdvertiserProfile(
        user_id=user_id,
        phone="+7900",
        brand="B",
        site_link=None,
        city=None,
        company_activity=None,
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=adv)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    response = client.post(
        "/miniapp/api/orders",
        json={
            "init_data": init_data,
            "product_link": "https://example.com/p",
            "offer_text": "Valid offer text with at least twenty chars.",
            "price": 1000,
            "bloggers_needed": 99,
            "order_type": "ugc_only",
        },
    )
    assert response.status_code == 400
    assert "bloggers_needed" in response.json().get("detail", "")


def test_miniapp_api_orders_list_success(client: TestClient) -> None:
    """POST /miniapp/api/orders/list with valid init_data returns orders."""
    init_data = _make_valid_init_data("test_token", 77777)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77777",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_order_svc = MagicMock()
    mock_order_svc.list_by_advertiser = AsyncMock(return_value=[])
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["order_service"] = mock_order_svc
    response = client.post(
        "/miniapp/api/orders/list",
        json={"init_data": init_data},
    )
    assert response.status_code == 200
    data = response.json()
    assert "orders" in data
    assert data["orders"] == []


def test_miniapp_api_orders_list_includes_payment_link(
    client: TestClient,
) -> None:
    """Orders list items include payment_link when config has bot_username."""
    init_data = _make_valid_init_data("test_token", 77778)
    user_id = uuid4()
    order_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77778",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    order = Order(
        order_id=order_id,
        advertiser_id=user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com/p",
        offer_text="Offer",
        barter_description=None,
        price=100.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_order_svc = MagicMock()
    mock_order_svc.list_by_advertiser = AsyncMock(return_value=[order])
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["order_service"] = mock_order_svc
    response = client.post(
        "/miniapp/api/orders/list",
        json={"init_data": init_data},
    )
    assert response.status_code == 200
    orders = response.json().get("orders", [])
    assert len(orders) == 1
    assert "payment_link" in orders[0]


def test_miniapp_api_geocode_reverse_success(client: TestClient) -> None:
    """POST /geocode/reverse returns city, region, country for valid coords."""
    init_data = _make_valid_init_data("test_token", 77781)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77781",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.resolve_city_from_location = AsyncMock(
        return_value=("Москва", "Московская область", "Россия")
    )
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/geocode/reverse",
        json={"init_data": init_data, "lat": 55.7558, "lon": 37.6173},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["city"] == "Москва"
    assert data["region"] == "Московская область"
    assert data["country"] == "Россия"


def test_miniapp_api_geocode_reverse_404_when_not_resolved(
    client: TestClient,
) -> None:
    """POST /geocode/reverse returns 404 when location not resolved."""
    init_data = _make_valid_init_data("test_token", 77782)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77782",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.resolve_city_from_location = AsyncMock(return_value=None)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/geocode/reverse",
        json={"init_data": init_data, "lat": 0.0, "lon": 0.0},
    )
    assert response.status_code == 404
    assert "detail" in response.json()


def test_miniapp_api_geocode_reverse_422_invalid_coords(
    client: TestClient,
) -> None:
    """POST /geocode/reverse returns 422 for lat/lon out of range."""
    init_data = _make_valid_init_data("test_token", 77783)
    response = client.post(
        "/miniapp/api/geocode/reverse",
        json={"init_data": init_data, "lat": 100.0, "lon": 0.0},
    )
    assert response.status_code == 422


def test_miniapp_api_geocode_forward_success(client: TestClient) -> None:
    """POST /geocode/forward returns lat, lon, city for valid city name."""
    init_data = _make_valid_init_data("test_token", 77784)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77784",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.resolve_city_to_coordinates = AsyncMock(
        return_value=(55.7558, 37.6173, "Московская область", "Россия")
    )
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/geocode/forward",
        json={"init_data": init_data, "city": "Москва"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["lat"] == 55.7558
    assert data["lon"] == 37.6173
    assert data["city"] == "Москва"
    assert data["region"] == "Московская область"
    assert data["country"] == "Россия"


def test_miniapp_api_geocode_forward_public_success(client: TestClient) -> None:
    """POST /geocode/forward/public returns lat, lon, city without init_data."""
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.resolve_city_to_coordinates = AsyncMock(
        return_value=(55.8304, 49.0661, "Республика Татарстан", "Россия")
    )
    dispatcher = app.state.dispatcher
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/geocode/forward/public",
        json={"city": "Казань"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["lat"] == 55.8304
    assert data["lon"] == 49.0661
    assert data["city"] == "Казань"


def test_miniapp_api_geocode_forward_public_404_when_not_found(
    client: TestClient,
) -> None:
    """POST /geocode/forward/public returns 404 when city not found."""
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.resolve_city_to_coordinates = AsyncMock(return_value=None)
    dispatcher = app.state.dispatcher
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/geocode/forward/public",
        json={"city": "NonexistentCity"},
    )
    assert response.status_code == 404


def test_miniapp_api_geocode_forward_400_empty_city(client: TestClient) -> None:
    """POST /geocode/forward returns 400 when city is empty."""
    init_data = _make_valid_init_data("test_token", 77786)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77786",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    response = client.post(
        "/miniapp/api/geocode/forward",
        json={"init_data": init_data, "city": "   "},
    )
    assert response.status_code == 400


def test_miniapp_api_geocode_forward_404_when_not_found(
    client: TestClient,
) -> None:
    """POST /geocode/forward returns 404 when city not found."""
    init_data = _make_valid_init_data("test_token", 77785)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77785",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.resolve_city_to_coordinates = AsyncMock(return_value=None)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/geocode/forward",
        json={"init_data": init_data, "city": "NonexistentCity"},
    )
    assert response.status_code == 404


def test_miniapp_api_orders_list_creator_success(client: TestClient) -> None:
    """POST /orders/list/creator returns orders the creator responded to."""
    from ugc_bot.domain.entities import OfferDispatch

    init_data = _make_valid_init_data("test_token", 77780)
    user_id = uuid4()
    order_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77780",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    order = Order(
        order_id=order_id,
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com/p",
        offer_text="Offer",
        barter_description=None,
        price=50.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    dispatch = OfferDispatch(
        order_id=order_id,
        blogger_id=user_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        accepted=True,
        in_offer=True,
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_order_svc = MagicMock()
    mock_order_svc.get_order = AsyncMock(return_value=order)
    mock_offer_svc = MagicMock()
    mock_offer_svc.list_by_blogger = AsyncMock(return_value=[dispatch])
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["order_service"] = mock_order_svc
    dispatcher["offer_response_service"] = mock_offer_svc
    response = client.post(
        "/miniapp/api/orders/list/creator",
        json={"init_data": init_data},
    )
    assert response.status_code == 200
    data = response.json()
    assert "orders" in data
    assert len(data["orders"]) == 1
    assert data["orders"][0]["order_id"] == str(order_id)
    assert data["orders"][0]["product_link"] == order.product_link
    assert data["orders"][0]["payment_link"] == ""


def test_miniapp_api_orders_list_creator_deduplicates_and_skips_missing(
    client: TestClient,
) -> None:
    """List creator: duplicate order_id and get_order None are skipped."""
    from ugc_bot.domain.entities import OfferDispatch

    init_data = _make_valid_init_data("test_token", 77787)
    user_id = uuid4()
    order_id_a = uuid4()
    order_id_b = uuid4()
    user = User(
        user_id=user_id,
        external_id="77787",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    order_a = Order(
        order_id=order_id_a,
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com/a",
        offer_text="Offer",
        barter_description=None,
        price=50.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    dispatch_a = OfferDispatch(
        order_id=order_id_a,
        blogger_id=user_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        accepted=True,
        in_offer=True,
    )
    dispatch_a_dup = OfferDispatch(
        order_id=order_id_a,
        blogger_id=user_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        accepted=True,
        in_offer=True,
    )
    dispatch_b = OfferDispatch(
        order_id=order_id_b,
        blogger_id=user_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        accepted=True,
        in_offer=True,
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_order_svc = MagicMock()

    async def get_order_side_effect(oid):
        if oid == order_id_a:
            return order_a
        return None

    mock_order_svc.get_order = AsyncMock(side_effect=get_order_side_effect)
    mock_offer_svc = MagicMock()
    mock_offer_svc.list_by_blogger = AsyncMock(
        return_value=[dispatch_a, dispatch_a_dup, dispatch_b]
    )
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["order_service"] = mock_order_svc
    dispatcher["offer_response_service"] = mock_offer_svc
    response = client.post(
        "/miniapp/api/orders/list/creator",
        json={"init_data": init_data},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["orders"]) == 1
    assert data["orders"][0]["order_id"] == str(order_id_a)


def test_miniapp_api_orders_get_success(client: TestClient) -> None:
    """POST /miniapp/api/orders/get returns order detail for owner."""
    init_data = _make_valid_init_data("test_token", 77779)
    user_id = uuid4()
    order_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77779",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    order = Order(
        order_id=order_id,
        advertiser_id=user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com/p",
        offer_text="Offer text",
        barter_description=None,
        price=100.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_order_svc = MagicMock()
    mock_order_svc.get_order = AsyncMock(return_value=order)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["order_service"] = mock_order_svc
    response = client.post(
        "/miniapp/api/orders/get",
        json={"init_data": init_data, "order_id": str(order_id)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["order_id"] == str(order_id)
    assert data["product_link"] == order.product_link
    assert data["status"] == OrderStatus.NEW.value
    assert "payment_link" in data


def test_miniapp_api_orders_get_404_when_not_found(client: TestClient) -> None:
    """POST /miniapp/api/orders/get returns 404 when order missing."""
    init_data = _make_valid_init_data("test_token", 77780)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77780",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_order_svc = MagicMock()
    mock_order_svc.get_order = AsyncMock(return_value=None)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["order_service"] = mock_order_svc
    response = client.post(
        "/miniapp/api/orders/get",
        json={"init_data": init_data, "order_id": str(uuid4())},
    )
    assert response.status_code == 404


def test_miniapp_api_orders_get_404_wrong_owner(client: TestClient) -> None:
    """POST /miniapp/api/orders/get returns 404 when order belongs to other."""
    init_data = _make_valid_init_data("test_token", 77781)
    user_id = uuid4()
    other_id = uuid4()
    order_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77781",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    order = Order(
        order_id=order_id,
        advertiser_id=other_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://x.com",
        offer_text="Offer",
        barter_description=None,
        price=100.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_order_svc = MagicMock()
    mock_order_svc.get_order = AsyncMock(return_value=order)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["order_service"] = mock_order_svc
    response = client.post(
        "/miniapp/api/orders/get",
        json={"init_data": init_data, "order_id": str(order_id)},
    )
    assert response.status_code == 404


def test_miniapp_api_orders_get_400_invalid_id(client: TestClient) -> None:
    """POST /miniapp/api/orders/get with invalid order_id returns 400."""
    init_data = _make_valid_init_data("test_token", 77782)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77782",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    response = client.post(
        "/miniapp/api/orders/get",
        json={"init_data": init_data, "order_id": "not-a-uuid"},
    )
    assert response.status_code == 400


def test_miniapp_api_orders_update_success(client: TestClient) -> None:
    """POST /miniapp/api/orders/update updates order and returns 200."""
    init_data = _make_valid_init_data("test_token", 77783)
    user_id = uuid4()
    order_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77783",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    advertiser = AdvertiserProfile(
        user_id=user_id,
        phone="+79001111111",
        brand="Brand",
        site_link=None,
        city=None,
        company_activity=None,
    )
    updated_order = Order(
        order_id=order_id,
        advertiser_id=user_id,
        order_type=OrderType.UGC_PLUS_PLACEMENT,
        product_link="https://example.com/v2",
        offer_text="Updated offer text with enough length.",
        barter_description=None,
        price=500.0,
        bloggers_needed=5,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=advertiser)
    mock_order_svc = MagicMock()
    mock_order_svc.update_order = AsyncMock(return_value=updated_order)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    dispatcher["order_service"] = mock_order_svc
    response = client.post(
        "/miniapp/api/orders/update",
        json={
            "init_data": init_data,
            "order_id": str(order_id),
            "product_link": "https://example.com/v2",
            "offer_text": "Updated offer text with enough length.",
            "price": 500,
            "bloggers_needed": 5,
            "order_type": "ugc_plus_placement",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("ok") is True
    assert data.get("order_id") == str(order_id)
    assert "payment_link" in data


def test_miniapp_api_orders_update_404(client: TestClient) -> None:
    """POST /miniapp/api/orders/update returns 404 when order not found."""
    init_data = _make_valid_init_data("test_token", 77784)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77784",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    advertiser = AdvertiserProfile(
        user_id=user_id,
        phone="+79001111111",
        brand="B",
        site_link=None,
        city=None,
        company_activity=None,
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=advertiser)
    mock_order_svc = MagicMock()
    mock_order_svc.update_order = AsyncMock(side_effect=OrderNotFoundError("x"))
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    dispatcher["order_service"] = mock_order_svc
    response = client.post(
        "/miniapp/api/orders/update",
        json={
            "init_data": init_data,
            "order_id": str(uuid4()),
            "product_link": "https://example.com",
            "offer_text": "Valid offer text with at least twenty chars.",
            "price": 100,
            "bloggers_needed": 3,
            "order_type": "ugc_only",
        },
    )
    assert response.status_code == 404


def test_miniapp_api_orders_update_400_bad_price(
    client: TestClient,
) -> None:
    """POST /orders/update with price over max returns 400."""
    init_data = _make_valid_init_data("test_token", 77791)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77791",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    advertiser = AdvertiserProfile(
        user_id=user_id,
        phone="+79001111111",
        brand="B",
        site_link=None,
        city=None,
        company_activity=None,
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=advertiser)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    response = client.post(
        "/miniapp/api/orders/update",
        json={
            "init_data": init_data,
            "order_id": str(uuid4()),
            "product_link": "https://example.com/v2",
            "offer_text": "Updated offer text with enough length.",
            "price": 999999999,
            "bloggers_needed": 3,
            "order_type": "ugc_only",
        },
    )
    assert response.status_code == 400


def test_miniapp_api_orders_update_400_validation_error(
    client: TestClient,
) -> None:
    """POST /orders/update with invalid payload returns 400 from validation."""
    init_data = _make_valid_init_data("test_token", 77789)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77789",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    advertiser = AdvertiserProfile(
        user_id=user_id,
        phone="+79001111111",
        brand="B",
        site_link=None,
        city=None,
        company_activity=None,
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=advertiser)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    response = client.post(
        "/miniapp/api/orders/update",
        json={
            "init_data": init_data,
            "order_id": str(uuid4()),
            "product_link": "",
            "offer_text": "Short",
            "price": 100,
            "bloggers_needed": 3,
            "order_type": "ugc_only",
        },
    )
    assert response.status_code == 400


def test_miniapp_api_orders_update_400_invalid_geography(
    client: TestClient,
) -> None:
    """POST /orders/update with invalid geography returns 400."""
    init_data = _make_valid_init_data("test_token", 77790)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77790",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    advertiser = AdvertiserProfile(
        user_id=user_id,
        phone="+79001111111",
        brand="B",
        site_link=None,
        city=None,
        company_activity=None,
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=advertiser)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    response = client.post(
        "/miniapp/api/orders/update",
        json={
            "init_data": init_data,
            "order_id": str(uuid4()),
            "product_link": "https://example.com/v2",
            "offer_text": "Updated offer text with enough length.",
            "price": 500,
            "bloggers_needed": 3,
            "order_type": "ugc_only",
            "geography": "/profile",
        },
    )
    assert response.status_code == 400


def test_miniapp_api_orders_update_400_invalid_order_id(
    client: TestClient,
) -> None:
    """POST /orders/update with invalid order_id returns 400."""
    init_data = _make_valid_init_data("test_token", 77786)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77786",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    advertiser = AdvertiserProfile(
        user_id=user_id,
        phone="+79001111111",
        brand="B",
        site_link=None,
        city=None,
        company_activity=None,
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=advertiser)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    response = client.post(
        "/miniapp/api/orders/update",
        json={
            "init_data": init_data,
            "order_id": "not-a-uuid",
            "product_link": "https://example.com",
            "offer_text": "Valid offer text with at least twenty chars.",
            "price": 100,
            "bloggers_needed": 3,
            "order_type": "ugc_only",
        },
    )
    assert response.status_code == 400
    assert "order_id" in response.json().get("detail", "").lower()


def test_miniapp_api_orders_update_400_invalid_bloggers_needed(
    client: TestClient,
) -> None:
    """POST /orders/update with bloggers_needed not in allowed returns 400."""
    init_data = _make_valid_init_data("test_token", 77788)
    user_id = uuid4()
    order_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77788",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    advertiser = AdvertiserProfile(
        user_id=user_id,
        phone="+79001111111",
        brand="B",
        site_link=None,
        city=None,
        company_activity=None,
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=advertiser)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    response = client.post(
        "/miniapp/api/orders/update",
        json={
            "init_data": init_data,
            "order_id": str(order_id),
            "product_link": "https://example.com/v2",
            "offer_text": "Updated offer text with enough length.",
            "price": 500,
            "bloggers_needed": 99,
            "order_type": "ugc_plus_placement",
        },
    )
    assert response.status_code == 400
    assert "bloggers_needed" in response.json().get("detail", "")


def test_miniapp_api_orders_update_400_creation_error(
    client: TestClient,
) -> None:
    """POST /orders/update when service raises OrderCreationError -> 400."""
    init_data = _make_valid_init_data("test_token", 77787)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77787",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    advertiser = AdvertiserProfile(
        user_id=user_id,
        phone="+79001111111",
        brand="B",
        site_link=None,
        city=None,
        company_activity=None,
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=advertiser)
    mock_order_svc = MagicMock()
    mock_order_svc.update_order = AsyncMock(
        side_effect=OrderCreationError("Cannot edit")
    )
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    dispatcher["order_service"] = mock_order_svc
    response = client.post(
        "/miniapp/api/orders/update",
        json={
            "init_data": init_data,
            "order_id": str(uuid4()),
            "product_link": "https://example.com",
            "offer_text": "Valid offer text with at least twenty chars.",
            "price": 100,
            "bloggers_needed": 3,
            "order_type": "ugc_only",
        },
    )
    assert response.status_code == 400


def test_miniapp_api_orders_update_403_no_advertiser(
    client: TestClient,
) -> None:
    """POST /orders/update without advertiser profile returns 403."""
    init_data = _make_valid_init_data("test_token", 77785)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="77785",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=None)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    response = client.post(
        "/miniapp/api/orders/update",
        json={
            "init_data": init_data,
            "order_id": str(uuid4()),
            "product_link": "https://example.com",
            "offer_text": "Valid offer text with at least twenty chars.",
            "price": 100,
            "bloggers_needed": 3,
            "order_type": "ugc_only",
        },
    )
    assert response.status_code == 403


def test_miniapp_api_orders_returns_403_without_advertiser_profile(
    client: TestClient,
) -> None:
    """POST /miniapp/api/orders without advertiser profile returns 403."""
    init_data = _make_valid_init_data("test_token", 66666)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="66666",
        messenger_type=MessengerType.TELEGRAM,
        username="noadv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=None)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    response = client.post(
        "/miniapp/api/orders",
        json={
            "init_data": init_data,
            "product_link": "https://x.com/p",
            "offer_text": "T",
            "price": 100,
            "bloggers_needed": 1,
            "order_type": "ugc_only",
        },
    )
    assert response.status_code == 403
    assert "advertiser" in response.json().get("detail", "").lower()


def test_miniapp_api_register_advertiser_invalid_phone(
    client: TestClient,
) -> None:
    """Register advertiser with invalid phone returns 400."""
    init_data = _make_valid_init_data("test_token", 11111)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="11111",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    response = client.post(
        "/miniapp/api/register/advertiser",
        json={
            "init_data": init_data,
            "phone": "1",
            "brand": "Brand",
            "site_link": None,
            "city": None,
            "company_activity": None,
            "display_name": None,
        },
    )
    assert response.status_code == 400
    assert "detail" in response.json()


def test_miniapp_api_register_blogger_age_range_invalid_400(
    client: TestClient,
) -> None:
    """POST register/blogger with audience_age_max < audience_age_min -> 400."""
    init_data = _make_valid_init_data("test_token", 55554)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="55554",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = MagicMock()
    response = client.post(
        "/miniapp/api/register/blogger",
        json={
            "init_data": init_data,
            "instagram_url": "https://instagram.com/u",
            "city": "Moscow",
            "audience_geo": "РФ",
            "audience_age_min": 35,
            "audience_age_max": 18,
            "audience_gender": "all",
            "price": 1000,
            "barter": False,
            "work_format": "ugc_only",
            "topics": ["tech"],
            "blogger_gender": "m",
            "display_name": "ValidUser",
            "birth_date": "01.01.1990",
        },
    )
    assert response.status_code == 400
    assert "audience_age" in response.json().get("detail", "")


def test_miniapp_api_register_blogger_invalid_work_format_400(
    client: TestClient,
) -> None:
    """POST register/blogger with invalid work_format -> 400."""
    init_data = _make_valid_init_data("test_token", 55553)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="55553",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.get_profile_by_instagram_url = AsyncMock(return_value=None)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/register/blogger",
        json={
            "init_data": init_data,
            "instagram_url": "https://instagram.com/u",
            "city": "Moscow",
            "audience_geo": "РФ",
            "audience_age_min": 18,
            "audience_age_max": 35,
            "audience_gender": "all",
            "price": 1000,
            "barter": False,
            "work_format": "invalid_format",
            "topics": ["tech"],
            "blogger_gender": "m",
            "display_name": "ValidUser",
            "birth_date": "01.01.1990",
        },
    )
    assert response.status_code == 400
    assert "work_format" in response.json().get("detail", "")


def test_miniapp_api_register_blogger_invalid_audience_gender_400(
    client: TestClient,
) -> None:
    """POST register/blogger with invalid audience_gender -> 400."""
    init_data = _make_valid_init_data("test_token", 55552)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="55552",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.get_profile_by_instagram_url = AsyncMock(return_value=None)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/register/blogger",
        json={
            "init_data": init_data,
            "instagram_url": "https://instagram.com/u",
            "city": "Moscow",
            "audience_geo": "РФ",
            "audience_age_min": 18,
            "audience_age_max": 35,
            "audience_gender": "invalid_gender",
            "price": 1000,
            "barter": False,
            "work_format": "ugc_only",
            "topics": ["tech"],
            "blogger_gender": "m",
            "display_name": "ValidUser",
            "birth_date": "01.01.1990",
        },
    )
    assert response.status_code == 400
    assert "audience_gender" in response.json().get("detail", "")


def test_miniapp_api_register_blogger_invalid_blogger_gender_400(
    client: TestClient,
) -> None:
    """POST register/blogger with invalid blogger_gender -> 400."""
    init_data = _make_valid_init_data("test_token", 55551)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="55551",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.get_profile_by_instagram_url = AsyncMock(return_value=None)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/register/blogger",
        json={
            "init_data": init_data,
            "instagram_url": "https://instagram.com/u",
            "city": "Moscow",
            "audience_geo": "РФ",
            "audience_age_min": 18,
            "audience_age_max": 35,
            "audience_gender": "all",
            "price": 1000,
            "barter": False,
            "work_format": "ugc_only",
            "topics": ["tech"],
            "blogger_gender": "invalid_blogger_gender",
            "display_name": "ValidUser",
            "birth_date": "01.01.1990",
        },
    )
    assert response.status_code == 400
    assert "blogger_gender" in response.json().get("detail", "")


def test_miniapp_api_register_blogger_success(client: TestClient) -> None:
    """POST /miniapp/api/register/blogger with valid data returns 200."""
    init_data = _make_valid_init_data("test_token", 55555)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="55555",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.get_profile_by_instagram_url = AsyncMock(return_value=None)
    mock_blogger_svc.save_blogger_before_agreement = AsyncMock(
        return_value=MagicMock()
    )
    mock_blogger_svc.confirm_blogger_agreement = AsyncMock(return_value=None)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/register/blogger",
        json={
            "init_data": init_data,
            "instagram_url": "https://instagram.com/test",
            "city": "Moscow",
            "audience_geo": "РФ",
            "audience_age_min": 18,
            "audience_age_max": 35,
            "audience_gender": "all",
            "price": 5000,
            "barter": False,
            "work_format": "ugc_only",
            "topics": ["tech"],
            "blogger_gender": "m",
            "display_name": "TestUser",
            "birth_date": "15.05.1995",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("ok") is True
    assert data.get("user_id") == str(user_id)


def test_miniapp_api_register_blogger_with_lat_lon_passes_location_geometry(
    client: TestClient,
) -> None:
    """Register blogger with lat/lon passes WKT to service, skips geocoder."""
    init_data = _make_valid_init_data("test_token", 55555)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="55555",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.get_profile_by_instagram_url = AsyncMock(return_value=None)
    mock_blogger_svc.save_blogger_before_agreement = AsyncMock(
        return_value=MagicMock()
    )
    mock_blogger_svc.confirm_blogger_agreement = AsyncMock(return_value=None)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/register/blogger",
        json={
            "init_data": init_data,
            "instagram_url": "https://instagram.com/test",
            "city": "Москва",
            "region": "Московская область",
            "country": "Россия",
            "lat": 55.7558,
            "lon": 37.6173,
            "audience_geo": "РФ",
            "audience_age_min": 18,
            "audience_age_max": 35,
            "audience_gender": "all",
            "price": 5000,
            "barter": False,
            "work_format": "ugc_only",
            "topics": ["tech"],
            "blogger_gender": "m",
            "display_name": "TestUser",
            "birth_date": "15.05.1995",
        },
    )
    assert response.status_code == 200
    mock_blogger_svc.save_blogger_before_agreement.assert_called_once()
    call_kw = mock_blogger_svc.save_blogger_before_agreement.call_args[1]
    assert call_kw.get("location_geometry") == "MULTIPOINT((37.6173 55.7558))"
    assert call_kw.get("city") == "Москва"
    assert call_kw.get("region") == "Московская область"
    assert call_kw.get("country") == "Россия"


def test_miniapp_api_register_blogger_update_raises_user_not_found_404(
    client: TestClient,
) -> None:
    """Register blogger update path when update_blogger_profile raises 404."""
    from ugc_bot.application.errors import UserNotFoundError
    from ugc_bot.domain.enums import AudienceGender, WorkFormat

    init_data = _make_valid_init_data("test_token", 55558)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="55558",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    existing_profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/mine",
        confirmed=True,
        city="Moscow",
        topics={"selected": ["tech"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="РФ",
        price=5000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.get_profile_by_instagram_url = AsyncMock(
        return_value=existing_profile
    )
    mock_blogger_svc.update_blogger_profile = AsyncMock(
        side_effect=UserNotFoundError("User not found")
    )
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/register/blogger",
        json={
            "init_data": init_data,
            "instagram_url": "https://instagram.com/mine",
            "city": "Moscow",
            "audience_geo": "РФ",
            "audience_age_min": 18,
            "audience_age_max": 35,
            "audience_gender": "all",
            "price": 5000,
            "barter": False,
            "work_format": "ugc_only",
            "topics": ["tech"],
            "blogger_gender": "m",
            "display_name": "TestUser",
            "birth_date": "15.05.1995",
        },
    )
    assert response.status_code == 404
    assert "detail" in response.json()


def test_miniapp_api_register_blogger_create_requires_birth_date(
    client: TestClient,
) -> None:
    """Register blogger without birth_date (create path) returns 400."""
    init_data = _make_valid_init_data("test_token", 55558)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="55558",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.get_profile_by_instagram_url = AsyncMock(return_value=None)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    payload = {
        "init_data": init_data,
        "instagram_url": "https://instagram.com/newuser",
        "city": "Moscow",
        "audience_geo": "РФ",
        "audience_age_min": 18,
        "audience_age_max": 35,
        "audience_gender": "all",
        "price": 5000,
        "barter": False,
        "work_format": "ugc_only",
        "topics": ["tech"],
        "blogger_gender": "m",
        "display_name": "User",
    }
    response = client.post("/miniapp/api/register/blogger", json=payload)
    assert response.status_code == 400
    assert (
        "birth_date" in response.json().get("detail", "").lower()
        or "date" in response.json().get("detail", "").lower()
    )


def test_miniapp_api_register_blogger_update_own_profile_success(
    client: TestClient,
) -> None:
    """POST register/blogger with own Instagram updates profile, returns 200."""
    from ugc_bot.application.services.blogger_registration_service import (
        UpdateBloggerProfileResult,
    )
    from ugc_bot.domain.enums import AudienceGender, WorkFormat

    init_data = _make_valid_init_data("test_token", 55557)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="55557",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    existing_profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/mine",
        confirmed=True,
        city="Moscow",
        topics={"selected": ["tech"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="РФ",
        price=5000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.get_profile_by_instagram_url = AsyncMock(
        return_value=existing_profile
    )
    mock_blogger_svc.update_blogger_profile = AsyncMock(
        return_value=UpdateBloggerProfileResult(profile=existing_profile)
    )
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/register/blogger",
        json={
            "init_data": init_data,
            "instagram_url": "https://instagram.com/mine",
            "city": "Moscow",
            "audience_geo": "РФ",
            "audience_age_min": 18,
            "audience_age_max": 35,
            "audience_gender": "all",
            "price": 5000,
            "barter": False,
            "work_format": "ugc_only",
            "topics": ["tech"],
            "blogger_gender": "m",
            "display_name": "TestUser",
            "birth_date": "15.05.1995",
        },
    )
    assert response.status_code == 200
    assert response.json().get("ok") is True
    assert response.json().get("user_id") == str(user_id)
    mock_blogger_svc.update_blogger_profile.assert_called_once()
    mock_blogger_svc.save_blogger_before_agreement.assert_not_called()


def test_miniapp_api_register_blogger_update_raises_registration_error_400(
    client: TestClient,
) -> None:
    """POST register/blogger update path BloggerRegistrationError -> 400."""
    from ugc_bot.domain.enums import AudienceGender, WorkFormat

    init_data = _make_valid_init_data("test_token", 55561)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="55561",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    existing = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/me",
        confirmed=True,
        city="Moscow",
        topics={"selected": ["tech"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="РФ",
        price=5000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.get_profile_by_instagram_url = AsyncMock(
        return_value=existing
    )
    mock_blogger_svc.update_blogger_profile = AsyncMock(
        side_effect=BloggerRegistrationError("Invalid data")
    )
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/register/blogger",
        json={
            "init_data": init_data,
            "instagram_url": "https://instagram.com/me",
            "city": "Moscow",
            "audience_geo": "РФ",
            "audience_age_min": 18,
            "audience_age_max": 35,
            "audience_gender": "all",
            "price": 5000,
            "barter": False,
            "work_format": "ugc_only",
            "topics": ["tech"],
            "blogger_gender": "m",
            "display_name": "User",
            "birth_date": "15.05.1995",
        },
    )
    assert response.status_code == 400


def test_miniapp_api_register_blogger_instagram_taken(
    client: TestClient,
) -> None:
    """POST /miniapp/api/register/blogger when Instagram taken returns 400."""
    init_data = _make_valid_init_data("test_token", 55556)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="55556",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.get_profile_by_instagram_url = AsyncMock(
        return_value=MagicMock()
    )
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/register/blogger",
        json={
            "init_data": init_data,
            "instagram_url": "https://instagram.com/taken",
            "city": "Moscow",
            "audience_geo": "РФ",
            "audience_age_min": 18,
            "audience_age_max": 35,
            "audience_gender": "all",
            "price": 1000,
            "barter": False,
            "work_format": "ugc_only",
            "topics": ["tech"],
            "blogger_gender": "m",
            "display_name": "User",
            "birth_date": "15.05.1995",
        },
    )
    assert response.status_code == 400
    assert "instagram" in response.json().get("detail", "").lower()


def test_miniapp_api_register_blogger_service_error(
    client: TestClient,
) -> None:
    """Register blogger when service raises returns 400."""
    init_data = _make_valid_init_data("test_token", 55560)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="55560",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.get_profile_by_instagram_url = AsyncMock(return_value=None)
    mock_blogger_svc.save_blogger_before_agreement = AsyncMock(
        side_effect=BloggerRegistrationError("DB error.")
    )
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/register/blogger",
        json={
            "init_data": init_data,
            "instagram_url": "https://instagram.com/user",
            "city": "Moscow",
            "audience_geo": "РФ",
            "audience_age_min": 18,
            "audience_age_max": 35,
            "audience_gender": "all",
            "price": 1000,
            "barter": False,
            "work_format": "ugc_only",
            "topics": ["tech"],
            "blogger_gender": "m",
            "display_name": "User",
            "birth_date": "15.05.1995",
        },
    )
    assert response.status_code == 400
    assert "detail" in response.json()


def test_miniapp_api_register_blogger_invalid_instagram_format(
    client: TestClient,
) -> None:
    """Register blogger with invalid instagram URL returns 400."""
    init_data = _make_valid_init_data("test_token", 55559)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="55559",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.get_profile_by_instagram_url = AsyncMock(return_value=None)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/register/blogger",
        json={
            "init_data": init_data,
            "instagram_url": "https://not-instagram.com/user",
            "city": "Moscow",
            "audience_geo": "РФ",
            "audience_age_min": 18,
            "audience_age_max": 35,
            "audience_gender": "all",
            "price": 1000,
            "barter": False,
            "work_format": "ugc_only",
            "topics": ["tech"],
            "blogger_gender": "m",
            "display_name": "User",
            "birth_date": "15.05.1995",
        },
    )
    assert response.status_code == 400
    assert "detail" in response.json()


def test_miniapp_api_register_blogger_validation_empty_topics(
    client: TestClient,
) -> None:
    """POST /miniapp/api/register/blogger with empty topics returns 400."""
    init_data = _make_valid_init_data("test_token", 55557)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="55557",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.get_profile_by_instagram_url = AsyncMock(return_value=None)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/register/blogger",
        json={
            "init_data": init_data,
            "instagram_url": "https://instagram.com/newuser",
            "city": "Moscow",
            "audience_geo": "РФ",
            "audience_age_min": 18,
            "audience_age_max": 35,
            "audience_gender": "all",
            "price": 1000,
            "barter": False,
            "work_format": "ugc_only",
            "topics": [],
            "blogger_gender": "m",
            "display_name": "User",
            "birth_date": "15.05.1995",
        },
    )
    assert response.status_code == 400
    assert "detail" in response.json()


def test_miniapp_api_orders_invalid_order_type_returns_400(
    client: TestClient,
) -> None:
    """POST /miniapp/api/orders with invalid order_type returns 400."""
    init_data = _make_valid_init_data("test_token", 44444)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="44444",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    adv = AdvertiserProfile(
        user_id=user_id,
        phone="+7900",
        brand="B",
        site_link=None,
        city=None,
        company_activity=None,
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=adv)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    dispatcher["order_service"] = MagicMock()
    response = client.post(
        "/miniapp/api/orders",
        json={
            "init_data": init_data,
            "product_link": "https://x.com/p",
            "offer_text": "Valid offer text with at least twenty chars.",
            "price": 100,
            "bloggers_needed": 1,
            "order_type": "invalid_type",
        },
    )
    assert response.status_code == 400
    assert "order_type" in response.json().get("detail", "").lower()


def test_miniapp_api_create_order_invalid_geography_400(
    client: TestClient,
) -> None:
    """POST /orders with invalid geography returns 400."""
    init_data = _make_valid_init_data("test_token", 88892)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="88892",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    adv = AdvertiserProfile(
        user_id=user_id,
        phone="+7900",
        brand="B",
        site_link=None,
        city=None,
        company_activity=None,
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=adv)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    dispatcher["order_service"] = MagicMock()
    response = client.post(
        "/miniapp/api/orders",
        json={
            "init_data": init_data,
            "product_link": "https://example.com/p",
            "offer_text": "Valid offer text with at least twenty chars.",
            "price": 1000,
            "bloggers_needed": 1,
            "order_type": "ugc_only",
            "geography": "/profile",
        },
    )
    assert response.status_code == 400
    assert "detail" in response.json()


def test_miniapp_api_create_order_validation_fails(
    client: TestClient,
) -> None:
    """POST /miniapp/api/orders with short offer_text returns 400."""
    init_data = _make_valid_init_data("test_token", 88889)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="88889",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    adv = AdvertiserProfile(
        user_id=user_id,
        phone="+7900",
        brand="B",
        site_link=None,
        city=None,
        company_activity=None,
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=adv)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    dispatcher["order_service"] = MagicMock()
    response = client.post(
        "/miniapp/api/orders",
        json={
            "init_data": init_data,
            "product_link": "https://example.com/p",
            "offer_text": "Short",
            "price": 1000,
            "bloggers_needed": 1,
            "order_type": "ugc_only",
        },
    )
    assert response.status_code == 400
    assert "detail" in response.json()


def test_miniapp_api_create_order_service_raises_user_not_found_404(
    client: TestClient,
) -> None:
    """POST /orders when order_service raises UserNotFoundError -> 404."""
    from ugc_bot.application.errors import UserNotFoundError

    init_data = _make_valid_init_data("test_token", 88891)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="88891",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    adv = AdvertiserProfile(
        user_id=user_id,
        phone="+7900",
        brand="B",
        site_link=None,
        city=None,
        company_activity=None,
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=adv)
    mock_order_svc = MagicMock()
    mock_order_svc.create_order = AsyncMock(
        side_effect=UserNotFoundError("Advertiser not found")
    )
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    dispatcher["order_service"] = mock_order_svc
    response = client.post(
        "/miniapp/api/orders",
        json={
            "init_data": init_data,
            "product_link": "https://example.com/p",
            "offer_text": "Valid offer text with at least twenty chars.",
            "price": 1000,
            "bloggers_needed": 1,
            "order_type": "ugc_only",
        },
    )
    assert response.status_code == 404
    assert "detail" in response.json()


def test_miniapp_api_create_order_service_raises_order_creation_error(
    client: TestClient,
) -> None:
    """POST /orders when order_service raises OrderCreationError -> 400."""
    from ugc_bot.application.errors import OrderCreationError

    init_data = _make_valid_init_data("test_token", 88890)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="88890",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    adv = AdvertiserProfile(
        user_id=user_id,
        phone="+7900",
        brand="B",
        site_link=None,
        city=None,
        company_activity=None,
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=adv)
    mock_order_svc = MagicMock()
    mock_order_svc.create_order = AsyncMock(
        side_effect=OrderCreationError("Invalid order")
    )
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    dispatcher["order_service"] = mock_order_svc
    response = client.post(
        "/miniapp/api/orders",
        json={
            "init_data": init_data,
            "product_link": "https://example.com/p",
            "offer_text": "Valid offer text with at least twenty chars.",
            "price": 1000,
            "bloggers_needed": 1,
            "order_type": "ugc_only",
        },
    )
    assert response.status_code == 400
    assert "detail" in response.json()


def test_miniapp_api_register_advertiser_service_error(
    client: TestClient,
) -> None:
    """Register advertiser when service raises returns 400."""
    init_data = _make_valid_init_data("test_token", 11117)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="11117",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_svc = MagicMock()
    mock_svc.register_advertiser = AsyncMock(
        side_effect=AdvertiserRegistrationError("Brand already exists.")
    )
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["advertiser_registration_service"] = mock_svc
    response = client.post(
        "/miniapp/api/register/advertiser",
        json={
            "init_data": init_data,
            "phone": "89001234567",
            "brand": "Brand",
            "site_link": None,
            "city": None,
            "company_activity": None,
            "display_name": None,
        },
    )
    assert response.status_code == 400
    assert "Brand" in response.json().get("detail", "")


def test_miniapp_api_register_advertiser_invalid_display_name_400(
    client: TestClient,
) -> None:
    """Register advertiser with invalid display_name returns 400."""
    init_data = _make_valid_init_data("test_token", 11113)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="11113",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    response = client.post(
        "/miniapp/api/register/advertiser",
        json={
            "init_data": init_data,
            "phone": "+79001234567",
            "brand": "Brand",
            "site_link": None,
            "city": None,
            "company_activity": None,
            "display_name": "X",
        },
    )
    assert response.status_code == 400
    assert "detail" in response.json()


def test_miniapp_api_register_advertiser_site_link_validation(
    client: TestClient,
) -> None:
    """Register advertiser with invalid site_link returns 400."""
    init_data = _make_valid_init_data("test_token", 11112)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="11112",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    response = client.post(
        "/miniapp/api/register/advertiser",
        json={
            "init_data": init_data,
            "phone": "89001234567",
            "brand": "Brand",
            "site_link": "not-a-valid-url!!!",
            "city": None,
            "company_activity": None,
            "display_name": None,
        },
    )
    assert response.status_code == 400
    assert "detail" in response.json()


def test_miniapp_api_register_blogger_invalid_birth_date(
    client: TestClient,
) -> None:
    """Register blogger with invalid birth_date returns 400."""
    init_data = _make_valid_init_data("test_token", 55558)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="55558",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_blogger_svc = MagicMock()
    mock_blogger_svc.get_profile_by_instagram_url = AsyncMock(return_value=None)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["blogger_registration_service"] = mock_blogger_svc
    response = client.post(
        "/miniapp/api/register/blogger",
        json={
            "init_data": init_data,
            "instagram_url": "https://instagram.com/user",
            "city": "Moscow",
            "audience_geo": "РФ",
            "audience_age_min": 18,
            "audience_age_max": 35,
            "audience_gender": "all",
            "price": 1000,
            "barter": False,
            "work_format": "ugc_only",
            "topics": ["tech"],
            "blogger_gender": "m",
            "display_name": "User",
            "birth_date": "32.13.2000",
        },
    )
    assert response.status_code == 400
    assert "detail" in response.json()


def test_miniapp_api_create_order_barter_required(client: TestClient) -> None:
    """POST /miniapp/api/orders with price 0 and no barter returns 400."""
    init_data = _make_valid_init_data("test_token", 88890)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="88890",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    adv = AdvertiserProfile(
        user_id=user_id,
        phone="+7900",
        brand="B",
        site_link=None,
        city=None,
        company_activity=None,
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=adv)
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    dispatcher["order_service"] = MagicMock()
    response = client.post(
        "/miniapp/api/orders",
        json={
            "init_data": init_data,
            "product_link": "https://example.com/p",
            "offer_text": "Valid offer text with at least twenty chars.",
            "price": 0,
            "bloggers_needed": 1,
            "order_type": "ugc_only",
            "barter_description": "",
        },
    )
    assert response.status_code == 400
    assert "detail" in response.json()


def test_miniapp_api_create_order_service_error(
    client: TestClient,
) -> None:
    """Create order when service raises returns 400."""
    init_data = _make_valid_init_data("test_token", 88891)
    user_id = uuid4()
    user = User(
        user_id=user_id,
        external_id="88891",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    adv = AdvertiserProfile(
        user_id=user_id,
        phone="+7900",
        brand="B",
        site_link=None,
        city=None,
        company_activity=None,
    )
    mock_urs = MagicMock()
    mock_urs.get_user = AsyncMock(return_value=user)
    mock_ps = MagicMock()
    mock_ps.get_advertiser_profile = AsyncMock(return_value=adv)
    mock_order_svc = MagicMock()
    mock_order_svc.create_order = AsyncMock(
        side_effect=OrderCreationError("Invalid link.")
    )
    dispatcher = app.state.dispatcher
    dispatcher["user_role_service"] = mock_urs
    dispatcher["profile_service"] = mock_ps
    dispatcher["order_service"] = mock_order_svc
    response = client.post(
        "/miniapp/api/orders",
        json={
            "init_data": init_data,
            "product_link": "https://example.com/p",
            "offer_text": "Valid offer text with at least twenty chars.",
            "price": 1000,
            "bloggers_needed": 1,
            "order_type": "ugc_only",
        },
    )
    assert response.status_code == 400
    assert "detail" in response.json()


def test_webhook_metrics(client: TestClient) -> None:
    """Metrics endpoint returns Prometheus format."""
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")
    assert b"ugc_" in response.content or b"python_" in response.content


def test_webhook_records_http_metrics(client: TestClient) -> None:
    """HTTP middleware records request metrics (RED method)."""
    client.get("/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    content = response.content.decode()
    assert "ugc_http_requests_total" in content
    assert "ugc_http_request_duration_seconds" in content


def test_webhook_records_telegram_metrics_on_success(
    client: TestClient,
) -> None:
    """Valid webhook increments ugc_telegram_webhook_received_total."""
    payload = {
        "update_id": 123456789,
        "message": {
            "message_id": 1,
            "date": 1609459200,
            "chat": {"id": 123, "type": "private", "username": "testuser"},
            "from": {
                "id": 123,
                "is_bot": False,
                "first_name": "Test",
                "username": "testuser",
            },
            "text": "hello",
        },
    }
    client.post("/webhook/telegram", json=payload)
    response = client.get("/metrics")
    assert b"ugc_telegram_webhook_received_total" in response.content


def test_webhook_records_telegram_invalid_on_bad_json(
    client: TestClient,
) -> None:
    """Invalid JSON webhook increments ugc_telegram_webhook_invalid_total."""
    client.post(
        "/webhook/telegram",
        content="not json",
        headers={"Content-Type": "application/json"},
    )
    response = client.get("/metrics")
    assert b"ugc_telegram_webhook_invalid_total" in response.content


def test_webhook_records_telegram_invalid_on_bad_update(
    client: TestClient,
) -> None:
    """Invalid Update payload increments ugc_telegram_webhook_invalid_total."""
    client.post(
        "/webhook/telegram",
        json={"update_id": "invalid", "message": None},
        headers={"Content-Type": "application/json"},
    )
    response = client.get("/metrics")
    assert b"ugc_telegram_webhook_invalid_total" in response.content


def test_webhook_post_update_returns_200(client: TestClient) -> None:
    """POST /webhook/telegram with valid Update returns 200."""
    # Minimal Telegram Update payload (message)
    payload = {
        "update_id": 123456789,
        "message": {
            "message_id": 1,
            "date": 1609459200,
            "chat": {
                "id": 123,
                "type": "private",
                "username": "testuser",
            },
            "from": {
                "id": 123,
                "is_bot": False,
                "first_name": "Test",
                "username": "testuser",
            },
            "text": "hello",
        },
    }
    response = client.post("/webhook/telegram", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_webhook_uses_fallback_semaphore_when_not_in_state(
    client: TestClient,
) -> None:
    """When app.state has no webhook_semaphore, handler creates one."""
    # Simulate missing semaphore (e.g. test or legacy path)
    if hasattr(app.state, "webhook_semaphore"):
        delattr(app.state, "webhook_semaphore")
    payload = {
        "update_id": 999,
        "message": {
            "message_id": 1,
            "date": 1609459200,
            "chat": {"id": 1, "type": "private"},
            "from": {"id": 1, "is_bot": False, "first_name": "x"},
            "text": "hi",
        },
    }
    response = client.post(
        "/webhook/telegram",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "test_secret"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_webhook_background_task_logs_processing_error(
    client: TestClient,
) -> None:
    """When feed_update raises in background task, handler still returns 200."""
    # Make the dispatcher's feed_update raise so the task's except block runs
    dispatcher = app.state.dispatcher
    dispatcher.feed_update = AsyncMock(
        side_effect=RuntimeError("processing err")
    )
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 1609459200,
            "chat": {"id": 1, "type": "private"},
            "from": {"id": 1, "is_bot": False, "first_name": "x"},
            "text": "hi",
        },
    }
    response = client.post(
        "/webhook/telegram",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "test_secret"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    # Allow background task to run so coverage sees the except block
    time.sleep(0.25)


def test_webhook_rejects_invalid_json(client: TestClient) -> None:
    """POST with invalid JSON returns 400 or 422."""
    response = client.post(
        "/webhook/telegram",
        content="not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code in (400, 422)


def test_webhook_lifespan_raises_when_base_url_empty() -> None:
    """Lifespan raises ValueError when WEBHOOK_BASE_URL is empty."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "WEBHOOK_BASE_URL": "",
            "WEBHOOK_SECRET": "secret",
        }
    )
    with (
        patch(
            "ugc_bot.telegram_webhook_app.load_config",
            return_value=config,
        ),
        pytest.raises(ValueError, match="WEBHOOK_BASE_URL is required"),
        TestClient(app),
    ):
        pass


def test_webhook_lifespan_raises_when_secret_empty() -> None:
    """Lifespan raises ValueError when WEBHOOK_SECRET is empty."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "WEBHOOK_BASE_URL": "https://test.example.com",
            "WEBHOOK_SECRET": "",
        }
    )
    with (
        patch(
            "ugc_bot.telegram_webhook_app.load_config",
            return_value=config,
        ),
        pytest.raises(ValueError, match="WEBHOOK_SECRET is required"),
        TestClient(app),
    ):
        pass


def test_http_middleware_records_metrics_on_http_exception(
    client: TestClient,
) -> None:
    """Middleware records status_code when HTTPException is raised."""
    response = client.get("/nonexistent")
    assert response.status_code == 404
    metrics_response = client.get("/metrics")
    assert b"ugc_http_requests_total" in metrics_response.content


def test_exception_handler_returns_200_for_webhook_path() -> None:
    """Exception on webhook path returns 200 (Telegram requirement)."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage

    with (
        patch(
            "ugc_bot.telegram_webhook_app.load_config",
            return_value=_test_config(),
        ),
        patch(
            "ugc_bot.telegram_webhook_app.create_storage",
            new_callable=AsyncMock,
        ),
        patch("ugc_bot.telegram_webhook_app.build_dispatcher") as mock_build,
        patch("ugc_bot.telegram_webhook_app.Bot") as MockBot,
        patch(
            "ugc_bot.telegram_webhook_app.record_telegram_webhook_received",
            side_effect=RuntimeError("Simulated error"),
        ),
    ):
        dp = Dispatcher(storage=MemoryStorage())
        mock_bot_texts = MagicMock()
        mock_bot_texts.load_from_db = AsyncMock(return_value=None)
        dp["bot_texts_service"] = mock_bot_texts
        mock_build.return_value = dp
        fake_bot = MagicMock()
        fake_bot.set_webhook = AsyncMock(return_value=True)
        fake_bot.delete_webhook = AsyncMock(return_value=True)
        fake_bot.session = MagicMock()
        fake_bot.session.close = AsyncMock()
        MockBot.return_value = fake_bot

        with TestClient(
            app,
            raise_server_exceptions=False,
            headers={"X-Telegram-Bot-Api-Secret-Token": "test_secret"},
        ) as c:
            payload = {
                "update_id": 1,
                "message": {
                    "message_id": 1,
                    "date": 1609459200,
                    "chat": {"id": 1, "type": "private"},
                    "from": {
                        "id": 1,
                        "is_bot": False,
                        "first_name": "x",
                    },
                    "text": "hi",
                },
            }
            response = c.post("/webhook/telegram", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert data.get("status") == "error"
            assert "message" in data


def test_exception_handler_returns_500_for_non_webhook_path() -> None:
    """Unhandled exception on non-webhook path returns 500."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage

    with (
        patch(
            "ugc_bot.telegram_webhook_app.load_config",
            return_value=_test_config(),
        ),
        patch(
            "ugc_bot.telegram_webhook_app.create_storage",
            new_callable=AsyncMock,
        ),
        patch("ugc_bot.telegram_webhook_app.build_dispatcher") as mock_build,
        patch("ugc_bot.telegram_webhook_app.Bot") as MockBot,
    ):
        dp = Dispatcher(storage=MemoryStorage())
        mock_bot_texts = MagicMock()
        mock_bot_texts.load_from_db = AsyncMock(return_value=None)
        dp["bot_texts_service"] = mock_bot_texts
        mock_build.return_value = dp
        fake_bot = MagicMock()
        fake_bot.set_webhook = AsyncMock(return_value=True)
        fake_bot.delete_webhook = AsyncMock(return_value=True)
        fake_bot.session = MagicMock()
        fake_bot.session.close = AsyncMock()
        MockBot.return_value = fake_bot

        async def _failing() -> None:
            raise RuntimeError("Simulated internal error")

        app.add_api_route(
            "/test-failing-route-xyz",
            _failing,
            methods=["GET"],
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get("/test-failing-route-xyz")
                assert response.status_code == 500
                assert "detail" in response.json()
        finally:
            app.router.routes = [
                r
                for r in app.router.routes
                if getattr(r, "path", "") != "/test-failing-route-xyz"
            ]


def test_webhook_rejects_invalid_secret() -> None:
    """POST without correct secret when WEBHOOK_SECRET is set returns 403."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "WEBHOOK_BASE_URL": "https://test.example.com",
            "WEBHOOK_SECRET": "my_secret",
        }
    )
    with (
        patch(
            "ugc_bot.telegram_webhook_app.load_config",
            return_value=config,
        ),
        patch(
            "ugc_bot.telegram_webhook_app.create_storage",
            new_callable=AsyncMock,
        ),
        patch("ugc_bot.telegram_webhook_app.build_dispatcher") as mock_build,
        patch("ugc_bot.telegram_webhook_app.Bot") as MockBot,
    ):
        fake_dp = MagicMock()
        fake_dp.feed_update = AsyncMock(return_value=None)
        mock_bot_texts = MagicMock()
        mock_bot_texts.load_from_db = AsyncMock(return_value=None)
        fake_dp.__getitem__ = lambda self, k: (
            mock_bot_texts if k == "bot_texts_service" else MagicMock()
        )
        mock_build.return_value = fake_dp
        fake_bot = MagicMock()
        fake_bot.set_webhook = AsyncMock(return_value=True)
        fake_bot.delete_webhook = AsyncMock(return_value=True)
        fake_bot.session = MagicMock()
        fake_bot.session.close = AsyncMock()
        MockBot.return_value = fake_bot

        with TestClient(app) as c:
            payload = {
                "update_id": 1,
                "message": {
                    "message_id": 1,
                    "date": 1609459200,
                    "chat": {"id": 1, "type": "private"},
                    "from": {
                        "id": 1,
                        "is_bot": False,
                        "first_name": "x",
                    },
                    "text": "hi",
                },
            }
            # No secret header
            response = c.post("/webhook/telegram", json=payload)
            assert response.status_code == 403

            # Wrong secret
            response = c.post(
                "/webhook/telegram",
                json=payload,
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
            )
            assert response.status_code == 403

            # Correct secret
            response = c.post(
                "/webhook/telegram",
                json=payload,
                headers={"X-Telegram-Bot-Api-Secret-Token": "my_secret"},
            )
            assert response.status_code == 200


@pytest.mark.asyncio
async def test_set_webhook_with_retry_succeeds_after_flood_control() -> None:
    """set_webhook retries on TelegramRetryAfter, succeeds on second attempt."""
    bot = MagicMock()
    set_webhook = AsyncMock(
        side_effect=[
            TelegramRetryAfter(
                method="SetWebhook",
                message="Too Many Requests: retry after 1",
                retry_after=1,
            ),
            True,
        ]
    )
    bot.set_webhook = set_webhook

    with patch(
        "ugc_bot.telegram_webhook_app.asyncio.sleep", new_callable=AsyncMock
    ):
        await _set_webhook_with_retry(
            bot, "https://test.example.com/webhook", None
        )

    assert set_webhook.call_count == 2


@pytest.mark.asyncio
async def test_set_webhook_with_retry_raises_after_max_retries() -> None:
    """set_webhook re-raises TelegramRetryAfter after exhausting retries."""
    bot = MagicMock()
    bot.set_webhook = AsyncMock(
        side_effect=TelegramRetryAfter(
            method="SetWebhook",
            message="Too Many Requests: retry after 1",
            retry_after=1,
        )
    )

    with (
        patch(
            "ugc_bot.telegram_webhook_app.asyncio.sleep", new_callable=AsyncMock
        ),
        pytest.raises(TelegramRetryAfter),
    ):
        await _set_webhook_with_retry(
            bot, "https://test.example.com/webhook", None
        )

    assert bot.set_webhook.call_count == 5

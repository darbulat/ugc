"""Tests for Telegram webhook application."""

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramRetryAfter
from fastapi import HTTPException
from fastapi.testclient import TestClient

from tests.unit.test_miniapp_auth import _make_valid_init_data
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import AdvertiserProfile, Order, User
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    OrderType,
    UserStatus,
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
        offer_text="Offer",
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
            "offer_text": "Offer",
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
            "topics": {},
            "blogger_gender": "m",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("ok") is True
    assert data.get("user_id") == str(user_id)


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
            "offer_text": "T",
            "price": 100,
            "bloggers_needed": 1,
            "order_type": "invalid_type",
        },
    )
    assert response.status_code == 400
    assert "order_type" in response.json().get("detail", "").lower()


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

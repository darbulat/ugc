"""Tests for Telegram webhook application."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramRetryAfter
from fastapi.testclient import TestClient

from ugc_bot.config import AppConfig
from ugc_bot.telegram_webhook_app import _set_webhook_with_retry, app


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
        mock_build.return_value = Dispatcher(storage=MemoryStorage())
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


def test_webhook_health(client: TestClient) -> None:
    """Health endpoint returns ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
        mock_build.return_value = Dispatcher(storage=MemoryStorage())
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
        mock_build.return_value = Dispatcher(storage=MemoryStorage())
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

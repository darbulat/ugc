"""Tests for Instagram webhook application."""

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import BloggerProfile, User
from ugc_bot.domain.enums import AudienceGender, MessengerType, UserStatus
from ugc_bot.instagram_webhook_app import (
    _notify_user_verification_success,
    _verify_signature,
    app,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryInstagramVerificationRepository,
    InMemoryUserRepository,
)


@pytest.fixture
def test_config() -> AppConfig:
    """Create test configuration."""
    return AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "INSTAGRAM_WEBHOOK_VERIFY_TOKEN": "test_verify_token",
            "INSTAGRAM_APP_SECRET": "test_app_secret",
            "ADMIN_INSTAGRAM_USERNAME": "admin_test",
        }
    )


@pytest.fixture
def client() -> TestClient:
    """Create test client."""
    return TestClient(app)


def _create_signature(payload: bytes, secret: str) -> str:
    """Create webhook signature for testing."""
    computed = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={computed}"


def test_webhook_health(client: TestClient) -> None:
    """Health endpoint returns ok."""

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_verify_signature_rejects_non_prefixed() -> None:
    """Reject signatures without sha256 prefix."""

    assert _verify_signature(b"payload", "invalid", "secret") is False


@pytest.mark.asyncio
async def test_notify_user_verification_user_missing(test_config: AppConfig) -> None:
    """No notification when user is missing."""

    service = InstagramVerificationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
        instagram_api_client=None,
    )
    await _notify_user_verification_success(uuid4(), service, test_config)


@pytest.mark.asyncio
async def test_notify_user_verification_missing_telegram_user(
    test_config: AppConfig,
) -> None:
    """No notification when Telegram user record is missing."""

    user_repo = InMemoryUserRepository()
    user = User(
        user_id=uuid4(),
        external_id="external",
        messenger_type=MessengerType.MAX,
        username="test_user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=None,
    )
    await user_repo.save(user)
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
        instagram_api_client=None,
    )
    await _notify_user_verification_success(user.user_id, service, test_config)


@pytest.mark.asyncio
async def test_notify_user_verification_success(test_config: AppConfig) -> None:
    """Send notification when user and telegram record exist."""

    class DummySession:
        async def close(self) -> None:
            return None

    class DummyBot:
        def __init__(self, token: str) -> None:
            self.token = token
            self.session = DummySession()
            self.sent = []

        async def send_message(self, chat_id: int, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.sent.append((chat_id, text, kwargs))

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user = User(
        user_id=uuid4(),
        external_id="12345",
        messenger_type=MessengerType.TELEGRAM,
        username="test_user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=None,
    )
    await user_repo.save(user)
    await blogger_repo.save(
        BloggerProfile(
            user_id=user.user_id,
            instagram_url="https://instagram.com/test_user",
            confirmed=True,
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=None,
        )
    )
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        verification_repo=InMemoryInstagramVerificationRepository(),
        instagram_api_client=None,
    )

    with patch("aiogram.Bot", DummyBot):
        await _notify_user_verification_success(user.user_id, service, test_config)


@patch("ugc_bot.instagram_webhook_app.load_config")
def test_webhook_verification_success(
    mock_load_config: MagicMock,
    client: TestClient,
    test_config: AppConfig,
) -> None:
    """Test successful webhook verification."""
    mock_load_config.return_value = test_config
    response = client.get(
        "/webhook/instagram",
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "1234567890",
            "hub.verify_token": "test_verify_token",
        },
    )
    assert response.status_code == 200
    assert response.text == "1234567890"


@patch("ugc_bot.instagram_webhook_app.load_config")
def test_webhook_verification_invalid_mode(
    mock_load_config: MagicMock,
    client: TestClient,
    test_config: AppConfig,
) -> None:
    """Test webhook verification with invalid mode."""
    mock_load_config.return_value = test_config
    response = client.get(
        "/webhook/instagram",
        params={
            "hub.mode": "invalid",
            "hub.challenge": "1234567890",
            "hub.verify_token": "test_verify_token",
        },
    )
    assert response.status_code == 400


@patch("ugc_bot.instagram_webhook_app.load_config")
def test_webhook_verification_invalid_token(
    mock_load_config: MagicMock,
    client: TestClient,
    test_config: AppConfig,
) -> None:
    """Test webhook verification with invalid token."""
    mock_load_config.return_value = test_config
    response = client.get(
        "/webhook/instagram",
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "1234567890",
            "hub.verify_token": "wrong_token",
        },
    )
    assert response.status_code == 403


@patch("ugc_bot.instagram_webhook_app.load_config")
def test_webhook_verification_missing_challenge(
    mock_load_config: MagicMock,
    client: TestClient,
    test_config: AppConfig,
) -> None:
    """Test webhook verification with missing challenge."""
    mock_load_config.return_value = test_config
    response = client.get(
        "/webhook/instagram",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "test_verify_token",
        },
    )
    assert response.status_code == 400


@patch("ugc_bot.instagram_webhook_app.load_config")
@patch("ugc_bot.instagram_webhook_app.Container")
@pytest.mark.asyncio
async def test_webhook_event_processing_success(
    mock_container_cls: MagicMock,
    mock_load_config: MagicMock,
    client: TestClient,
    test_config: AppConfig,
) -> None:
    """Test successful webhook event processing."""
    mock_load_config.return_value = test_config

    # Setup repositories
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()

    user = User(
        user_id=uuid4(),
        external_id="123456",
        messenger_type=MessengerType.TELEGRAM,
        username="test_user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=None,
    )
    await user_repo.save(user)

    await blogger_repo.save(
        BloggerProfile(
            user_id=user.user_id,
            instagram_url="https://instagram.com/test_user",
            confirmed=False,
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=None,
        )
    )

    verification_service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        verification_repo=verification_repo,
        instagram_api_client=None,
    )
    verification = await verification_service.generate_code(user.user_id)

    mock_container_cls.return_value.build_instagram_verification_service.return_value = verification_service

    # Create webhook payload
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "page_id",
                "time": 1234567890,
                "messaging": [
                    {
                        "sender": {"id": "instagram_user_id"},
                        "recipient": {"id": "page_id"},
                        "timestamp": 1234567890,
                        "message": {
                            "mid": "message_id",
                            "text": verification.code,
                        },
                    }
                ],
            }
        ],
    }

    payload_bytes = json.dumps(payload).encode("utf-8")
    signature = _create_signature(
        payload_bytes, test_config.instagram.instagram_app_secret
    )

    response = client.post(
        "/webhook/instagram",
        content=payload_bytes,
        headers={"X-Hub-Signature-256": signature},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    # Verify profile was confirmed
    profile = await blogger_repo.get_by_user_id(user.user_id)
    assert profile is not None
    assert profile.confirmed is True


@patch("ugc_bot.instagram_webhook_app.load_config")
def test_webhook_event_invalid_signature(
    mock_load_config: MagicMock,
    client: TestClient,
    test_config: AppConfig,
) -> None:
    """Test webhook event with invalid signature."""
    mock_load_config.return_value = test_config

    payload = {"object": "instagram", "entry": []}
    payload_bytes = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/webhook/instagram",
        content=payload_bytes,
        headers={"X-Hub-Signature-256": "sha256=invalid_signature"},
    )

    assert response.status_code == 403


@patch("ugc_bot.instagram_webhook_app.load_config")
def test_webhook_event_missing_signature_header(
    mock_load_config: MagicMock,
    client: TestClient,
    test_config: AppConfig,
) -> None:
    """Test webhook event with missing signature header."""

    mock_load_config.return_value = test_config
    payload = {"object": "instagram", "entry": []}
    response = client.post("/webhook/instagram", json=payload)
    assert response.status_code == 400


@patch("ugc_bot.instagram_webhook_app.load_config")
def test_webhook_event_non_instagram_object(
    mock_load_config: MagicMock,
    client: TestClient,
    test_config: AppConfig,
) -> None:
    """Test webhook event with non-Instagram object."""
    mock_load_config.return_value = test_config

    payload = {"object": "facebook", "entry": []}
    payload_bytes = json.dumps(payload).encode("utf-8")
    signature = _create_signature(
        payload_bytes, test_config.instagram.instagram_app_secret
    )

    response = client.post(
        "/webhook/instagram",
        content=payload_bytes,
        headers={"X-Hub-Signature-256": signature},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch("ugc_bot.instagram_webhook_app.load_config")
def test_webhook_event_invalid_json(
    mock_load_config: MagicMock,
    client: TestClient,
    test_config: AppConfig,
) -> None:
    """Test webhook event with invalid JSON."""
    mock_load_config.return_value = test_config

    payload_bytes = b"invalid json"
    signature = _create_signature(
        payload_bytes, test_config.instagram.instagram_app_secret
    )

    response = client.post(
        "/webhook/instagram",
        content=payload_bytes,
        headers={"X-Hub-Signature-256": signature},
    )

    assert response.status_code == 400


@patch("ugc_bot.instagram_webhook_app.load_config")
@patch("ugc_bot.instagram_webhook_app.Container")
def test_webhook_event_no_app_secret(
    mock_container_cls: MagicMock,
    mock_load_config: MagicMock,
    client: TestClient,
) -> None:
    """Test webhook event processing when app secret is not configured."""
    # Create config without app secret
    config_without_secret = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "INSTAGRAM_WEBHOOK_VERIFY_TOKEN": "test_verify_token",
            "INSTAGRAM_APP_SECRET": "",  # Empty secret
            "ADMIN_INSTAGRAM_USERNAME": "admin_test",
        }
    )
    mock_load_config.return_value = config_without_secret

    verification_service = InstagramVerificationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
        instagram_api_client=None,
    )
    mock_container_cls.return_value.build_instagram_verification_service.return_value = verification_service

    payload = {"object": "instagram", "entry": []}
    payload_bytes = json.dumps(payload).encode("utf-8")

    # Should succeed without signature when secret is empty
    response = client.post(
        "/webhook/instagram",
        content=payload_bytes,
    )

    # Should return 200 because signature verification is skipped
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch("ugc_bot.instagram_webhook_app._notify_user_verification_success")
@patch("ugc_bot.instagram_webhook_app.load_config")
@patch("ugc_bot.instagram_webhook_app._process_webhook_events")
def test_webhook_event_processing_exception(
    mock_process_events: MagicMock,
    mock_load_config: MagicMock,
    mock_notify: MagicMock,
    client: TestClient,
    test_config: AppConfig,
) -> None:
    """Test webhook event handling when processing raises exception."""
    mock_load_config.return_value = test_config
    mock_process_events.side_effect = ValueError("Test exception")

    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "page_id",
                "time": 1234567890,
                "messaging": [
                    {
                        "sender": {"id": "instagram_user_id"},
                        "recipient": {"id": "page_id"},
                        "timestamp": 1234567890,
                        "message": {
                            "mid": "message_id",
                            "text": "SOMECODE",
                        },
                    }
                ],
            }
        ],
    }

    payload_bytes = json.dumps(payload).encode("utf-8")
    signature = _create_signature(
        payload_bytes, test_config.instagram.instagram_app_secret
    )

    response = client.post(
        "/webhook/instagram",
        content=payload_bytes,
        headers={"X-Hub-Signature-256": signature},
    )

    # Should still return 200 to prevent retries
    assert response.status_code == 200
    assert response.json() == {"status": "error", "message": "Test exception"}
    mock_notify.assert_not_called()

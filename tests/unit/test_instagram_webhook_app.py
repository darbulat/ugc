"""Tests for Instagram webhook application."""

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
    VerificationApiUnavailable,
    VerificationLinkSuccess,
    VerificationMismatch,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import BloggerProfile, User
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    UserStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryInstagramVerificationRepository,
    InMemoryUserRepository,
)
from ugc_bot.instagram_webhook_app import (
    _get_chat_id_and_messenger_factory,
    _notify_user_verification_api_unavailable,
    _notify_user_verification_mismatch,
    _notify_user_verification_success,
    _unhandled_exception_handler,
    _verify_signature,
    app,
    main,
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
    computed = hmac.new(
        secret.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()
    return f"sha256={computed}"


def test_webhook_health(client: TestClient) -> None:
    """Health endpoint returns ok."""

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_unhandled_exception_handler_webhook_path_returns_200() -> None:
    """Unhandled exception on webhook path returns 200 with generic message."""
    request = MagicMock()
    request.url.path = "/webhook/instagram"
    exc = ValueError("Unhandled in handler")
    response = await _unhandled_exception_handler(request, exc)
    assert response.status_code == 200
    assert response.body == b'{"status":"error","message":"Internal error"}'


@pytest.mark.asyncio
async def test_unhandled_exception_handler_non_webhook_returns_500() -> None:
    """Unhandled exception on non-webhook path returns 500."""
    request = MagicMock()
    request.url.path = "/health"
    exc = ValueError("Unhandled")
    response = await _unhandled_exception_handler(request, exc)
    assert response.status_code == 500
    assert b"Internal server error" in response.body


def test_verify_signature_rejects_non_prefixed() -> None:
    """Reject signatures without sha256 prefix."""

    assert _verify_signature(b"payload", "invalid", "secret") is False


@pytest.mark.asyncio
async def test_notify_user_verification_user_missing(
    test_config: AppConfig,
) -> None:
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
        max_id="external",
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
        telegram_id="12345",
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
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
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
        await _notify_user_verification_success(
            user.user_id, service, test_config
        )


@pytest.mark.asyncio
async def test_notify_user_verification_mismatch_user_missing(
    test_config: AppConfig,
) -> None:
    """No mismatch notification when user is missing."""
    service = InstagramVerificationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
        instagram_api_client=None,
    )
    await _notify_user_verification_mismatch(uuid4(), service, test_config)


@pytest.mark.asyncio
async def test_notify_user_verification_mismatch_missing_telegram_user(
    test_config: AppConfig,
) -> None:
    """No mismatch notification when external_id is not Telegram chat id."""
    user_repo = InMemoryUserRepository()
    user = User(
        user_id=uuid4(),
        max_id="external",
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
    await _notify_user_verification_mismatch(user.user_id, service, test_config)


@pytest.mark.asyncio
async def test_notify_user_verification_mismatch_success(
    test_config: AppConfig,
) -> None:
    """Mismatch notification sent when user has Telegram chat id."""
    sent: list = []

    class DummySession:
        async def close(self) -> None:
            return None

    class DummyBot:
        def __init__(self, token: str) -> None:
            self.token = token
            self.session = DummySession()

        async def send_message(self, chat_id: int, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            sent.append((chat_id, text, kwargs))

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user = User(
        user_id=uuid4(),
        telegram_id="12345",
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
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
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
        await _notify_user_verification_mismatch(
            user.user_id, service, test_config
        )

    assert len(sent) == 1
    chat_id, text, kwargs = sent[0]
    assert chat_id == 12345
    assert "не совпадает" in text
    assert "Мой профиль" in text
    assert "корректный Instagram" in text
    assert "reply_markup" in kwargs or "keyboard" in kwargs


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
        telegram_id="123456",
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
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
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

    mock_build = (
        mock_container_cls.return_value.build_instagram_verification_service
    )
    mock_build.return_value = verification_service

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
    assert response.json() == {"status": "error", "message": "Internal error"}
    mock_notify.assert_not_called()


@patch("ugc_bot.instagram_webhook_app.log_startup_info")
@patch("ugc_bot.instagram_webhook_app.configure_logging")
@patch("ugc_bot.instagram_webhook_app.load_config")
@patch("uvicorn.run")
def test_main_logs_startup_info(
    mock_uvicorn_run: MagicMock,
    mock_load_config: MagicMock,
    mock_configure_logging: MagicMock,
    mock_log_startup_info: MagicMock,
    test_config: AppConfig,
) -> None:
    """main configures logging and logs startup information."""

    _ = mock_uvicorn_run, mock_configure_logging
    mock_load_config.return_value = test_config

    main()

    mock_log_startup_info.assert_called_once()
    assert (
        mock_log_startup_info.call_args.kwargs["service_name"]
        == "instagram-webhook"
    )


@patch("ugc_bot.instagram_webhook_app.load_config")
@patch("ugc_bot.instagram_webhook_app.Container")
@pytest.mark.asyncio
async def test_webhook_startup_event(
    mock_container_cls: MagicMock,
    mock_load_config: MagicMock,
    test_config: AppConfig,
) -> None:
    """Startup event loads config and logs."""
    mock_load_config.return_value = test_config
    mock_container_cls.return_value.dispose = AsyncMock()
    from ugc_bot.instagram_webhook_app import lifespan

    app = FastAPI()
    async with lifespan(app):
        pass

    mock_load_config.assert_called()


@patch("ugc_bot.instagram_webhook_app.load_config")
@patch("ugc_bot.instagram_webhook_app.Container")
@pytest.mark.asyncio
async def test_webhook_entry_empty_messaging(
    mock_container_cls: MagicMock,
    mock_load_config: MagicMock,
    client: TestClient,
    test_config: AppConfig,
) -> None:
    """Entry with empty messaging is skipped."""
    mock_load_config.return_value = test_config
    mock_build = (
        mock_container_cls.return_value.build_instagram_verification_service
    )
    mock_build.return_value = InstagramVerificationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
        instagram_api_client=None,
    )
    payload = {
        "object": "instagram",
        "entry": [{"id": "page1", "time": 123, "messaging": []}],
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


@patch("ugc_bot.instagram_webhook_app.load_config")
@patch("ugc_bot.instagram_webhook_app.Container")
@pytest.mark.asyncio
async def test_webhook_echo_and_self_messages_skipped(
    mock_container_cls: MagicMock,
    mock_load_config: MagicMock,
    client: TestClient,
    test_config: AppConfig,
) -> None:
    """Echo and self messages are skipped."""
    mock_load_config.return_value = test_config
    mock_build = (
        mock_container_cls.return_value.build_instagram_verification_service
    )
    mock_build.return_value = InstagramVerificationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
        instagram_api_client=None,
    )
    for is_echo, is_self in [(True, False), (False, True)]:
        payload = {
            "object": "instagram",
            "entry": [
                {
                    "id": "page1",
                    "time": 123,
                    "messaging": [
                        {
                            "is_echo": is_echo,
                            "is_self": is_self,
                            "sender": {"id": "123"},
                            "recipient": {"id": "page1"},
                            "message": {"text": "code", "mid": "m1"},
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


@patch("ugc_bot.instagram_webhook_app.load_config")
@patch("ugc_bot.instagram_webhook_app.Container")
@pytest.mark.asyncio
async def test_webhook_no_sender_id_skipped(
    mock_container_cls: MagicMock,
    mock_load_config: MagicMock,
    client: TestClient,
    test_config: AppConfig,
) -> None:
    """Message with no sender id is skipped."""
    mock_load_config.return_value = test_config
    mock_build = (
        mock_container_cls.return_value.build_instagram_verification_service
    )
    mock_build.return_value = InstagramVerificationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
        instagram_api_client=None,
    )
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "page1",
                "time": 123,
                "messaging": [
                    {
                        "sender": {},
                        "recipient": {"id": "page1"},
                        "message": {"text": "code", "mid": "m1"},
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


@patch("ugc_bot.instagram_webhook_app.load_config")
@patch("ugc_bot.instagram_webhook_app.Container")
@pytest.mark.asyncio
async def test_webhook_no_message_object_skipped(
    mock_container_cls: MagicMock,
    mock_load_config: MagicMock,
    client: TestClient,
    test_config: AppConfig,
) -> None:
    """Message with no message object is skipped."""
    mock_load_config.return_value = test_config
    mock_build = (
        mock_container_cls.return_value.build_instagram_verification_service
    )
    mock_build.return_value = InstagramVerificationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
        instagram_api_client=None,
    )
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "page1",
                "time": 123,
                "messaging": [
                    {
                        "sender": {"id": "123"},
                        "recipient": {"id": "page1"},
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


@patch("ugc_bot.instagram_webhook_app.load_config")
@patch("ugc_bot.instagram_webhook_app.Container")
@pytest.mark.asyncio
async def test_webhook_empty_text_skipped(
    mock_container_cls: MagicMock,
    mock_load_config: MagicMock,
    client: TestClient,
    test_config: AppConfig,
) -> None:
    """Message with empty text is skipped."""
    mock_load_config.return_value = test_config
    mock_build = (
        mock_container_cls.return_value.build_instagram_verification_service
    )
    mock_build.return_value = InstagramVerificationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
        instagram_api_client=None,
    )
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "page1",
                "time": 123,
                "messaging": [
                    {
                        "sender": {"id": "123"},
                        "recipient": {"id": "page1"},
                        "message": {"text": "   ", "mid": "m1"},
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


@patch("ugc_bot.instagram_webhook_app._notify_user_verification_success")
@patch("ugc_bot.instagram_webhook_app.load_config")
@patch("ugc_bot.instagram_webhook_app.Container")
@pytest.mark.asyncio
async def test_webhook_verification_exception_logged(
    mock_container_cls: MagicMock,
    mock_load_config: MagicMock,
    mock_notify: MagicMock,
    client: TestClient,
    test_config: AppConfig,
) -> None:
    """When verify_code raises, exception is logged and processing continues."""
    mock_load_config.return_value = test_config
    verification_service = MagicMock()
    verification_service.verify_code_by_instagram_sender = MagicMock(
        side_effect=RuntimeError("Verification failed")
    )
    mock_build = (
        mock_container_cls.return_value.build_instagram_verification_service
    )
    mock_build.return_value = verification_service
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "page1",
                "time": 123,
                "messaging": [
                    {
                        "sender": {"id": "123"},
                        "recipient": {"id": "page1"},
                        "message": {"text": "CODE", "mid": "m1"},
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
    mock_notify.assert_not_called()


@patch("ugc_bot.instagram_webhook_app._notify_user_verification_mismatch")
@patch("ugc_bot.instagram_webhook_app._notify_user_verification_success")
@patch("ugc_bot.instagram_webhook_app.load_config")
@patch("ugc_bot.instagram_webhook_app.Container")
@pytest.mark.asyncio
async def test_webhook_verification_mismatch_calls_notify_mismatch(
    mock_container_cls: MagicMock,
    mock_load_config: MagicMock,
    mock_notify_success: MagicMock,
    mock_notify_mismatch: MagicMock,
    client: TestClient,
    test_config: AppConfig,
) -> None:
    """When verify returns VerificationMismatch, notify_mismatch is called."""
    mock_load_config.return_value = test_config
    user_id = uuid4()
    verification_service = MagicMock()
    verification_service.verify_code_by_instagram_sender = AsyncMock(
        return_value=VerificationMismatch(
            user_id=user_id,
            profile_username="profile_user",
            api_username="api_user",
        )
    )
    mock_build = (
        mock_container_cls.return_value.build_instagram_verification_service
    )
    mock_build.return_value = verification_service
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "page1",
                "time": 123,
                "messaging": [
                    {
                        "sender": {"id": "123"},
                        "recipient": {"id": "page1"},
                        "message": {"text": "CODE", "mid": "m1"},
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
    mock_notify_mismatch.assert_called_once()
    call_args = mock_notify_mismatch.call_args
    assert call_args[0][0] == user_id
    mock_notify_success.assert_not_called()


@patch("ugc_bot.instagram_webhook_app.load_config")
@patch("ugc_bot.instagram_webhook_app.Container")
@pytest.mark.asyncio
async def test_webhook_empty_entries_list_returns_ok(
    mock_container_cls: MagicMock,
    mock_load_config: MagicMock,
    client: TestClient,
    test_config: AppConfig,
) -> None:
    """Webhook with empty entries list returns 200 (line 407-408)."""
    mock_load_config.return_value = test_config
    mock_build = (
        mock_container_cls.return_value.build_instagram_verification_service
    )
    mock_build.return_value = InstagramVerificationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
        instagram_api_client=None,
    )
    payload = {"object": "instagram", "entry": []}
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


@pytest.mark.asyncio
async def test_notify_user_verification_mismatch_exception_is_logged(
    test_config: AppConfig,
) -> None:
    """Exception during mismatch notification is caught and logged (308-309)."""
    user_repo = InMemoryUserRepository()
    user = User(
        user_id=uuid4(),
        telegram_id="12345",
        messenger_type=MessengerType.TELEGRAM,
        username="test_user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=None,
    )
    await user_repo.save(user)
    blogger_repo = InMemoryBloggerProfileRepository()
    await blogger_repo.save(
        BloggerProfile(
            user_id=user.user_id,
            instagram_url="https://instagram.com/test_user",
            confirmed=False,
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=None,
        )
    )
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        verification_repo=InMemoryInstagramVerificationRepository(),
        instagram_api_client=None,
    )

    class BrokenSession:
        async def close(self) -> None:
            return None

    class BrokenBot:
        def __init__(self, token: str) -> None:
            self.session = BrokenSession()

        async def send_message(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            raise RuntimeError("Telegram is down")

    with patch("aiogram.Bot", BrokenBot):
        # Should not raise — exception is caught and logged
        await _notify_user_verification_mismatch(
            user.user_id, service, test_config
        )


@pytest.mark.asyncio
async def test_notify_user_verification_api_unavailable(
    test_config: AppConfig,
) -> None:
    """Send api-unavailable notification to user."""

    class DummySession:
        async def close(self) -> None:
            return None

    class DummyBot:
        def __init__(self, token: str) -> None:
            self.token = token
            self.session = DummySession()
            self.sent: list = []

        async def send_message(self, chat_id: int, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.sent.append((chat_id, text, kwargs))

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user = User(
        user_id=uuid4(),
        telegram_id="12345",
        messenger_type=MessengerType.TELEGRAM,
        username="test_user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=None,
    )
    await user_repo.save(user)
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        verification_repo=InMemoryInstagramVerificationRepository(),
    )

    with patch("aiogram.Bot", DummyBot):
        await _notify_user_verification_api_unavailable(
            user.user_id, service, test_config
        )


@pytest.mark.asyncio
async def test_notify_user_verification_api_unavailable_no_user(
    test_config: AppConfig,
) -> None:
    """No crash when user not found for api-unavailable notification."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        verification_repo=InMemoryInstagramVerificationRepository(),
    )

    await _notify_user_verification_api_unavailable(
        uuid4(), service, test_config
    )


def test_get_chat_id_max_user_with_config():
    """Max user with max_bot config returns max_chat_id."""
    user = MagicMock()
    user.messenger_type = MessengerType.MAX
    user.max_chat_id = "12345"
    user.max_id = "99"
    user.telegram_id = None
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "t",
            "DATABASE_URL": "sqlite:///:memory:",
            "MAX_BOT_TOKEN": "max_token",
        }
    )
    chat_id, cm = _get_chat_id_and_messenger_factory(user, config)
    assert chat_id == "12345"
    assert cm is not None


def test_get_chat_id_max_user_no_config():
    """Max user without max_bot config returns None."""
    user = MagicMock()
    user.messenger_type = MessengerType.MAX
    user.max_chat_id = "12345"
    user.max_id = "99"
    user.telegram_id = None
    config = AppConfig.model_validate(
        {"BOT_TOKEN": "t", "DATABASE_URL": "sqlite:///:memory:"}
    )
    chat_id, cm = _get_chat_id_and_messenger_factory(user, config)
    assert chat_id is None
    assert cm is None


def test_get_chat_id_telegram_user():
    """Telegram user returns telegram_id."""
    user = MagicMock()
    user.messenger_type = MessengerType.TELEGRAM
    user.max_id = None
    user.telegram_id = "99999"
    config = AppConfig.model_validate(
        {"BOT_TOKEN": "t", "DATABASE_URL": "sqlite:///:memory:"}
    )
    chat_id, cm = _get_chat_id_and_messenger_factory(user, config)
    assert chat_id == "99999"
    assert cm is not None


def test_get_chat_id_no_messenger_id():
    """User with no telegram_id and not Max returns None."""
    user = MagicMock()
    user.messenger_type = MessengerType.TELEGRAM
    user.max_id = None
    user.telegram_id = None
    config = AppConfig.model_validate(
        {"BOT_TOKEN": "t", "DATABASE_URL": "sqlite:///:memory:"}
    )
    chat_id, cm = _get_chat_id_and_messenger_factory(user, config)
    assert chat_id is None
    assert cm is None


@pytest.mark.asyncio
async def test_create_max_messenger_yields_client() -> None:
    """_create_max_messenger yields MaxMessengerClient."""
    from ugc_bot.instagram_webhook_app import _create_max_messenger

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "t",
            "DATABASE_URL": "sqlite:///:memory:",
            "MAX_BOT_TOKEN": "max_token",
        }
    )
    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.close = AsyncMock()
        mock_session_cls.return_value = mock_session
        async with _create_max_messenger(config) as client:
            from ugc_bot.infrastructure.messenger.max.client import (
                MaxMessengerClient,
            )

            assert isinstance(client, MaxMessengerClient)
        mock_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_notify_user_verification_success_max_user() -> None:
    """Send notification via Max messenger for Max users."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user = User(
        user_id=uuid4(),
        max_id="23759393",
        max_chat_id="252972060",
        messenger_type=MessengerType.MAX,
        username="max_user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=None,
    )
    await user_repo.save(user)
    await blogger_repo.save(
        BloggerProfile(
            user_id=user.user_id,
            instagram_url="https://instagram.com/test",
            confirmed=True,
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=None,
        )
    )
    service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        verification_repo=InMemoryInstagramVerificationRepository(),
        instagram_api_client=None,
    )
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "MAX_BOT_TOKEN": "max_test_token",
        }
    )
    mock_client = AsyncMock()
    with patch(
        "ugc_bot.instagram_webhook_app._create_max_messenger",
    ) as mock_cm:
        mock_cm.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.return_value.__aexit__ = AsyncMock(return_value=False)
        await _notify_user_verification_success(user.user_id, service, config)
    mock_client.send_text.assert_called_once()
    call_kwargs = mock_client.send_text.call_args
    assert call_kwargs.kwargs["chat_id"] == "252972060"


@pytest.mark.asyncio
async def test_webhook_api_unavailable_calls_notify(
    test_config: AppConfig,
) -> None:
    """VerificationApiUnavailable triggers api-unavailable notification."""
    service = MagicMock(spec=InstagramVerificationService)
    service.verify_code_by_instagram_sender = AsyncMock(
        return_value=VerificationApiUnavailable(user_id=uuid4())
    )

    with patch(
        "ugc_bot.instagram_webhook_app."
        "_notify_user_verification_api_unavailable",
        new_callable=AsyncMock,
    ) as mock_notify:
        from ugc_bot.instagram_webhook_app import (
            _process_single_messaging_event,
        )

        event = {
            "sender": {"id": "sender_123"},
            "message": {"text": "ABC123"},
        }
        result = await _process_single_messaging_event(
            event, service, test_config
        )
        assert result is True
        mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_webhook_link_success_calls_both_notifications(
    test_config: AppConfig,
) -> None:
    """VerificationLinkSuccess triggers both notifications."""
    user_id = uuid4()
    linked_user_id = uuid4()
    service = MagicMock(spec=InstagramVerificationService)
    service.verify_code_by_instagram_sender = AsyncMock(
        return_value=VerificationLinkSuccess(
            user_id=user_id, linked_user_id=linked_user_id
        )
    )

    with (
        patch(
            "ugc_bot.instagram_webhook_app._notify_user_verification_success",
            new_callable=AsyncMock,
        ) as mock_notify_success,
        patch(
            "ugc_bot.instagram_webhook_app._notify_user_account_linked",
            new_callable=AsyncMock,
        ) as mock_notify_linked,
    ):
        from ugc_bot.instagram_webhook_app import (
            _process_single_messaging_event,
        )

        event = {
            "sender": {"id": "sender_123"},
            "message": {"text": "ABC123"},
        }
        result = await _process_single_messaging_event(
            event, service, test_config
        )
        assert result is True
        mock_notify_success.assert_called_once()
        assert mock_notify_success.call_args[0][0] == user_id
        mock_notify_linked.assert_called_once()
        assert mock_notify_linked.call_args[0][0] == linked_user_id

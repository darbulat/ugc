"""Tests for Max messenger webhook application and supporting components."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ugc_bot.bot.max.middleware import resolve_locale
from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.messenger.max.adapter import MaxEventAdapter
from ugc_bot.max_webhook_app import handle_max_webhook, health

# ---------------------------------------------------------------------------
# MaxEventAdapter tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_webhook_routes_message():
    adapter = MaxEventAdapter()
    router = MaxRouter()
    called = []

    @router.message(lambda m: m.text == "/start")
    async def start(msg, deps):
        called.append("start")

    event = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 1, "username": "test"},
            "recipient": {"chat_id": 2},
            "body": {"mid": "m1", "text": "/start"},
        },
    }

    incoming = adapter.from_message(event)
    await router.route_message(incoming, {})
    assert called == ["start"]


@pytest.mark.asyncio
async def test_max_webhook_routes_callback():
    adapter = MaxEventAdapter()
    router = MaxRouter()
    called = []

    @router.callback(lambda c: (c.data or "").startswith("order:"))
    async def order_handler(cb, deps):
        called.append(cb.data)

    event = {
        "update_type": "message_callback",
        "callback": {
            "callback_id": "cb_1",
            "user": {"user_id": 1, "username": "test"},
            "payload": "order:123",
        },
        "message": {
            "recipient": {"chat_id": 2},
            "body": {"mid": "m1", "text": "old"},
        },
    }

    incoming = adapter.from_callback(event)
    await router.route_callback(incoming, {})
    assert called == ["order:123"]


@pytest.mark.asyncio
async def test_route_callback_removes_keyboard():
    """route_callback should remove inline keyboard before handler."""
    router = MaxRouter()

    @router.callback(lambda c: True)
    async def handler(cb, deps):
        pass

    incoming = MagicMock()
    incoming.data = "test:action"
    incoming.message_id = "mid_123"
    incoming.chat_id = "chat_1"
    incoming.callback_id = "cb_1"

    mock_client = AsyncMock()
    deps = {"messenger_client": mock_client}

    await router.route_callback(incoming, deps)
    mock_client.edit_reply_markup.assert_called_once_with(
        chat_id="chat_1",
        message_id="mid_123",
        keyboard=None,
    )


@pytest.mark.asyncio
async def test_route_callback_no_message_id_skips_removal():
    """route_callback should skip keyboard removal if no message_id."""
    router = MaxRouter()

    @router.callback(lambda c: True)
    async def handler(cb, deps):
        pass

    incoming = MagicMock()
    incoming.data = "test:action"
    incoming.message_id = None
    incoming.chat_id = "chat_1"

    mock_client = AsyncMock()
    deps = {"messenger_client": mock_client}

    await router.route_callback(incoming, deps)
    mock_client.edit_reply_markup.assert_not_called()


def test_adapter_from_message_fields():
    adapter = MaxEventAdapter()
    event = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 42, "username": "alice"},
            "recipient": {"chat_id": 99},
            "body": {"mid": "abc", "text": "hello"},
        },
    }
    msg = adapter.from_message(event)
    assert msg.chat_id == "99"
    assert msg.text == "hello"
    assert msg.message_id == "abc"
    assert msg.user.external_id == "42"
    assert msg.user.username == "alice"
    assert msg.user.messenger_type == MessengerType.MAX


def test_adapter_from_callback_fields():
    adapter = MaxEventAdapter()
    event = {
        "update_type": "message_callback",
        "callback": {
            "callback_id": "cb_99",
            "user": {"user_id": 7, "username": "bob"},
            "payload": "action:do",
        },
        "message": {
            "recipient": {"chat_id": 55},
            "body": {"mid": "m99", "text": "prev"},
        },
    }
    cb = adapter.from_callback(event)
    assert cb.callback_id == "cb_99"
    assert cb.chat_id == "55"
    assert cb.data == "action:do"
    assert cb.message_id == "m99"
    assert cb.message_text == "prev"
    assert cb.user.external_id == "7"
    assert cb.user.messenger_type == MessengerType.MAX


def test_adapter_from_bot_started_fields():
    adapter = MaxEventAdapter()
    event = {
        "update_type": "bot_started",
        "chat_id": 252972060,
        "user": {"user_id": 23759393, "username": "alice"},
    }
    msg = adapter.from_bot_started(event)
    assert msg.chat_id == "252972060"
    assert msg.user.external_id == "23759393"
    assert msg.text == "/start"
    assert msg.message_id is None
    assert msg.user.messenger_type == MessengerType.MAX
    assert msg.user.username == "alice"


def test_adapter_from_pre_checkout_raises():
    adapter = MaxEventAdapter()
    import pytest as _pt

    with _pt.raises(NotImplementedError):
        adapter.from_pre_checkout({})


# ---------------------------------------------------------------------------
# MaxRouter tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_router_no_handler_matched_message():
    """No handler registered: route_message should not raise."""
    router = MaxRouter()
    adapter = MaxEventAdapter()
    event = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 1, "username": "u"},
            "recipient": {"chat_id": 1},
            "body": {"mid": "m1", "text": "unmatched"},
        },
    }
    incoming = adapter.from_message(event)
    await router.route_message(incoming, {})  # no error


@pytest.mark.asyncio
async def test_router_no_handler_matched_callback():
    """No handler registered: route_callback should not raise."""
    router = MaxRouter()
    adapter = MaxEventAdapter()
    event = {
        "update_type": "message_callback",
        "callback": {
            "callback_id": "c1",
            "user": {"user_id": 1, "username": "u"},
            "payload": "other:1",
        },
        "message": {"recipient": {"chat_id": 1}, "body": {"mid": "m1"}},
    }
    incoming = adapter.from_callback(event)
    await router.route_callback(incoming, {})  # no error


@pytest.mark.asyncio
async def test_router_handler_exception_is_swallowed():
    """If a handler raises, route_message should not propagate it."""
    router = MaxRouter()
    adapter = MaxEventAdapter()

    @router.message(lambda m: True)
    async def bad_handler(msg, deps):
        raise RuntimeError("boom")

    event = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 1, "username": "u"},
            "recipient": {"chat_id": 1},
            "body": {"mid": "m1", "text": "hi"},
        },
    }
    incoming = adapter.from_message(event)
    await router.route_message(incoming, {})  # should not raise


@pytest.mark.asyncio
async def test_router_callback_handler_exception_is_swallowed():
    """If a callback handler raises, route_callback should not propagate it."""
    router = MaxRouter()
    adapter = MaxEventAdapter()

    @router.callback(lambda c: True)
    async def bad_cb(cb, deps):
        raise ValueError("oops")

    event = {
        "update_type": "message_callback",
        "callback": {
            "callback_id": "c1",
            "user": {"user_id": 1, "username": "u"},
            "payload": "x",
        },
        "message": {"recipient": {"chat_id": 1}, "body": {}},
    }
    incoming = adapter.from_callback(event)
    await router.route_callback(incoming, {})  # should not raise


# ---------------------------------------------------------------------------
# Adapter contact extraction tests
# ---------------------------------------------------------------------------


def test_adapter_extracts_contact_phone_from_vcf():
    """ContactAttachment with vcf_info should populate contact_phone."""
    adapter = MaxEventAdapter()
    event = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 42, "username": "alice"},
            "recipient": {"chat_id": 99},
            "body": {
                "mid": "m1",
                "text": None,
                "attachments": [
                    {
                        "type": "contact",
                        "payload": {
                            "vcf_info": (
                                "BEGIN:VCARD\n"
                                "VERSION:3.0\n"
                                "FN:Alice\n"
                                "TEL:+79001234567\n"
                                "END:VCARD"
                            ),
                            "tam_info": {"user_id": 42, "name": "Alice"},
                        },
                    }
                ],
            },
        },
    }
    msg = adapter.from_message(event)
    assert msg.contact_phone == "+79001234567"


def test_adapter_contact_phone_none_without_attachment():
    """Without ContactAttachment, contact_phone should be None."""
    adapter = MaxEventAdapter()
    event = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 1, "username": "u"},
            "recipient": {"chat_id": 1},
            "body": {"mid": "m1", "text": "+79009009090"},
        },
    }
    msg = adapter.from_message(event)
    assert msg.contact_phone is None


def test_adapter_contact_phone_none_when_vcf_empty():
    """ContactAttachment with empty vcf_info should leave contact_phone None."""
    adapter = MaxEventAdapter()
    event = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 1, "username": "u"},
            "recipient": {"chat_id": 1},
            "body": {
                "mid": "m1",
                "text": None,
                "attachments": [
                    {
                        "type": "contact",
                        "payload": {"vcf_info": None, "tam_info": None},
                    }
                ],
            },
        },
    }
    msg = adapter.from_message(event)
    assert msg.contact_phone is None


def test_adapter_extracts_location_from_attachment():
    """LocationAttachment should populate location_lat/lon."""
    adapter = MaxEventAdapter()
    event = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 1, "username": "u"},
            "recipient": {"chat_id": 1},
            "body": {
                "mid": "m1",
                "text": None,
                "attachments": [
                    {
                        "type": "location",
                        "latitude": 55.7558,
                        "longitude": 37.6173,
                    }
                ],
            },
        },
    }
    msg = adapter.from_message(event)
    assert msg.location_lat == 55.7558
    assert msg.location_lon == 37.6173


def test_adapter_location_none_without_attachment():
    """Without LocationAttachment, location should be None."""
    adapter = MaxEventAdapter()
    event = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 1, "username": "u"},
            "recipient": {"chat_id": 1},
            "body": {"mid": "m1", "text": "Moscow"},
        },
    }
    msg = adapter.from_message(event)
    assert msg.location_lat is None
    assert msg.location_lon is None


# ---------------------------------------------------------------------------
# VCF phone extraction unit tests
# ---------------------------------------------------------------------------


def test_extract_phone_from_vcf_standard():
    from ugc_bot.infrastructure.messenger.max.adapter import (
        _extract_phone_from_vcf,
    )

    vcf = "BEGIN:VCARD\nVERSION:3.0\nTEL:+79001234567\nEND:VCARD"
    assert _extract_phone_from_vcf(vcf) == "+79001234567"


def test_extract_phone_from_vcf_with_type():
    from ugc_bot.infrastructure.messenger.max.adapter import (
        _extract_phone_from_vcf,
    )

    vcf = "BEGIN:VCARD\nTEL;TYPE=CELL:+79005556677\nEND:VCARD"
    assert _extract_phone_from_vcf(vcf) == "+79005556677"


def test_extract_phone_from_vcf_none():
    from ugc_bot.infrastructure.messenger.max.adapter import (
        _extract_phone_from_vcf,
    )

    assert _extract_phone_from_vcf(None) is None
    assert _extract_phone_from_vcf("") is None
    assert _extract_phone_from_vcf("BEGIN:VCARD\nEND:VCARD") is None


# ---------------------------------------------------------------------------
# Middleware tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_locale_returns_user_language():
    adapter = MaxEventAdapter()
    event = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 1, "username": "u"},
            "recipient": {"chat_id": 1},
            "body": {"mid": "m1", "text": "hi"},
        },
    }
    incoming = adapter.from_message(event)
    mock_user = MagicMock()
    mock_user.language = "en"
    mock_service = AsyncMock()
    mock_service.get_user = AsyncMock(return_value=mock_user)
    result = await resolve_locale(incoming, mock_service)
    assert result == "en"


@pytest.mark.asyncio
async def test_resolve_locale_fallback_when_no_language():
    adapter = MaxEventAdapter()
    event = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 1, "username": "u"},
            "recipient": {"chat_id": 1},
            "body": {"mid": "m1", "text": "hi"},
        },
    }
    incoming = adapter.from_message(event)
    mock_user = MagicMock()
    mock_user.language = None
    mock_service = AsyncMock()
    mock_service.get_user = AsyncMock(return_value=mock_user)
    result = await resolve_locale(incoming, mock_service)
    assert result == "ru"


@pytest.mark.asyncio
async def test_resolve_locale_fallback_when_user_not_found():
    adapter = MaxEventAdapter()
    event = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 1, "username": "u"},
            "recipient": {"chat_id": 1},
            "body": {"mid": "m1", "text": "hi"},
        },
    }
    incoming = adapter.from_message(event)
    mock_service = AsyncMock()
    mock_service.get_user = AsyncMock(return_value=None)
    result = await resolve_locale(incoming, mock_service)
    assert result == "ru"


@pytest.mark.asyncio
async def test_resolve_locale_fallback_on_exception():
    adapter = MaxEventAdapter()
    event = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 1, "username": "u"},
            "recipient": {"chat_id": 1},
            "body": {"mid": "m1", "text": "hi"},
        },
    }
    incoming = adapter.from_message(event)
    mock_service = AsyncMock()
    mock_service.get_user = AsyncMock(side_effect=RuntimeError("db error"))
    result = await resolve_locale(incoming, mock_service, default_locale="kk")
    assert result == "kk"


# ---------------------------------------------------------------------------
# Webhook endpoint tests (handle_max_webhook)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_endpoint():
    """Health endpoint returns ok."""
    resp = await health()
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_handle_max_webhook_invalid_json():
    """Non-JSON body returns 400."""
    state = MagicMock()
    state.webhook_secret = None
    request = MagicMock()
    request.app.state = state
    request.headers = {}
    request.json = AsyncMock(side_effect=ValueError("bad json"))
    resp = await handle_max_webhook(request)
    assert resp.status_code == 400


def _make_app_state(router=None):
    """Create a mock app state for webhook handler tests."""
    mock_user_role_service = AsyncMock()
    mock_user_role_service.get_user = AsyncMock(return_value=None)

    state = MagicMock()
    state.event_adapter = MaxEventAdapter()
    state.max_router = router or MaxRouter()
    state.bot_services = {"user_role_service": mock_user_role_service}
    state.messenger_client = MagicMock()
    state.config = MagicMock()
    state.config.market.default_locale = "ru"
    state.redis = MagicMock()
    state.webhook_secret = None
    return state


@pytest.mark.asyncio
async def test_handle_max_webhook_message_created():
    """message_created events are routed to max_router.route_message."""
    router = MaxRouter()
    called = []

    @router.message(lambda m: True)
    async def handler(msg, deps):
        called.append(msg.text)

    state = _make_app_state(router)
    request = MagicMock()
    request.app.state = state
    request.json = AsyncMock(
        return_value={
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": 1, "username": "u"},
                "recipient": {"chat_id": 1},
                "body": {"mid": "m1", "text": "hello"},
            },
        }
    )
    resp = await handle_max_webhook(request)
    assert resp.status_code == 200
    assert called == ["hello"]


@pytest.mark.asyncio
async def test_handle_max_webhook_message_callback():
    """message_callback events are routed to max_router.route_callback."""
    router = MaxRouter()
    called = []

    @router.callback(lambda c: True)
    async def handler(cb, deps):
        called.append(cb.data)

    state = _make_app_state(router)
    request = MagicMock()
    request.app.state = state
    request.json = AsyncMock(
        return_value={
            "update_type": "message_callback",
            "callback": {
                "callback_id": "cb1",
                "user": {"user_id": 2, "username": "u"},
                "payload": "act:1",
            },
            "message": {"recipient": {"chat_id": 3}, "body": {}},
        }
    )
    resp = await handle_max_webhook(request)
    assert resp.status_code == 200
    assert called == ["act:1"]


@pytest.mark.asyncio
async def test_handle_max_webhook_unknown_update_type():
    """Unknown update_type is logged and returns ok."""
    state = _make_app_state()
    request = MagicMock()
    request.app.state = state
    request.json = AsyncMock(return_value={"update_type": "some_future_event"})
    resp = await handle_max_webhook(request)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_handle_max_webhook_exception_returns_500():
    """Exceptions during routing are caught and response is 500."""
    state = _make_app_state()
    state.event_adapter = MagicMock()
    state.event_adapter.from_message.side_effect = RuntimeError("parse error")
    request = MagicMock()
    request.app.state = state
    request.headers = {}
    request.json = AsyncMock(
        return_value={
            "update_type": "message_created",
            "message": {},
        }
    )
    resp = await handle_max_webhook(request)
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_handle_max_webhook_rejects_invalid_secret():
    """Webhook rejects requests with invalid secret."""
    state = _make_app_state()
    state.webhook_secret = "my-secret"
    request = MagicMock()
    request.app.state = state
    request.headers = {"X-Max-Bot-Api-Secret": "wrong-secret"}
    request.json = AsyncMock(return_value={"update_type": "message_created"})
    resp = await handle_max_webhook(request)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_handle_max_webhook_accepts_valid_secret():
    """Webhook accepts requests with valid secret."""
    state = _make_app_state()
    state.webhook_secret = "my-secret"
    request = MagicMock()
    request.app.state = state
    request.headers = {"X-Max-Bot-Api-Secret": "my-secret"}
    request.json = AsyncMock(return_value={"update_type": "some_future_event"})
    resp = await handle_max_webhook(request)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Config: MaxBotConfig
# ---------------------------------------------------------------------------


def test_max_bot_config_absent_when_no_token():
    """max_bot is None when MAX_BOT_TOKEN is not set."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
        }
    )
    assert config.max_bot is None


def test_max_bot_config_present_when_token_set():
    """max_bot is populated when MAX_BOT_TOKEN is set."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "MAX_BOT_TOKEN": "max_secret_token",
            "MAX_BOT_WEBHOOK_URL": "https://example.com/webhook/max",
        }
    )
    assert config.max_bot is not None
    assert config.max_bot.token == "max_secret_token"
    assert config.max_bot.webhook_url == "https://example.com/webhook/max"


# ---------------------------------------------------------------------------
# MaxRedisStateStore tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_store_get_set_state():
    """set_state and get_state work correctly."""
    from ugc_bot.infrastructure.messenger.max.state import MaxRedisStateStore

    redis = AsyncMock()
    redis.get = AsyncMock(return_value="waiting_input")
    redis.set = AsyncMock()

    store = MaxRedisStateStore(redis=redis, chat_id="1", user_id="2")
    result = await store.get_state()
    assert result == "waiting_input"

    await store.set_state("new_state")
    redis.set.assert_called_once()


@pytest.mark.asyncio
async def test_state_store_set_state_none_deletes():
    """set_state(None) deletes the state key."""
    from ugc_bot.infrastructure.messenger.max.state import MaxRedisStateStore

    redis = AsyncMock()
    redis.delete = AsyncMock()

    store = MaxRedisStateStore(redis=redis, chat_id="1", user_id="2")
    await store.set_state(None)
    redis.delete.assert_called_once()


@pytest.mark.asyncio
async def test_state_store_update_and_get_data():
    """update_data merges data and get_data returns it."""
    import json

    from ugc_bot.infrastructure.messenger.max.state import MaxRedisStateStore

    stored: list[str] = []
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)

    async def fake_set(key, value):
        stored.append(value)

    redis.set = AsyncMock(side_effect=fake_set)

    store = MaxRedisStateStore(redis=redis, chat_id="1", user_id="2")
    await store.update_data(name="Alice", step=3)

    assert len(stored) == 1
    data = json.loads(stored[0])
    assert data == {"name": "Alice", "step": 3}


@pytest.mark.asyncio
async def test_state_store_get_data_returns_empty_when_none():
    """get_data returns empty dict when no data stored."""
    from ugc_bot.infrastructure.messenger.max.state import MaxRedisStateStore

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)

    store = MaxRedisStateStore(redis=redis, chat_id="1", user_id="2")
    result = await store.get_data()
    assert result == {}


@pytest.mark.asyncio
async def test_state_store_get_data_corrupted_json_returns_empty():
    """get_data returns empty dict and logs on corrupted JSON."""
    from ugc_bot.infrastructure.messenger.max.state import MaxRedisStateStore

    redis = AsyncMock()
    redis.get = AsyncMock(return_value="not-valid-json{{{")

    store = MaxRedisStateStore(redis=redis, chat_id="1", user_id="2")
    result = await store.get_data()
    assert result == {}


@pytest.mark.asyncio
async def test_state_store_clear():
    """clear removes state and data keys."""
    from ugc_bot.infrastructure.messenger.max.state import MaxRedisStateStore

    redis = AsyncMock()
    redis.delete = AsyncMock()

    store = MaxRedisStateStore(redis=redis, chat_id="1", user_id="2")
    await store.clear()
    redis.delete.assert_called_once()


# ---------------------------------------------------------------------------
# _lifespan tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_no_max_bot_raises_value_error():
    """When max_bot is None, lifespan raises ValueError."""
    from ugc_bot.max_webhook_app import _lifespan

    mock_config = MagicMock()
    mock_config.max_bot = None
    fake_app = MagicMock()

    with (
        patch("ugc_bot.max_webhook_app.load_config", return_value=mock_config),
        pytest.raises(ValueError, match="MAX_BOT_TOKEN is required"),
    ):
        async with _lifespan(fake_app):
            pass


@pytest.mark.asyncio
async def test_lifespan_with_max_bot_sets_state():
    """When max_bot is configured, lifespan sets up app state."""
    from ugc_bot.max_webhook_app import _lifespan

    mock_config = MagicMock()
    mock_config.max_bot.token = "tok"
    mock_config.max_bot.webhook_url = "https://example.com/webhook/max"
    mock_config.redis.redis_url = "redis://localhost:6379/0"

    fake_app = MagicMock()
    fake_app.state = MagicMock()

    mock_redis = AsyncMock()
    mock_http_session = AsyncMock()
    mock_http_session.close = AsyncMock()
    # Make post return a context manager with status 200
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_http_session.post = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        )
    )

    mock_container = MagicMock()
    mock_container.build_bot_services = MagicMock(return_value={})
    mock_container.dispose = AsyncMock()

    mock_bot = MagicMock()
    mock_bot.session = MagicMock()
    mock_bot.session.close = AsyncMock()

    with (
        patch("ugc_bot.max_webhook_app.load_config", return_value=mock_config),
        patch(
            "ugc_bot.max_webhook_app.Redis.from_url", return_value=mock_redis
        ),
        patch(
            "ugc_bot.max_webhook_app.aiohttp.ClientSession",
            return_value=mock_http_session,
        ),
        patch("ugc_bot.max_webhook_app.Container", return_value=mock_container),
        patch("ugc_bot.max_webhook_app.Bot", return_value=mock_bot),
        patch("ugc_bot.max_webhook_app.TelegramMessengerClient"),
        patch(
            "ugc_bot.max_webhook_app.MaxMessengerClient.set_my_commands",
            new_callable=AsyncMock,
        ),
    ):
        async with _lifespan(fake_app):
            assert fake_app.state.config is mock_config
            assert fake_app.state.max_router is not None
            assert fake_app.state.telegram_messenger_client is not None

    mock_bot.session.close.assert_called_once()
    mock_container.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_webhook_registration_failure_raises():
    """Non-2xx webhook registration raises RuntimeError."""
    from ugc_bot.max_webhook_app import _lifespan

    mock_config = MagicMock()
    mock_config.max_bot.token = "tok"
    mock_config.max_bot.webhook_url = "https://example.com/webhook/max"
    mock_config.redis.redis_url = "redis://localhost:6379/0"

    fake_app = MagicMock()
    fake_app.state = MagicMock()

    mock_redis = AsyncMock()
    mock_http_session = AsyncMock()
    mock_http_session.close = AsyncMock()
    mock_resp = AsyncMock()
    mock_resp.status = 400
    mock_resp.text = AsyncMock(return_value="Bad Request")
    mock_http_session.post = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        )
    )

    mock_container = MagicMock()
    mock_container.build_bot_services = MagicMock(return_value={})
    mock_container.dispose = AsyncMock()

    mock_bot = MagicMock()
    mock_bot.session = MagicMock()
    mock_bot.session.close = AsyncMock()

    with (
        patch("ugc_bot.max_webhook_app.load_config", return_value=mock_config),
        patch(
            "ugc_bot.max_webhook_app.Redis.from_url", return_value=mock_redis
        ),
        patch(
            "ugc_bot.max_webhook_app.aiohttp.ClientSession",
            return_value=mock_http_session,
        ),
        patch("ugc_bot.max_webhook_app.Container", return_value=mock_container),
        patch("ugc_bot.max_webhook_app.Bot", return_value=mock_bot),
        patch("ugc_bot.max_webhook_app.TelegramMessengerClient"),
        pytest.raises(RuntimeError, match="Failed to register Max webhook"),
    ):
        async with _lifespan(fake_app):
            pass


# ---------------------------------------------------------------------------
# Miniapp routes tests
# ---------------------------------------------------------------------------


@pytest.fixture
def max_app_client() -> TestClient:
    """Create test client with mocked lifespan deps."""
    from ugc_bot.max_webhook_app import app

    mock_config = MagicMock()
    mock_config.max_bot.token = "tok"
    mock_config.max_bot.webhook_url = "https://example.com/webhook/max"
    mock_config.max_bot.webhook_secret = None
    mock_config.redis.redis_url = "redis://localhost:6379/0"
    mock_config.market.default_locale = "ru"

    mock_redis = AsyncMock()
    mock_http_session = AsyncMock()
    mock_http_session.close = AsyncMock()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_http_session.post = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        )
    )

    mock_bot_texts = MagicMock()
    mock_bot_texts.load_from_db = AsyncMock(return_value=None)
    mock_bot_texts.get_many = AsyncMock(return_value={})
    mock_geocode_limiter = MagicMock()
    mock_geocode_limiter.allow_async = AsyncMock(return_value=True)

    mock_container = MagicMock()
    mock_container.build_bot_services = MagicMock(
        return_value={
            "bot_texts_service": mock_bot_texts,
            "geocode_public_rate_limiter": mock_geocode_limiter,
        }
    )
    mock_container.dispose = AsyncMock()

    mock_bot = MagicMock()
    mock_bot.session = MagicMock()
    mock_bot.session.close = AsyncMock()

    with (
        patch("ugc_bot.max_webhook_app.load_config", return_value=mock_config),
        patch(
            "ugc_bot.max_webhook_app.Redis.from_url", return_value=mock_redis
        ),
        patch(
            "ugc_bot.max_webhook_app.aiohttp.ClientSession",
            return_value=mock_http_session,
        ),
        patch("ugc_bot.max_webhook_app.Container", return_value=mock_container),
        patch("ugc_bot.max_webhook_app.Bot", return_value=mock_bot),
        patch("ugc_bot.max_webhook_app.TelegramMessengerClient"),
        patch(
            "ugc_bot.max_webhook_app.MaxMessengerClient.set_my_commands",
            new_callable=AsyncMock,
        ),
        TestClient(app) as c,
    ):
        yield c


def test_miniapp_api_routes_mounted(max_app_client: TestClient) -> None:
    """Miniapp API routes are accessible under /miniapp/api prefix."""
    response = max_app_client.post("/miniapp/api/config", json={})
    # 422 = validation error (missing init_data), not 404 = route exists
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_retry_instagram_callback_sets_state() -> None:
    """Retry instagram callback sets FSM to blog_instagram step."""
    from ugc_bot.application.messenger.dto import IncomingCallback, IncomingUser
    from ugc_bot.bot.max.handlers.blogger_registration import (
        STATE_BLOG_INSTAGRAM,
        handle_retry_instagram_callback,
    )

    incoming = IncomingCallback(
        callback_id="cb_1",
        chat_id="chat_42",
        user=IncomingUser(
            external_id="user_1",
            messenger_type=MessengerType.MAX,
            username="tester",
        ),
        data="blogger:retry_instagram",
    )
    messenger_client = AsyncMock()
    state_store = AsyncMock()
    bot_texts_service = AsyncMock()
    bot_texts_service.get = AsyncMock(
        return_value="Пришлите ссылку в формате instagram.com/name"
    )
    deps = {
        "messenger_client": messenger_client,
        "state_store": state_store,
        "bot_texts_service": bot_texts_service,
        "locale": "ru",
    }
    await handle_retry_instagram_callback(incoming, deps)
    messenger_client.answer_callback.assert_called_once_with(callback_id="cb_1")
    messenger_client.send_text.assert_called_once()
    assert messenger_client.send_text.call_args.kwargs["chat_id"] == "chat_42"
    state_store.set_state.assert_called_once_with(STATE_BLOG_INSTAGRAM)

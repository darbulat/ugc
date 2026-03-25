"""Tests for Max messenger webhook application and supporting components."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ugc_bot.bot.max.middleware import resolve_locale
from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.messenger.max.adapter import MaxEventAdapter
from ugc_bot.max_webhook_app import handle_max_webhook

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
            "message": {
                "recipient": {"chat_id": 2},
                "body": {"mid": "m1", "text": "old"},
            },
            "payload": "order:123",
        },
    }

    incoming = adapter.from_callback(event)
    await router.route_callback(incoming, {})
    assert called == ["order:123"]


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
            "message": {
                "recipient": {"chat_id": 55},
                "body": {"mid": "m99", "text": "prev"},
            },
            "payload": "action:do",
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
            "message": {"recipient": {"chat_id": 1}, "body": {"mid": "m1"}},
            "payload": "other:1",
        },
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
            "message": {"recipient": {"chat_id": 1}, "body": {}},
            "payload": "x",
        },
    }
    incoming = adapter.from_callback(event)
    await router.route_callback(incoming, {})  # should not raise


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


def _make_app_state(router=None):
    """Create a mock app state for webhook handler tests."""
    state = MagicMock()
    state.event_adapter = MaxEventAdapter()
    state.max_router = router or MaxRouter()
    state.bot_services = {}
    state.messenger_client = MagicMock()
    state.config = MagicMock()
    state.redis = MagicMock()
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
                "message": {"recipient": {"chat_id": 3}, "body": {}},
                "payload": "act:1",
            },
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
    request.json = AsyncMock(return_value={"update_type": "bot_started"})
    resp = await handle_max_webhook(request)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_handle_max_webhook_exception_returns_ok():
    """Exceptions during routing are caught and response is still ok."""
    state = _make_app_state()
    state.event_adapter = MagicMock()
    state.event_adapter.from_message.side_effect = RuntimeError("parse error")
    request = MagicMock()
    request.app.state = state
    request.json = AsyncMock(
        return_value={
            "update_type": "message_created",
            "message": {},
        }
    )
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
    redis.setex = AsyncMock()

    store = MaxRedisStateStore(redis=redis, chat_id="1", user_id="2")
    result = await store.get_state()
    assert result == "waiting_input"

    await store.set_state("new_state")
    redis.setex.assert_called_once()


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

    async def fake_setex(key, ttl, value):
        stored.append(value)

    redis.setex = AsyncMock(side_effect=fake_setex)

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
async def test_lifespan_no_max_bot_yields_immediately():
    """When max_bot is None, lifespan yields without setup."""
    from ugc_bot.max_webhook_app import _lifespan

    mock_config = MagicMock()
    mock_config.max_bot = None
    fake_app = MagicMock()

    with patch("ugc_bot.max_webhook_app.load_config", return_value=mock_config):
        async with _lifespan(fake_app):
            pass  # should yield without error


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
    ):
        async with _lifespan(fake_app):
            assert fake_app.state.config is mock_config
            assert fake_app.state.max_router is not None

    mock_container.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_webhook_registration_failure_logged():
    """On webhook registration failure (non-2xx), app still starts."""
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
    ):
        async with _lifespan(fake_app):
            pass  # app should still start despite registration failure

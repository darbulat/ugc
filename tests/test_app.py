"""Tests for application setup."""

import asyncio
from datetime import datetime, timezone
from uuid import UUID

import pytest
from aiogram import Router

from ugc_bot.app import (
    _handle_health_connection,
    _json_dumps,
    _run_health_server,
    build_dispatcher,
    create_storage,
    run_bot,
)
from ugc_bot.config import AppConfig


def test_build_dispatcher_requires_database_url() -> None:
    """Ensure build_dispatcher requires database url."""

    with pytest.raises(ValueError):
        build_dispatcher(
            AppConfig.model_validate({"BOT_TOKEN": "token", "DATABASE_URL": ""}),
            include_routers=False,
            storage=None,
        )


def test_build_dispatcher_sets_services() -> None:
    """Ensure dispatcher is built with required services."""

    dispatcher = build_dispatcher(
        AppConfig.model_validate(
            {
                "BOT_TOKEN": "token",
                "DATABASE_URL": "postgresql+psycopg://user:pass@localhost/db",
                "KAFKA_ENABLED": False,
            }
        ),
        include_routers=False,
        storage=None,
    )

    assert dispatcher["user_role_service"] is not None
    assert dispatcher["blogger_registration_service"] is not None
    assert dispatcher["advertiser_registration_service"] is not None
    assert dispatcher["instagram_verification_service"] is not None
    assert dispatcher["order_service"] is not None
    assert dispatcher["offer_dispatch_service"] is not None
    assert dispatcher["offer_response_service"] is not None
    assert dispatcher["payment_service"] is not None


def test_build_dispatcher_includes_routers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Include routers when enabled."""

    monkeypatch.setattr("ugc_bot.app.start_router", Router())
    monkeypatch.setattr("ugc_bot.app.blogger_router", Router())
    monkeypatch.setattr("ugc_bot.app.advertiser_router", Router())
    monkeypatch.setattr("ugc_bot.app.instagram_router", Router())
    monkeypatch.setattr("ugc_bot.app.offer_response_router", Router())
    monkeypatch.setattr("ugc_bot.app.order_router", Router())
    monkeypatch.setattr("ugc_bot.app.payments_router", Router())

    dispatcher = build_dispatcher(
        AppConfig.model_validate(
            {
                "BOT_TOKEN": "token",
                "DATABASE_URL": "postgresql+psycopg://user:pass@localhost/db",
                "KAFKA_ENABLED": False,
            }
        ),
        include_routers=True,
        storage=None,
    )

    assert dispatcher is not None


@pytest.mark.asyncio
async def test_run_bot_uses_dispatcher(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure run_bot wires dispatcher and bot."""

    class FakeDispatcher:
        def __init__(self) -> None:
            self.started = False

        async def start_polling(self, bot) -> None:  # type: ignore[no-untyped-def]
            self.started = True

    class FakeBot:
        def __init__(self, token: str) -> None:
            self.token = token

    fake_dispatcher = FakeDispatcher()

    class FakeStorage:
        async def close(self) -> None:
            pass

    fake_storage = FakeStorage()

    async def fake_create_storage(config):
        return fake_storage

    monkeypatch.setattr(
        "ugc_bot.app.build_dispatcher",
        lambda *args, **kwargs: fake_dispatcher,
    )
    monkeypatch.setattr("ugc_bot.app.create_storage", fake_create_storage)
    monkeypatch.setattr("ugc_bot.app.Bot", FakeBot)
    monkeypatch.setattr(
        "ugc_bot.app.load_config",
        lambda: AppConfig.model_validate(
            {
                "BOT_TOKEN": "token",
                "LOG_LEVEL": "INFO",
                "DATABASE_URL": "db",
            }
        ),
    )

    startup_called: dict[str, object] = {}

    def _fake_startup_log(**kwargs):  # type: ignore[no-untyped-def]
        startup_called.update(kwargs)

    monkeypatch.setattr("ugc_bot.app.log_startup_info", _fake_startup_log)

    await run_bot()
    assert fake_dispatcher.started is True
    assert startup_called.get("service_name") == "ugc-bot"


def test_main_invokes_asyncio(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure main calls asyncio.run."""

    called = {"value": False}

    def fake_run(coro):  # type: ignore[no-untyped-def]
        called["value"] = True
        coro.close()

    monkeypatch.setattr("ugc_bot.app.asyncio.run", fake_run)
    from ugc_bot.app import main

    main()
    assert called["value"] is True


def test_json_dumps_serializes_uuid_and_datetime() -> None:
    """_json_dumps handles UUID and datetime in dict."""
    uid = UUID("00000000-0000-0000-0000-000000000001")
    dt = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    result = _json_dumps({"id": uid, "at": dt})
    assert '"00000000-0000-0000-0000-000000000001"' in result
    assert "2025-01-15" in result


def test_json_dumps_default_raises_for_other_types() -> None:
    """_json_dumps default() calls super().default for non-UUID/datetime."""
    with pytest.raises(TypeError):
        _json_dumps({"bad": object()})


@pytest.mark.asyncio
async def test_create_storage_returns_redis_storage_when_redis_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_storage returns RedisStorage when use_redis_storage is True and redis available."""
    import importlib.util

    if importlib.util.find_spec("redis") is None:
        pytest.skip("redis not installed")
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "t",
            "DATABASE_URL": "sqlite:///x",
            "USE_REDIS_STORAGE": "true",
            "REDIS_URL": "redis://localhost:6379/0",
        }
    )
    from unittest.mock import MagicMock

    monkeypatch.setattr(
        "redis.asyncio.Redis.from_url",
        lambda *args, **kwargs: MagicMock(),
    )
    storage = await create_storage(config)
    from aiogram.fsm.storage.redis import RedisStorage

    assert isinstance(storage, RedisStorage)


@pytest.mark.asyncio
async def test_create_storage_returns_memory_when_redis_disabled() -> None:
    """create_storage returns MemoryStorage when use_redis_storage is False."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "t",
            "DATABASE_URL": "sqlite:///x",
            "USE_REDIS_STORAGE": "false",
        }
    )
    storage = await create_storage(config)
    from aiogram.fsm.storage.memory import MemoryStorage

    assert isinstance(storage, MemoryStorage)


@pytest.mark.asyncio
async def test_create_storage_falls_back_to_memory_on_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_storage falls back to MemoryStorage when redis is not installed."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "t",
            "DATABASE_URL": "sqlite:///x",
            "USE_REDIS_STORAGE": "true",
            "REDIS_URL": "redis://localhost/0",
        }
    )

    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if name == "redis" or name == "redis.asyncio":
            raise ImportError("no redis")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    storage = await create_storage(config)
    from aiogram.fsm.storage.memory import MemoryStorage

    assert isinstance(storage, MemoryStorage)


@pytest.mark.asyncio
async def test_health_server_responds_ok() -> None:
    """Health server responds with 200 and status ok for GET /health."""
    server = await asyncio.start_server(_handle_health_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
        await writer.drain()
        data = await reader.read(512)
        writer.close()
        await writer.wait_closed()
    assert b"200 OK" in data
    assert b'{"status":"ok"}' in data


@pytest.mark.asyncio
async def test_health_server_responds_404_for_other_paths() -> None:
    """Health server responds 404 for non GET /health requests."""
    server = await asyncio.start_server(_handle_health_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET /other HTTP/1.1\r\nHost: localhost\r\n\r\n")
        await writer.drain()
        data = await reader.read(512)
        writer.close()
        await writer.wait_closed()
    assert b"404 Not Found" in data


@pytest.mark.asyncio
async def test_health_server_responds_408_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Health server responds 408 when read times out."""

    async def timeout_wait_for(coro: object, timeout: object = None):  # type: ignore[no-untyped-def]
        await coro  # let read complete so handler enters try block
        raise asyncio.TimeoutError()

    monkeypatch.setattr("ugc_bot.app.asyncio.wait_for", timeout_wait_for)
    reader = asyncio.StreamReader()
    reader.feed_data(b"GET /x HTTP/1.1\r\n\r\n")
    writer = type("Writer", (), {})()
    written: list[bytes] = []

    async def drain() -> None:
        pass

    def write(data: bytes) -> None:
        written.append(data)

    writer.write = write  # type: ignore[attr-defined]
    writer.drain = drain  # type: ignore[attr-defined]
    writer.close = lambda: None  # type: ignore[attr-defined]
    closed_waited: list[bool] = []

    async def wait_closed() -> None:
        closed_waited.append(True)

    writer.wait_closed = wait_closed  # type: ignore[attr-defined]
    await _handle_health_connection(reader, writer)  # type: ignore[arg-type]
    assert any(b"408" in d for d in written)
    assert closed_waited


@pytest.mark.asyncio
async def test_health_server_handles_oserror_on_wait_closed() -> None:
    """Health server handles OSError when writer.wait_closed() is called."""
    reader = asyncio.StreamReader()
    reader.feed_data(b"GET /x HTTP/1.1\r\n\r\n")
    writer = type("Writer", (), {})()
    written: list[bytes] = []

    async def drain() -> None:
        pass

    def write(data: bytes) -> None:
        written.append(data)

    writer.write = write  # type: ignore[attr-defined]
    writer.drain = drain  # type: ignore[attr-defined]
    writer.close = lambda: None  # type: ignore[attr-defined]

    async def wait_closed_raise() -> None:
        raise OSError("closed")

    writer.wait_closed = wait_closed_raise  # type: ignore[attr-defined]
    await _handle_health_connection(reader, writer)  # type: ignore[arg-type]
    assert any(b"404" in d for d in written)


@pytest.mark.asyncio
async def test_health_server_handles_oserror_when_client_closes_early() -> None:
    """Health server handles OSError/ConnectionReset when client closes before read."""
    server = await asyncio.start_server(_handle_health_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET /health HTTP/1.1\r\n\r\n")
        await writer.drain()
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
    # Handler may hit OSError in finally when client already closed


@pytest.mark.asyncio
async def test_run_health_server_starts_and_responds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_run_health_server starts server and responds to health checks."""
    monkeypatch.setattr("ugc_bot.app.BOT_HEALTH_PORT", 19998)
    task = asyncio.create_task(_run_health_server())
    await asyncio.sleep(0.05)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", 19998)
        writer.write(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
        await writer.drain()
        data = await reader.read(512)
        writer.close()
        await writer.wait_closed()
        assert b"200 OK" in data
        assert b'{"status":"ok"}' in data
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

"""Tests for application setup."""

from datetime import datetime, timezone
from uuid import UUID

import pytest
from aiogram import Router

from ugc_bot.app import (
    _json_dumps,
    build_dispatcher,
    create_storage,
)
from ugc_bot.config import AppConfig


def test_build_dispatcher_requires_database_url() -> None:
    """Ensure build_dispatcher requires database url."""

    with pytest.raises(ValueError):
        build_dispatcher(
            AppConfig.model_validate(
                {"BOT_TOKEN": "token", "DATABASE_URL": ""}
            ),
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


def test_build_dispatcher_includes_routers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def _redis_import_works() -> bool:
    """Check if redis can be imported (avoids cffi/cryptography issues)."""
    try:
        from redis.asyncio import Redis  # noqa: F401

        return True
    except BaseException:
        return False


@pytest.mark.asyncio
async def test_create_storage_returns_redis_storage_when_redis_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_storage returns RedisStorage when use_redis and redis ok."""
    import importlib.util

    if importlib.util.find_spec("redis") is None:
        pytest.skip("redis not installed")
    if not _redis_import_works():
        pytest.skip("redis import failed (cffi/cryptography may be broken)")
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
    """create_storage falls back to MemoryStorage when redis not installed."""
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

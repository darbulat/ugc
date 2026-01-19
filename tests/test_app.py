"""Tests for application setup."""

from __future__ import annotations

import pytest
from aiogram import Router

from ugc_bot.app import build_dispatcher, run_bot
from ugc_bot.config import AppConfig


def test_build_dispatcher_requires_database_url() -> None:
    """Ensure build_dispatcher requires database url."""

    with pytest.raises(ValueError):
        build_dispatcher(
            AppConfig.model_validate({"BOT_TOKEN": "token", "DATABASE_URL": ""}),
            include_routers=False,
        )


def test_build_dispatcher_sets_services() -> None:
    """Ensure dispatcher is built with required services."""

    dispatcher = build_dispatcher(
        AppConfig.model_validate(
            {
                "BOT_TOKEN": "token",
                "DATABASE_URL": "postgresql+psycopg://user:pass@localhost/db",
                "OPENAI_ENABLED": False,
            }
        ),
        include_routers=False,
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
                "OPENAI_ENABLED": False,
            }
        ),
        include_routers=True,
    )

    assert dispatcher is not None


def test_build_dispatcher_openai_enabled() -> None:
    """Allow OpenAI selector when enabled."""

    dispatcher = build_dispatcher(
        AppConfig.model_validate(
            {
                "BOT_TOKEN": "token",
                "DATABASE_URL": "postgresql+psycopg://user:pass@localhost/db",
                "OPENAI_ENABLED": True,
                "OPENAI_API_KEY": "test",
            }
        ),
        include_routers=False,
    )

    assert dispatcher["offer_dispatch_service"] is not None


def test_build_dispatcher_requires_openai_key() -> None:
    """Ensure build_dispatcher requires OPENAI_API_KEY."""

    with pytest.raises(ValueError):
        build_dispatcher(
            AppConfig.model_validate(
                {
                    "BOT_TOKEN": "token",
                    "DATABASE_URL": "postgresql://db",
                    "OPENAI_ENABLED": True,
                }
            ),
            include_routers=False,
        )


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

    monkeypatch.setattr(
        "ugc_bot.app.build_dispatcher",
        lambda *_: fake_dispatcher,
    )
    monkeypatch.setattr("ugc_bot.app.Bot", FakeBot)
    monkeypatch.setattr(
        "ugc_bot.app.load_config",
        lambda: AppConfig.model_validate(
            {
                "BOT_TOKEN": "token",
                "LOG_LEVEL": "INFO",
                "DATABASE_URL": "db",
                "OPENAI_API_KEY": "test",
            }
        ),
    )

    await run_bot()
    assert fake_dispatcher.started is True


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

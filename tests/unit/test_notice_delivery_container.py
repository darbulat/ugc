"""Production receipt transports are constructed only after the core gate."""

from unittest.mock import Mock

import pytest

from ugc_bot.config import AppConfig
from ugc_bot.container import Container, service_factory
from ugc_bot.infrastructure.messenger import notice_receipts


def config(*, enabled=False, database="sqlite:///:memory:", max_token=""):
    return AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": database,
            "FINANCIAL_CORE_ENABLED": enabled,
            "KAFKA_ENABLED": False,
            "USE_REDIS_STORAGE": False,
            "REDIS_URL": "",
            "WEBHOOK_BASE_URL": "https://telegram.example.test",
            "MAX_BOT_TOKEN": max_token,
            "MAX_BOT_WEBHOOK_URL": "https://max.example.test/max/webhook",
        }
    )


def test_default_off_builds_neither_receipt_transport_nor_repositories(
    monkeypatch,
):
    current = config()
    assert current.financial.core_enabled is False
    container = Container(current)
    monkeypatch.setattr(
        container,
        "build_repos",
        Mock(side_effect=AssertionError("disabled repository construction")),
    )
    monkeypatch.setattr(
        notice_receipts,
        "TelegramNoticeReceipts",
        Mock(side_effect=AssertionError("disabled transport construction")),
    )
    assert container.build_collaboration_notice_delivery(object()) is None


def test_enabled_factory_uses_sql_current_clock_and_real_one_shot_receipts():
    from ugc_bot.infrastructure.db.repositories.notice_delivery import (
        SqlAlchemyNoticeDeliveryRepository,
    )

    container = Container(config(enabled=True, max_token="synthetic-max-token"))
    bot, max_session = object(), object()
    worker = container.build_collaboration_notice_delivery(
        bot, max_session=max_session
    )
    assert (
        worker.lifecycle.repository
        is container.build_repos()["collaboration_repo"]
    )
    assert worker.transactions is container.transaction_manager
    assert isinstance(worker.repository, SqlAlchemyNoticeDeliveryRepository)
    assert isinstance(worker.transport, notice_receipts.RoutedNoticeReceipts)
    assert isinstance(
        worker.transport.transports["telegram"],
        notice_receipts.TelegramNoticeReceipts,
    )
    assert worker.transport.transports["telegram"].bot is bot
    assert isinstance(
        worker.transport.transports["max"], notice_receipts.MaxNoticeReceipts
    )
    assert worker.transport.transports["max"].session is max_session
    assert worker.miniapp_url == {
        "telegram": "https://telegram.example.test/miniapp/app.html",
        "max": "https://max.example.test/miniapp/max_app.html",
    }
    assert worker.lifecycle.clock.now().tzinfo is not None


@pytest.mark.parametrize(
    "max_token,session", [("", object()), ("synthetic-max-token", None)]
)
def test_unconfigured_max_capability_has_no_implicit_session(
    max_token, session
):
    container = Container(config(enabled=True, max_token=max_token))
    worker = container.build_collaboration_notice_delivery(
        object(), max_session=session
    )
    assert set(worker.transport.transports) == {"telegram"}


def test_enabled_factory_requires_database_before_any_transport(monkeypatch):
    container = Container(config(enabled=True, database=""))
    monkeypatch.setattr(
        notice_receipts,
        "TelegramNoticeReceipts",
        Mock(
            side_effect=AssertionError(
                "transport constructed before database gate"
            )
        ),
    )
    with pytest.raises(ValueError, match="DATABASE_URL"):
        container.build_collaboration_notice_delivery(object())


def test_service_factory_also_checks_core_flag_before_any_dependencies(
    monkeypatch,
):
    from types import SimpleNamespace

    current = SimpleNamespace(financial=SimpleNamespace(core_enabled=False))
    monkeypatch.setattr(
        notice_receipts,
        "TelegramNoticeReceipts",
        Mock(side_effect=AssertionError("disabled transport construction")),
    )
    assert (
        service_factory.build_collaboration_notice_delivery(
            current, {}, None, object()
        )
        is None
    )

"""Characterize scheduler orchestration without starting external clients."""

import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest

from ugc_bot import combined_scheduler as scheduler


def settings(enabled=False):
    return NS(
        feedback=NS(
            feedback_enabled=enabled, feedback_poll_interval_seconds=17
        ),
        role_reminder=NS(role_reminder_enabled=enabled),
        referral=NS(
            referral_reconciliation_enabled=enabled,
            referral_reconciliation_interval_seconds=29,
        ),
        market=NS(default_locale="en"),
        log=NS(log_level="INFO", log_format="JSON"),
        db=NS(database_url="sqlite:///:memory:"),
        bot=NS(bot_token="unused"),
    )


@pytest.fixture
def boundaries(monkeypatch):
    install = Mock()
    client = object()
    monkeypatch.setattr(scheduler, "install_asyncio_exception_handler", install)
    monkeypatch.setattr(
        scheduler, "TelegramMessengerClient", Mock(return_value=client)
    )
    return install, client


@pytest.mark.asyncio
async def test_disabled_schedulers_build_no_dependencies(boundaries, caplog):
    container = Mock()
    await scheduler._run_all(settings(), container, object())
    assert container.mock_calls == []
    boundaries[0].assert_called_once_with("combined-scheduler")
    assert "No schedulers enabled" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_enabled_loops_receive_dependencies_and_cancel_peers_on_failure(
    monkeypatch, boundaries, caplog, failure
):
    config = settings(True)
    config.market.default_locale = ""
    deps = {
        key: object()
        for key in (
            "interaction_repo",
            "interaction_service",
            "user_role_service",
            "profile_service",
            "order_repo",
            "transaction_manager",
            "referral_income_entry_repo",
            "recorder",
        )
    }
    container = Mock()
    container.build_feedback_scheduler_deps.return_value = deps
    container.build_referral_reconciliation_deps.return_value = deps
    started = asyncio.Event()
    cancelled = []
    calls = {}

    async def feedback(*args, **kwargs):
        calls["feedback"] = (args, kwargs)
        await started.wait()
        if failure:
            raise RuntimeError("scheduler backend failed")

    async def reminder(*args):
        calls["reminder"] = args
        if failure:
            try:
                await asyncio.Future()
            finally:
                cancelled.append("reminder")

    async def referral(**kwargs):
        calls["referral"] = kwargs
        started.set()
        if failure:
            try:
                await asyncio.Future()
            finally:
                cancelled.append("referral")

    monkeypatch.setattr(scheduler, "feedback_loop", feedback)
    monkeypatch.setattr(scheduler, "role_reminder_loop", reminder)
    monkeypatch.setattr(scheduler, "referral_loop", referral)
    await scheduler._run_all(config, container, object())
    args, kwargs = calls["feedback"]
    assert args == (
        {"telegram": boundaries[1]},
        deps["interaction_repo"],
        deps["interaction_service"],
        deps["user_role_service"],
        deps["profile_service"],
        deps["order_repo"],
        config.feedback,
    )
    assert kwargs == dict(
        interval_seconds=17,
        transaction_manager=deps["transaction_manager"],
        default_locale="ru",
        bot_texts_service=container.build_bot_texts_service.return_value,
        close_clients_on_exit=False,
    )
    assert calls["reminder"] == (
        {"telegram": boundaries[1]},
        container.build_user_role_service.return_value,
        config,
    )
    assert calls["referral"] == dict(
        income_entry_repo=deps["referral_income_entry_repo"],
        recorder=deps["recorder"],
        order_repo=deps["order_repo"],
        transaction_manager=deps["transaction_manager"],
        interval_seconds=29,
    )
    assert sorted(cancelled) == (["referral", "reminder"] if failure else [])
    assert (
        "Scheduler task failed: feedback-scheduler" in caplog.text
    ) == failure


@pytest.mark.parametrize("database", [False, True])
@pytest.mark.parametrize("has_session", [False, True])
def test_main_validates_database_and_disposes_resources(
    monkeypatch, boundaries, database, has_session
):
    config = settings()
    if not database:
        config.db.database_url = ""
    bot = NS(session=NS(close=AsyncMock()) if has_session else None)
    container = NS(dispose=AsyncMock())
    make_container = Mock(return_value=container)
    make_bot = Mock(return_value=bot)
    logging = Mock()
    monkeypatch.setattr(scheduler, "load_config", lambda: config)
    monkeypatch.setattr(scheduler, "configure_logging", logging)
    monkeypatch.setattr(scheduler, "install_exception_hooks", Mock())
    monkeypatch.setattr(scheduler, "log_startup_info", Mock())
    monkeypatch.setattr(scheduler, "Container", make_container)
    monkeypatch.setattr(scheduler, "Bot", make_bot)
    scheduler.main()
    logging.assert_called_once_with("INFO", json_format=True)
    assert make_container.call_count == int(database)
    assert make_bot.call_count == int(database)
    assert container.dispose.await_count == int(database)
    if has_session:
        assert bot.session.close.await_count == int(database)


def test_main_closes_resources_when_scheduler_setup_fails(monkeypatch):
    config = settings(True)
    container = Mock(dispose=AsyncMock())
    container.build_feedback_scheduler_deps.side_effect = RuntimeError(
        "dependency unavailable"
    )
    bot = NS(session=NS(close=AsyncMock()))
    monkeypatch.setattr(scheduler, "load_config", lambda: config)
    monkeypatch.setattr(scheduler, "configure_logging", Mock())
    monkeypatch.setattr(scheduler, "install_exception_hooks", Mock())
    monkeypatch.setattr(scheduler, "install_asyncio_exception_handler", Mock())
    monkeypatch.setattr(scheduler, "log_startup_info", Mock())
    monkeypatch.setattr(scheduler, "Container", Mock(return_value=container))
    monkeypatch.setattr(scheduler, "Bot", Mock(return_value=bot))
    with pytest.raises(RuntimeError, match="dependency unavailable"):
        scheduler.main()
    bot.session.close.assert_awaited_once()
    container.dispose.assert_awaited_once()

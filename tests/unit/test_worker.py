"""Tests for unified worker entry point."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ugc_bot.config import (
    AdminConfig,
    AppConfig,
    BotConfig,
    DbConfig,
    DocsConfig,
    FeedbackConfig,
    GeocoderConfig,
    InstagramConfig,
    KafkaConfig,
    LogConfig,
    MarketConfig,
    OrderConfig,
    OutboxConfig,
    RedisConfig,
    ReferralConfig,
    RoleReminderConfig,
    WebhookConfig,
)


@pytest.mark.asyncio
async def test_no_close_messenger_client_does_not_close_delegate() -> None:
    """_NoCloseMessengerClient.close() does not call delegate.close()."""
    from ugc_bot.worker import _NoCloseMessengerClient

    delegate = AsyncMock()
    wrapper = _NoCloseMessengerClient(delegate)
    await wrapper.close()

    delegate.close.assert_not_called()


@pytest.mark.asyncio
async def test_no_close_messenger_client_delegates_send_text() -> None:
    """_NoCloseMessengerClient delegates send_text to the wrapped client."""
    from ugc_bot.worker import _NoCloseMessengerClient

    delegate = AsyncMock()
    wrapper = _NoCloseMessengerClient(delegate)
    await wrapper.send_text(chat_id="123", text="hello")

    delegate.send_text.assert_called_once_with(
        chat_id="123",
        text="hello",
        keyboard=None,
        parse_mode=None,
        disable_preview=None,
    )


@pytest.mark.asyncio
async def test_no_close_messenger_client_send_text_optional_kwargs() -> None:
    """_NoCloseMessengerClient forwards optional send_text kwargs."""
    from ugc_bot.worker import _NoCloseMessengerClient

    delegate = AsyncMock()
    keyboard = MagicMock()
    wrapper = _NoCloseMessengerClient(delegate)
    await wrapper.send_text(
        chat_id="123",
        text="hello",
        keyboard=keyboard,
        parse_mode="HTML",
        disable_preview=True,
    )

    delegate.send_text.assert_called_once_with(
        chat_id="123",
        text="hello",
        keyboard=keyboard,
        parse_mode="HTML",
        disable_preview=True,
    )


@pytest.mark.asyncio
async def test_no_close_messenger_client_delegates_send_photo() -> None:
    """_NoCloseMessengerClient delegates send_photo to the wrapped client."""
    from ugc_bot.worker import _NoCloseMessengerClient

    delegate = AsyncMock()
    wrapper = _NoCloseMessengerClient(delegate)
    await wrapper.send_photo(chat_id="123", file_id="file1", caption="cap")

    delegate.send_photo.assert_called_once_with(
        chat_id="123",
        file_id="file1",
        caption="cap",
        keyboard=None,
        parse_mode=None,
    )


@pytest.mark.asyncio
async def test_no_close_messenger_client_delegates_edit_text() -> None:
    """_NoCloseMessengerClient delegates edit_text to the wrapped client."""
    from ugc_bot.worker import _NoCloseMessengerClient

    delegate = AsyncMock()
    wrapper = _NoCloseMessengerClient(delegate)
    await wrapper.edit_text(
        chat_id="123", message_id="m1", text="new", keyboard=MagicMock()
    )

    delegate.edit_text.assert_called_once()


@pytest.mark.asyncio
async def test_no_close_messenger_client_delegates_edit_reply_markup() -> None:
    """_NoCloseMessengerClient delegates edit_reply_markup."""
    from ugc_bot.worker import _NoCloseMessengerClient

    delegate = AsyncMock()
    wrapper = _NoCloseMessengerClient(delegate)
    await wrapper.edit_reply_markup(
        chat_id="123", message_id="m1", keyboard=MagicMock()
    )

    delegate.edit_reply_markup.assert_called_once()


@pytest.mark.asyncio
async def test_no_close_messenger_client_delegates_answer_callback() -> None:
    """_NoCloseMessengerClient delegates answer_callback."""
    from ugc_bot.worker import _NoCloseMessengerClient

    delegate = AsyncMock()
    wrapper = _NoCloseMessengerClient(delegate)
    await wrapper.answer_callback(callback_id="cb1", text="ok", show_alert=True)

    delegate.answer_callback.assert_called_once_with(
        callback_id="cb1", text="ok", show_alert=True
    )


@pytest.mark.asyncio
async def test_no_close_messenger_client_delegates_send_invoice() -> None:
    """_NoCloseMessengerClient delegates send_invoice to the wrapped client."""
    from ugc_bot.worker import _NoCloseMessengerClient

    delegate = AsyncMock()
    invoice = MagicMock()
    wrapper = _NoCloseMessengerClient(delegate)
    await wrapper.send_invoice(chat_id="123", invoice=invoice)

    delegate.send_invoice.assert_called_once_with(
        chat_id="123", invoice=invoice
    )


@pytest.mark.asyncio
async def test_run_with_restart_restarts_on_exception() -> None:
    """_run_with_restart re-runs coro_factory after an exception."""
    from ugc_bot.worker import _run_with_restart

    call_count = 0

    gate = asyncio.Event()

    async def factory():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("transient error")
        gate.set()  # signal: second call (success) reached
        # Block until cancelled so the loop doesn't advance to a 3rd call
        await asyncio.sleep(float("inf"))

    async def run():
        await _run_with_restart("test", factory, restart_delay=0)

    task = asyncio.create_task(run())
    await gate.wait()  # wait until second call starts
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert call_count == 2


def _make_config(
    *,
    feedback_enabled: bool = True,
    role_reminder_enabled: bool = True,
    referral_reconciliation_enabled: bool = True,
    instagram_stats_update_enabled: bool = True,
    instagram_stats_collector_enabled: bool = True,
) -> AppConfig:
    """Build AppConfig via nested form to control scheduler enabled flags."""
    return AppConfig.model_validate(
        {
            "bot": BotConfig.model_validate({"BOT_TOKEN": "test"}),
            "log": LogConfig.model_validate({}),
            "db": DbConfig.model_validate(
                {"DATABASE_URL": "postgresql+psycopg://x:x@localhost:5432/x"}
            ),
            "admin": AdminConfig.model_validate({}),
            "kafka": KafkaConfig.model_validate({"KAFKA_ENABLED": False}),
            "feedback": FeedbackConfig.model_validate(
                {"FEEDBACK_ENABLED": feedback_enabled}
            ),
            "role_reminder": RoleReminderConfig.model_validate(
                {"ROLE_REMINDER_ENABLED": role_reminder_enabled}
            ),
            "redis": RedisConfig.model_validate({}),
            "instagram": InstagramConfig.model_validate(
                {
                    "INSTAGRAM_STATS_UPDATE_ENABLED": (
                        instagram_stats_update_enabled
                    ),
                    "INSTAGRAM_STATS_COLLECTOR_ENABLED": (
                        instagram_stats_collector_enabled
                    ),
                }
            ),
            "geocoder": GeocoderConfig.model_validate({}),
            "docs": DocsConfig.model_validate({}),
            "webhook": WebhookConfig.model_validate({}),
            "outbox": OutboxConfig.model_validate({}),
            "order": OrderConfig.model_validate({}),
            "market": MarketConfig.model_validate({}),
            "referral": ReferralConfig.model_validate(
                {
                    "REFERRAL_RECONCILIATION_ENABLED": (
                        referral_reconciliation_enabled
                    )
                }
            ),
        }
    )


def _make_mock_container():
    container = MagicMock()
    container.build_feedback_scheduler_deps.return_value = {
        "interaction_repo": MagicMock(),
        "interaction_service": MagicMock(),
        "user_role_service": MagicMock(),
        "profile_service": MagicMock(),
        "order_repo": MagicMock(),
        "transaction_manager": MagicMock(),
    }
    container.build_bot_texts_service.return_value = MagicMock()
    container.build_role_reminder_scheduler_deps.return_value = {
        "user_role_service": MagicMock(),
        "transaction_manager": MagicMock(),
    }
    container.build_referral_reconciliation_deps.return_value = {
        "referral_income_entry_repo": MagicMock(),
        "recorder": MagicMock(),
        "order_repo": MagicMock(),
        "transaction_manager": MagicMock(),
    }
    container.build_instagram_stats_scheduler_deps.return_value = {
        "instagram_stats_update_service": MagicMock(),
        "interval_seconds": 60,
    }
    container.build_instagram_stats_collector_scheduler_deps.return_value = {
        "instagram_stats_collector_service": MagicMock(),
        "interval_seconds": 120,
    }
    return container


@pytest.mark.asyncio
async def test_worker_runs_all_enabled_schedulers() -> None:
    """main_async launches all 5 schedulers when all are enabled."""
    from ugc_bot.worker import main_async

    config = _make_config()
    container = _make_mock_container()
    messenger = AsyncMock()
    launched = []

    async def fake_restart(name, coro_factory, restart_delay=5.0):
        launched.append(name)
        await (
            coro_factory()
        )  # invoke factory to verify it calls the right run_loop

    with (
        patch(
            "ugc_bot.feedback_scheduler.run_loop", new=AsyncMock()
        ) as mock_fb,
        patch(
            "ugc_bot.role_reminder_scheduler.run_loop", new=AsyncMock()
        ) as mock_rr,
        patch(
            "ugc_bot.referral_reconciliation_scheduler.run_loop",
            new=AsyncMock(),
        ) as mock_ref,
        patch(
            "ugc_bot.instagram_stats_scheduler.run_loop", new=AsyncMock()
        ) as mock_ig,
        patch(
            "ugc_bot.instagram_stats_collector_scheduler.run_loop",
            new=AsyncMock(),
        ) as mock_igc,
        patch("ugc_bot.worker._run_with_restart", new=fake_restart),
    ):
        await main_async(config, container, messenger)

    assert set(launched) == {
        "feedback",
        "role_reminder",
        "referral_reconciliation",
        "instagram_stats",
        "instagram_stats_collector",
    }
    mock_fb.assert_called_once()
    mock_rr.assert_called_once()
    mock_ref.assert_called_once()
    mock_ig.assert_called_once()
    mock_igc.assert_called_once()


@pytest.mark.asyncio
async def test_worker_skips_disabled_scheduler() -> None:
    """main_async does not launch a scheduler whose enabled flag is False."""
    from ugc_bot.worker import main_async

    config = _make_config(feedback_enabled=False)
    container = _make_mock_container()
    messenger = AsyncMock()
    launched = []

    async def fake_restart(name, coro_factory, restart_delay=5.0):
        launched.append(name)
        await coro_factory()

    with (
        patch(
            "ugc_bot.feedback_scheduler.run_loop", new=AsyncMock()
        ) as mock_fb,
        patch(
            "ugc_bot.role_reminder_scheduler.run_loop", new=AsyncMock()
        ) as mock_rr,
        patch(
            "ugc_bot.referral_reconciliation_scheduler.run_loop",
            new=AsyncMock(),
        ),
        patch("ugc_bot.instagram_stats_scheduler.run_loop", new=AsyncMock()),
        patch(
            "ugc_bot.instagram_stats_collector_scheduler.run_loop",
            new=AsyncMock(),
        ),
        patch("ugc_bot.worker._run_with_restart", new=fake_restart),
    ):
        await main_async(config, container, messenger)

    assert "feedback" not in launched
    assert len(launched) == 4
    mock_fb.assert_not_called()
    mock_rr.assert_called_once()


@pytest.mark.asyncio
async def test_worker_all_disabled_does_not_exit() -> None:
    """main_async calls asyncio.sleep(inf) when all schedulers are disabled."""
    from ugc_bot.worker import main_async

    config = _make_config(
        feedback_enabled=False,
        role_reminder_enabled=False,
        referral_reconciliation_enabled=False,
        instagram_stats_update_enabled=False,
        instagram_stats_collector_enabled=False,
    )
    container = _make_mock_container()
    messenger = AsyncMock()
    sleep_args = []

    async def fake_sleep(seconds):
        sleep_args.append(seconds)

    with patch("ugc_bot.worker.asyncio.sleep", new=fake_sleep):
        await main_async(config, container, messenger)

    assert float("inf") in sleep_args

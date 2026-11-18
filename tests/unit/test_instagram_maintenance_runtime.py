"""Opt-in delivery wiring does not launch another collection scheduler."""

from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ugc_bot import instagram_profile_notice_scheduler as scheduler
from ugc_bot.application.instagram_maintenance_ports import ProfileNotice
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    ReceiptCallback,
    ReceiptCard,
)
from ugc_bot.container.instagram_maintenance_factory import (
    build_profile_maintenance,
)
from ugc_bot.infrastructure.messenger.notice_receipts import (
    TelegramNoticeReceipts,
    _max_message_body,
)


def config(enabled=False, context="app:umc"):
    return NS(
        instagram=NS(
            instagram_profile_maintenance_enabled=enabled,
            instagram_identity_context=context,
        ),
        max_bot=None,
    )


def test_factory_requires_opt_in_transaction_and_namespace():
    assert build_profile_maintenance(None, {}, None) is None
    assert build_profile_maintenance(config(), {}, None) is None
    with pytest.raises(ValueError, match="database"):
        build_profile_maintenance(config(True), {}, None)
    with pytest.raises(ValueError, match="context"):
        build_profile_maintenance(
            config(True, ""), {"blogger_repo": object()}, object()
        )
    tx = object()
    maintenance = build_profile_maintenance(
        config(True), {"blogger_repo": object()}, tx
    )
    assert maintenance.transactions is tx
    assert maintenance.repo.context == "app:umc"


@pytest.mark.asyncio
@pytest.mark.parametrize("failing", [False, True])
async def test_notice_loop_only_drains_queue(monkeypatch, failing):
    worker = NS(
        run_once=AsyncMock(side_effect=RuntimeError if failing else None)
    )
    monkeypatch.setattr(
        scheduler, "InstagramProfileNoticeDelivery", Mock(return_value=worker)
    )
    container = NS(
        build_repos=lambda: {"blogger_repo": object()},
        transaction_manager=object(),
    )
    await scheduler.run_enabled(config(), container, object(), max_iterations=1)
    worker.run_once.assert_not_called()
    await scheduler.run_enabled(
        config(True), container, object(), max_iterations=1
    )
    worker.run_once.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [True, False])
async def test_repair_button_is_native_callback_in_both_messengers(valid):
    bot = NS(
        send_message=AsyncMock(return_value=NS(message_id=42, chat=NS(id=101)))
    )
    notice = ProfileNotice(
        uuid4(),
        uuid4(),
        "telegram",
        "101",
        "chat_id",
        "Проверьте Instagram\nОписание",
        ReceiptCard(
            callbacks=(
                ReceiptCallback(
                    "Обновить Instagram",
                    "instagram:refresh" if valid else "forged",
                ),
            )
        ),
    )
    if not valid:
        with pytest.raises(DeliveryFailure, match="callback_invalid"):
            await TelegramNoticeReceipts(bot).send(notice)
        bot.send_message.assert_not_called()
        return
    await TelegramNoticeReceipts(bot).send(notice)
    button = bot.send_message.call_args.kwargs["reply_markup"].inline_keyboard[
        0
    ][0]
    assert button.callback_data == "instagram:refresh" and button.url is None
    buttons = _max_message_body(notice)["attachments"][0]["payload"]["buttons"]
    assert buttons == [
        [
            {
                "type": "callback",
                "text": "Обновить Instagram",
                "payload": "instagram:refresh",
            }
        ]
    ]

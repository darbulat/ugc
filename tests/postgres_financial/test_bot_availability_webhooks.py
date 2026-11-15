"""Check that live webhook payloads produce deduplicated availability facts."""

import asyncio
from datetime import datetime, timedelta, timezone
from functools import partial
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from sqlalchemy import select
from sqlalchemy.orm import Session

from ugc_bot import max_webhook_app, telegram_webhook_app
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.db.models import AuditLogModel, UserModel
from ugc_bot.infrastructure.db.repositories.bot_availability import (
    BOT_AVAILABLE_EVENT,
    BOT_UNAVAILABLE_EVENT,
    creator_directory_status,
    record_telegram_send_block,
)
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)


@pytest.mark.asyncio
async def test_native_bot_blocks_are_recorded_once_on_both_webhooks(
    financial_pg_engine, monkeypatch
):
    ids = {
        platform: uuid4()
        for platform in (MessengerType.TELEGRAM, MessengerType.MAX)
    }
    active_at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(
        seconds=15
    )
    timestamp = int(active_at.timestamp())
    with Session(financial_pg_engine) as db, db.begin():
        db.add_all(
            [
                UserModel(
                    user_id=ids[MessengerType.TELEGRAM],
                    telegram_id="772233",
                    username="Synthetic",
                    status=UserStatus.ACTIVE,
                    messenger_type=MessengerType.TELEGRAM,
                ),
                UserModel(
                    user_id=ids[MessengerType.MAX],
                    max_id="992211",
                    username="Synthetic",
                    status=UserStatus.ACTIVE,
                    messenger_type=MessengerType.MAX,
                ),
            ]
        )
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "123456:synthetic",
            "WEBHOOK_SECRET": "synthetic_secret",
            "DATABASE_URL": financial_pg_engine.url.render_as_string(
                hide_password=False
            ),
            "KAFKA_ENABLED": False,
            "USE_REDIS_STORAGE": False,
        }
    )
    container = Container(config)
    telegram = telegram_webhook_app.app
    max_app = max_webhook_app.app
    dispatcher = Dispatcher()
    dispatcher["transaction_manager"] = container.transaction_manager
    bot = Bot(config.bot.bot_token)
    for key, value in {
        "bot": bot,
        "dispatcher": dispatcher,
        "config": config,
        "webhook_semaphore": asyncio.Semaphore(1),
    }.items():
        monkeypatch.setattr(telegram.state, key, value, raising=False)
    monkeypatch.setattr(
        max_app.state, "webhook_secret", "synthetic_secret", raising=False
    )
    monkeypatch.setattr(
        max_app.state,
        "bot_services",
        dict(dispatcher.workflow_data),
        raising=False,
    )
    telegram_bot = {"id": 123456, "is_bot": True, "first_name": "Bot"}
    telegram_payload = {
        "update_id": 123,
        "my_chat_member": {
            "chat": {"id": 772233, "type": "private"},
            "from": {"id": 772233, "is_bot": False, "first_name": "Synthetic"},
            "date": timestamp,
            "old_chat_member": {"status": "member", "user": telegram_bot},
            "new_chat_member": {
                "status": "kicked",
                "user": telegram_bot,
                "until_date": 0,
            },
        },
    }
    max_payload = {
        "update_type": "bot_stopped",
        "timestamp": timestamp * 1000,
        "user": {"user_id": 992211},
        "chat_id": 553344,
    }
    try:
        for module, app, name, header, payload in (
            (
                telegram_webhook_app,
                telegram,
                "telegram",
                "X-Telegram-Bot-Api-Secret-Token",
                telegram_payload,
            ),
            (
                max_webhook_app,
                max_app,
                "max",
                "X-Max-Bot-Api-Secret",
                max_payload,
            ),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers={header: "synthetic_secret"},
            ) as client:
                path = f"/webhook/{name}"
                if name == "max":
                    for invalid in (
                        {**payload, "user": {"user_id": "992211"}},
                        {**payload, "timestamp": 10**32},
                    ):
                        response = await client.post(path, json=invalid)
                        assert response.status_code == 400

                with monkeypatch.context() as failing:
                    recorder = AsyncMock(
                        side_effect=RuntimeError("Database unavailable")
                    )
                    failing.setattr(module, "record_bot_availability", recorder)
                    response = await client.post(path, json=payload)
                    assert response.status_code == 503
                    recorder.assert_awaited_once()

                for _ in range(2):
                    result = await client.post(path, json=payload)
                    assert result.status_code == 200
        with Session(financial_pg_engine) as db:
            rows = db.scalars(
                select(AuditLogModel).where(
                    AuditLogModel.entity_type == BOT_UNAVAILABLE_EVENT,
                    AuditLogModel.entity_id.in_(ids.values()),
                )
            ).all()
            assert len(rows) == 2
            assert {
                row.entity_id: row.new_values["platform"] for row in rows
            } == {
                identity: platform.value for platform, identity in ids.items()
            }
            assert all(row.changed_at == active_at for row in rows)
            assert (
                db.scalar(
                    select(creator_directory_status()).where(
                        UserModel.user_id == ids[MessengerType.MAX]
                    )
                )
                == UserStatus.ACTIVE
            )
        membership = telegram_payload["my_chat_member"]
        unblock_payload = {
            "update_id": 124,
            "my_chat_member": {
                **membership,
                "old_chat_member": membership["new_chat_member"],
                "new_chat_member": membership["old_chat_member"],
            },
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=telegram),
            base_url="http://test",
            headers={"X-Telegram-Bot-Api-Secret-Token": "synthetic_secret"},
        ) as client:
            with Session(financial_pg_engine) as db:
                status_query = select(creator_directory_status()).where(
                    UserModel.user_id == ids[MessengerType.TELEGRAM],
                )
                assert db.scalar(status_query) == UserStatus.BOT_BLOCKED
            for payload in (unblock_payload, telegram_payload, unblock_payload):
                response = await client.post("/webhook/telegram", json=payload)
                assert response.status_code == 200
            with Session(financial_pg_engine) as db:
                assert db.scalar(status_query) == UserStatus.ACTIVE
                assert (
                    len(
                        db.scalars(
                            select(AuditLogModel).where(
                                AuditLogModel.entity_type
                                == BOT_AVAILABLE_EVENT,
                                AuditLogModel.entity_id
                                == ids[MessengerType.TELEGRAM],
                            )
                        ).all()
                    )
                    == 1
                )
        monkeypatch.setattr(
            bot,
            "send_message",
            AsyncMock(
                side_effect=TelegramForbiddenError(
                    method=SendMessage(chat_id=772233, text="test"),
                    message="Forbidden: bot was blocked by the user",
                )
            ),
        )
        messenger = TelegramMessengerClient(
            bot,
            on_confirmed_block=partial(
                record_telegram_send_block, container.transaction_manager
            ),
        )
        with pytest.raises(TelegramForbiddenError):
            await messenger.send_text(chat_id="772233", text="test")
        with Session(financial_pg_engine) as db:
            assert db.scalar(status_query) == UserStatus.BOT_BLOCKED
            assert (
                db.get(UserModel, ids[MessengerType.TELEGRAM]).status
                == UserStatus.ACTIVE
            )
    finally:
        await bot.session.close()
        await container.dispose()

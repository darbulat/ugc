"""Check that live webhook payloads produce deduplicated availability facts."""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from aiogram import Bot, Dispatcher
from sqlalchemy import select
from sqlalchemy.orm import Session

from ugc_bot import max_webhook_app, telegram_webhook_app
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.db.models import AuditLogModel, UserModel
from ugc_bot.infrastructure.db.repositories.bot_availability import (
    BOT_UNAVAILABLE_EVENT,
)


@pytest.mark.asyncio
async def test_native_bot_blocks_are_recorded_once_on_both_webhooks(
    financial_pg_engine, monkeypatch
):
    ids = {
        platform: uuid4()
        for platform in (MessengerType.TELEGRAM, MessengerType.MAX)
    }
    active_at = datetime(2026, 11, 15, 16, 0, tzinfo=timezone.utc)
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
        for app, name, header, payload in (
            (
                telegram,
                "telegram",
                "X-Telegram-Bot-Api-Secret-Token",
                telegram_payload,
            ),
            (max_app, "max", "X-Max-Bot-Api-Secret", max_payload),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers={header: "synthetic_secret"},
            ) as client:
                for _ in range(2):
                    result = await client.post(f"/webhook/{name}", json=payload)
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
    finally:
        await bot.session.close()
        await container.dispose()

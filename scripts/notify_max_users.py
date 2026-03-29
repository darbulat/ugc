#!/usr/bin/env python3
"""Send notification to users who chose MAX in the messenger survey.

Targets nps_responses with comment='MAX' and score=0.

Usage:
    # Preview who would receive the message
    python -m scripts.notify_max_users --dry-run

    # Send to all matching users
    python -m scripts.notify_max_users
"""

import argparse
import asyncio
import logging
import sys

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import select

from ugc_bot.config import load_config
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.db.models import NpsResponseModel, UserModel
from ugc_bot.infrastructure.db.session import create_session_factory
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)

logger = logging.getLogger(__name__)

_SEND_RETRIES = 3
_SEND_RETRY_DELAY = 1.0
_INTER_MESSAGE_DELAY = 0.05  # ~20 msg/s, well under Telegram's 30/s limit

_MESSAGE_TEXT = """\
Вы выбрали MAX как удобный канал — мы подготовили для вас бота \
для уведомлений о новых заказах:

https://max.ru/id165919810643_bot

Для корректной привязки аккаунта при регистрации в MAX укажите тот же \
Instagram и пройдите повторную верификацию.
Все ранее заполненные данные автоматически перенесутся из Telegram."""

_EXCLUDED_STATUSES = {UserStatus.BLOCKED, UserStatus.DELETED}


async def _fetch_max_users(session_factory) -> list[str]:
    """Return external_ids of users who chose MAX (score=0, comment='MAX')."""
    async with session_factory() as session:
        stmt = (
            select(UserModel.external_id)
            .join(
                NpsResponseModel,
                NpsResponseModel.user_id == UserModel.user_id,
            )
            .where(
                NpsResponseModel.score == 0,
                NpsResponseModel.comment == "MAX",
                UserModel.messenger_type == MessengerType.TELEGRAM.value,
                UserModel.status.notin_([s.value for s in _EXCLUDED_STATUSES]),
            )
            .distinct()
        )
        result = await session.execute(stmt)
        return [row.external_id for row in result.all()]


async def _send_with_retry(
    client: TelegramMessengerClient,
    chat_id: str,
    text: str,
) -> bool:
    for attempt in range(1, _SEND_RETRIES + 1):
        try:
            await client.send_text(chat_id=chat_id, text=text)
            return True
        except (TelegramForbiddenError, TelegramBadRequest) as exc:
            logger.warning("Skipping %s (non-retryable): %s", chat_id, exc)
            return False
        except Exception as exc:
            if attempt == _SEND_RETRIES:
                logger.warning(
                    "Failed to send to %s after %d attempts: %s",
                    chat_id,
                    _SEND_RETRIES,
                    exc,
                )
                return False
            await asyncio.sleep(_SEND_RETRY_DELAY)
    return False


async def run(dry_run: bool) -> int:
    config = load_config()
    if not config.db.database_url:
        print("DATABASE_URL is required.", file=sys.stderr)
        return 1

    session_factory = create_session_factory(
        config.db.database_url,
        pool_size=config.db.pool_size,
        max_overflow=config.db.max_overflow,
        pool_timeout=config.db.pool_timeout,
    )

    users = await _fetch_max_users(session_factory)
    if not users:
        print("No users who chose MAX found.")
        return 0

    print(f"Found {len(users)} user(s) who chose MAX.")

    if dry_run:
        for external_id in users:
            print(f"  would send to: {external_id}")
        print("Run without --dry-run to send the notification.")
        return 0

    bot = Bot(token=config.bot.bot_token)
    client = TelegramMessengerClient(bot)
    sent = 0
    failed = 0

    try:
        for external_id in users:
            ok = await _send_with_retry(client, external_id, _MESSAGE_TEXT)
            if ok:
                sent += 1
            else:
                failed += 1
            await asyncio.sleep(_INTER_MESSAGE_DELAY)
    finally:
        session = getattr(bot, "session", None)
        if session is not None:
            await session.close()

    print(f"Done. Sent: {sent}, failed: {failed}.")
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send MAX bot notification to users who chose MAX.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list recipients, do not send messages.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())

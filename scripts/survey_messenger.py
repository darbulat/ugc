#!/usr/bin/env python3
"""One-shot broadcast: messenger-choice survey to all active Telegram users.

Usage:
    # Preview who would receive the survey
    python -m scripts.survey_messenger --dry-run

    # Send to all active Telegram users
    python -m scripts.survey_messenger
"""

import argparse
import asyncio
import logging
import sys

from aiogram import Bot
from sqlalchemy import select

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.bot.handlers.keyboards import (
    CALLBACK_SURVEY_MESSENGER_MAX,
    CALLBACK_SURVEY_MESSENGER_OTHER,
    CALLBACK_SURVEY_MESSENGER_TG,
)
from ugc_bot.config import load_config
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.session import create_session_factory
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)

logger = logging.getLogger(__name__)

_SEND_RETRIES = 3
_SEND_RETRY_DELAY = 1.0
_INTER_MESSAGE_DELAY = 0.05  # ~20 msg/s, well under Telegram's 30/s limit

_MESSAGE_TEXT = """\
Коллеги, привет! 👋

В связи с текущими ограничениями в Telegram рассматриваем альтернативные \
мессенджеры для рабочей коммуникации.

Подскажите, пожалуйста, где вам было бы удобнее продолжать взаимодействие:"""

_EXCLUDED_STATUSES = {UserStatus.BLOCKED, UserStatus.DELETED}


def _survey_keyboard() -> Keyboard:
    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text="остаёмся в Telegram",
                    callback_data=CALLBACK_SURVEY_MESSENGER_TG,
                )
            ],
            [
                Button(
                    text="переходим в MAX",
                    callback_data=CALLBACK_SURVEY_MESSENGER_MAX,
                )
            ],
            [
                Button(
                    text="другой вариант",
                    callback_data=CALLBACK_SURVEY_MESSENGER_OTHER,
                )
            ],
        ],
    )


async def _fetch_users(session_factory) -> list[str]:
    """Return external_ids of all active Telegram users."""
    async with session_factory() as session:
        stmt = select(UserModel.external_id).where(
            UserModel.messenger_type == MessengerType.TELEGRAM.value,
            UserModel.status.notin_([s.value for s in _EXCLUDED_STATUSES]),
        )
        result = await session.execute(stmt)
        return [row.external_id for row in result.all()]


async def _send_with_retry(
    client: TelegramMessengerClient,
    chat_id: str,
    text: str,
    keyboard: Keyboard,
) -> bool:
    for attempt in range(1, _SEND_RETRIES + 1):
        try:
            await client.send_text(
                chat_id=chat_id, text=text, keyboard=keyboard
            )
            return True
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

    users = await _fetch_users(session_factory)
    if not users:
        print("No eligible users found.")
        return 0

    print(f"Found {len(users)} eligible user(s).")

    if dry_run:
        for external_id in users:
            print(f"  would send to: {external_id}")
        print("Run without --dry-run to send the survey.")
        return 0

    bot = Bot(token=config.bot.bot_token)
    client = TelegramMessengerClient(bot)
    keyboard = _survey_keyboard()
    sent = 0
    failed = 0

    try:
        for external_id in users:
            ok = await _send_with_retry(
                client, external_id, _MESSAGE_TEXT, keyboard
            )
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
        description="Broadcast messenger-choice survey to Telegram users.",
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

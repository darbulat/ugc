#!/usr/bin/env python3
"""One-shot script: send a gentle reminder to creators who haven't confirmed Instagram.

Usage:
    # Preview which creators would receive a reminder
    python -m scripts.remind_unconfirmed_instagram --dry-run

    # Actually send reminders
    python -m scripts.remind_unconfirmed_instagram
"""

import argparse
import asyncio
import logging
import sys

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.bot.handlers.keyboards import (
    CALLBACK_PROFILE_CONFIRM_INSTAGRAM,
)
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
from ugc_bot.config import load_config
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.db.models import BloggerProfileModel, UserModel
from ugc_bot.infrastructure.db.session import create_session_factory
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)
from ugc_bot.infrastructure.messenger.types import Button, Keyboard, KeyboardKind

logger = logging.getLogger(__name__)

_SEND_RETRIES = 3
_SEND_RETRY_DELAY = 0.5


def _reminder_keyboard(locale: str) -> Keyboard:
    """Single inline button: confirm Instagram."""
    texts = DEFAULT_TEXTS.get(locale) or DEFAULT_TEXTS["ru"]
    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=texts.get("btn_confirm_instagram", "Подтвердить Instagram"),
                    callback_data=CALLBACK_PROFILE_CONFIRM_INSTAGRAM,
                )
            ]
        ],
    )


def _reminder_text(locale: str) -> str:
    texts = DEFAULT_TEXTS.get(locale) or DEFAULT_TEXTS["ru"]
    return texts.get(
        "msg_instagram_confirm_reminder",
        (
            "Напоминаем, что для получения заказов необходимо "
            "подтвердить ваш Instagram-аккаунт."
        ),
    )


async def _fetch_unconfirmed_creators(
    session: AsyncSession,
) -> list[tuple[str, str | None]]:
    """Return list of (external_id, language) for creators with unconfirmed Instagram."""
    stmt = (
        select(UserModel.external_id, UserModel.language)
        .join(
            BloggerProfileModel,
            BloggerProfileModel.user_id == UserModel.user_id,
        )
        .where(
            BloggerProfileModel.confirmed.is_(False),
            UserModel.messenger_type == MessengerType.TELEGRAM.value,
        )
    )
    result = await session.execute(stmt)
    return [(row.external_id, row.language) for row in result.all()]


async def _send_with_retry(
    client: TelegramMessengerClient,
    chat_id: str,
    text: str,
    keyboard: Keyboard,
) -> bool:
    for attempt in range(1, _SEND_RETRIES + 1):
        try:
            await client.send_text(
                chat_id=chat_id, text=text, keyboard=keyboard,
            )
            return True
        except Exception as exc:
            if attempt == _SEND_RETRIES:
                logger.warning(
                    "Failed to send reminder to %s after %d attempts: %s",
                    chat_id, _SEND_RETRIES, exc,
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

    async with session_factory() as session:
        creators = await _fetch_unconfirmed_creators(session)

    if not creators:
        print("No unconfirmed creators found.")
        return 0

    print(f"Found {len(creators)} unconfirmed creator(s).")

    if dry_run:
        for external_id, lang in creators:
            print(f"  would remind: external_id={external_id}, language={lang}")
        print("Run without --dry-run to send reminders.")
        return 0

    bot = Bot(token=config.bot.bot_token)
    client = TelegramMessengerClient(bot)
    sent = 0
    failed = 0

    try:
        for external_id, lang in creators:
            locale = lang or "ru"
            text = _reminder_text(locale)
            keyboard = _reminder_keyboard(locale)
            ok = await _send_with_retry(client, external_id, text, keyboard)
            if ok:
                sent += 1
            else:
                failed += 1
    finally:
        session = getattr(bot, "session", None)
        if session is not None:
            await session.close()

    print(f"Done. Sent: {sent}, failed: {failed}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send Instagram confirmation reminder to unconfirmed creators.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list creators, do not send messages.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())

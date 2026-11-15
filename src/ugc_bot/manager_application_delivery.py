"""Deliver manager application events from the existing transactional outbox."""

from uuid import UUID

from aiogram import Bot
from sqlalchemy import func, select

from ugc_bot.bot.telegram.manager_review_messages import (
    manager_welcome,
    review_message,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import OutboxEvent
from ugc_bot.domain.manager_application import (
    MANAGER_REVIEWERS,
    MANAGER_SUBMITTED,
    application_version,
)
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.repositories.manager_applications import (
    manager_application_query,
)
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)


class ManagerApplicationDelivery:
    def __init__(self, config: AppConfig):
        self.config = config

    async def __call__(self, event: OutboxEvent, session: object) -> None:
        db = _session(session)
        candidate = (
            (
                await db.execute(
                    manager_application_query(UUID(event.aggregate_id))
                )
            )
            .mappings()
            .one_or_none()
        )
        if candidate is None:
            return
        if event.event_type == MANAGER_SUBMITTED:
            if event.payload["submission"] != application_version(
                candidate["submitted_at"]
            ):
                return
            recipient = event.payload["reviewer"]
            if recipient not in MANAGER_REVIEWERS:
                raise ValueError("manager_reviewer_not_configured")
            addresses = (
                await db.scalars(
                    select(UserModel.telegram_id)
                    .where(
                        func.lower(UserModel.telegram) == recipient,
                        UserModel.admin.is_(True),
                        UserModel.status == "active",
                        UserModel.telegram_id.is_not(None),
                    )
                    .limit(2)
                )
            ).all()
            if len(addresses) != 1:
                raise ValueError("manager_reviewer_telegram_unavailable")
            chat_id = addresses[0]
            text, markup = review_message(self.config, candidate)
        else:
            if candidate["state"] != "approved":
                return
            chat_id = candidate["telegram_id"]
            text, markup = manager_welcome(
                self.config, candidate["decision_note"]
            )
        if not chat_id:
            raise ValueError("manager_telegram_recipient_unavailable")
        try:
            async with Bot(token=self.config.bot.bot_token).context() as bot:
                await TelegramMessengerClient(bot, retry_attempts=1).send_text(
                    chat_id=chat_id,
                    text=text,
                    keyboard=markup,
                    parse_mode="HTML",
                    disable_preview=True,
                )
        except Exception as exc:
            raise RuntimeError(
                f"manager_telegram_delivery_{type(exc).__name__}"
            ) from exc

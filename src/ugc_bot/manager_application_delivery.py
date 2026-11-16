"""Deliver manager application events from the existing transactional outbox."""

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from aiogram import Bot
from sqlalchemy import func, select

from ugc_bot.application.ports import TransactionManager
from ugc_bot.bot.telegram.manager_review_messages import (
    instagram_verified_message,
    manager_welcome,
    review_message,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import OutboxEvent
from ugc_bot.domain.enums import OutboxEventStatus
from ugc_bot.domain.manager_application import (
    MANAGER_APPROVED,
    MANAGER_INSTAGRAM_VERIFIED,
    MANAGER_NOTIFICATION_RECIPIENTS,
    MANAGER_READY_FOR_REVIEW,
    MANAGER_READY_FOR_REVIEW_V2,
    MANAGER_REVIEWABLE_STATES,
    MANAGER_SUBMITTED,
    application_version,
)
from ugc_bot.infrastructure.db.models import OutboxEventModel, UserModel
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.repositories.manager_applications import (
    manager_application_query,
)
from ugc_bot.infrastructure.db.repositories.outbox import (
    _to_outbox_event_entity,
)
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)

logger = logging.getLogger(__name__)


class ManagerApplicationDelivery:
    def __init__(self, config: AppConfig):
        self.config = config

    async def deliver_verification_notices(
        self, transactions: TransactionManager, event_ids: list[UUID]
    ) -> None:
        """Try sending after commit; the normal worker handles pending rows."""

        async def send_one(event_id: UUID) -> None:
            try:
                async with transactions.transaction() as session:
                    db = _session(session)
                    row = await db.scalar(
                        select(OutboxEventModel)
                        .where(
                            OutboxEventModel.event_id == event_id,
                            OutboxEventModel.status
                            == OutboxEventStatus.PENDING,
                            OutboxEventModel.event_type.in_(
                                (
                                    MANAGER_INSTAGRAM_VERIFIED,
                                    MANAGER_READY_FOR_REVIEW,
                                    MANAGER_READY_FOR_REVIEW_V2,
                                )
                            ),
                        )
                        .with_for_update(skip_locked=True)
                    )
                    if row is None:
                        return
                    # The worker skips this row while it is locked.
                    async with asyncio.timeout(3):
                        await self(_to_outbox_event_entity(row), session)
                    row.status = OutboxEventStatus.PUBLISHED
                    row.processed_at = datetime.now(timezone.utc)
            except Exception as exc:
                logger.warning(
                    "Manager verification notice will retry in worker (%s)",
                    type(exc).__name__,
                )

        await asyncio.gather(*(send_one(event_id) for event_id in event_ids))

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
        notice = await self._notice(db, event, candidate)
        if notice is None:
            return
        chat_id, (text, markup) = notice
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

    async def _notice(self, db, event, candidate):
        if event.event_type in {
            MANAGER_SUBMITTED,
            MANAGER_READY_FOR_REVIEW,
            MANAGER_READY_FOR_REVIEW_V2,
        }:
            if event.payload["submission"] != application_version(
                candidate["submitted_at"]
            ):
                return None
            ready = event.event_type != MANAGER_SUBMITTED
            if ready and (
                not candidate["instagram_verified_at"]
                or candidate["state"] not in MANAGER_REVIEWABLE_STATES
            ):
                return None
            # Keep the original recipient for legacy queued notices.
            reviewer = (
                "kamilbakhteev"
                if event.event_type == MANAGER_READY_FOR_REVIEW
                else event.payload["reviewer"]
            )
            chat_id = await self._reviewer_address(db, reviewer)
            message = review_message(self.config, candidate, ready=ready)
        elif event.event_type == MANAGER_INSTAGRAM_VERIFIED:
            if not candidate["instagram_verified_at"] or event.payload[
                "verification"
            ] != application_version(candidate["instagram_verified_at"]):
                return None
            chat_id = candidate["telegram_id"]
            message = instagram_verified_message(
                candidate["state"], self.config
            )
        elif event.event_type == MANAGER_APPROVED:
            if candidate["state"] != "approved":
                return None
            chat_id = candidate["telegram_id"]
            message = manager_welcome(self.config)
        else:
            raise ValueError("manager_telegram_event_unsupported")
        return chat_id, message

    @staticmethod
    async def _reviewer_address(db, recipient):
        if recipient not in MANAGER_NOTIFICATION_RECIPIENTS:
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
        return addresses[0]

"""Deliver manager application events from the existing transactional outbox."""

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramUnauthorizedError,
)
from sqlalchemy import select

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
    MANAGER_NOTICE_EVENTS,
    MANAGER_NOTIFICATION_RECIPIENTS,
    MANAGER_READY_FOR_REVIEW,
    MANAGER_READY_FOR_REVIEW_V2,
    MANAGER_REVIEWABLE_STATES,
    MANAGER_SUBMITTED,
    MANAGER_TELEGRAM_RESULT_UNKNOWN,
    application_version,
)
from ugc_bot.infrastructure.db.models import OutboxEventModel
from ugc_bot.infrastructure.db.repositories.admin_recipients import (
    active_admin_telegram_address,
)
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

_VERIFICATION_NOTICES = (
    MANAGER_INSTAGRAM_VERIFIED,
    MANAGER_READY_FOR_REVIEW,
    MANAGER_READY_FOR_REVIEW_V2,
)


class ManagerApplicationDelivery:
    def __init__(self, config: AppConfig):
        self.config = config

    async def deliver_verification_notices(
        self, transactions: TransactionManager, event_ids: list[UUID]
    ) -> None:
        """Try sending after commit; the normal worker handles pending rows."""

        async def send_one(event_id: UUID) -> None:
            try:
                await self._deliver(
                    event_id, transactions, max_retries=None, send_timeout=3
                )
            except Exception as exc:
                logger.warning(
                    "Manager verification notice interrupted (%s)",
                    type(exc).__name__,
                )

        await asyncio.gather(*(send_one(event_id) for event_id in event_ids))

    async def __call__(
        self,
        event_id: UUID,
        transactions: TransactionManager,
        max_retries: int,
    ) -> None:
        await self._deliver(event_id, transactions, max_retries=max_retries)

    async def _deliver(
        self,
        event_id: UUID,
        transactions: TransactionManager,
        *,
        max_retries: int | None,
        send_timeout: float | None = None,
    ) -> None:
        async with Bot(token=self.config.bot.bot_token).context() as bot:
            attempt = await self._begin(event_id, transactions, max_retries)
            if attempt is None:
                return
            started_at, (chat_id, (text, markup)) = attempt
            error = None
            try:
                async with asyncio.timeout(send_timeout):
                    await TelegramMessengerClient(
                        bot, retry_attempts=1
                    ).send_text(
                        chat_id=chat_id,
                        text=text,
                        keyboard=markup,
                        parse_mode="HTML",
                        disable_preview=True,
                    )
            except (
                TelegramBadRequest,
                TelegramForbiddenError,
                TelegramNotFound,
                TelegramRetryAfter,
                TelegramUnauthorizedError,
            ) as exc:
                error = f"manager_telegram_delivery_{type(exc).__name__}"
            except Exception as exc:
                logger.warning(
                    "Manager Telegram result is unknown (%s)",
                    type(exc).__name__,
                )
                return
        await self._finish(
            event_id, transactions, started_at, error, max_retries
        )

    async def _begin(
        self,
        event_id: UUID,
        transactions: TransactionManager,
        max_retries: int | None,
    ):
        status, event_types = (
            (OutboxEventStatus.PENDING, _VERIFICATION_NOTICES)
            if max_retries is None
            else (OutboxEventStatus.PROCESSING, MANAGER_NOTICE_EVENTS)
        )
        async with transactions.transaction() as session:
            db = _session(session)
            row = await db.scalar(
                select(OutboxEventModel)
                .where(
                    OutboxEventModel.event_id == event_id,
                    OutboxEventModel.status == status,
                    OutboxEventModel.event_type.in_(event_types),
                )
                .with_for_update(skip_locked=True)
            )
            if row is None:
                return None
            if max_retries is not None and row.retry_count >= max_retries:
                row.status = OutboxEventStatus.FAILED
                row.last_error = f"Max retries ({max_retries}) exceeded"
                return None
            try:
                notice = await self._prepare(db, _to_outbox_event_entity(row))
            except ValueError as exc:
                self._record_rejection(row, str(exc), max_retries)
                return None
            if notice is None:
                self._publish(row)
                return None
            # Commit an unknown outcome before I/O. Even older workers skip
            # terminal events, so a crash cannot requeue this attempt.
            started_at = datetime.now(timezone.utc)
            row.claimed_at = started_at
            row.status = OutboxEventStatus.FAILED
            row.last_error = MANAGER_TELEGRAM_RESULT_UNKNOWN
            return started_at, notice

    async def _finish(
        self,
        event_id: UUID,
        transactions: TransactionManager,
        started_at: datetime,
        error: str | None,
        max_retries: int | None,
    ) -> None:
        async with transactions.transaction() as session:
            db = _session(session)
            row = await db.scalar(
                select(OutboxEventModel)
                .where(
                    OutboxEventModel.event_id == event_id,
                    OutboxEventModel.status == OutboxEventStatus.FAILED,
                    OutboxEventModel.claimed_at == started_at,
                    OutboxEventModel.last_error
                    == MANAGER_TELEGRAM_RESULT_UNKNOWN,
                )
                .with_for_update()
            )
            if row is None:
                return
            if error is None:
                self._publish(row)
            else:
                self._record_rejection(row, error, max_retries)

    @staticmethod
    def _publish(row: OutboxEventModel) -> None:
        row.status = OutboxEventStatus.PUBLISHED
        row.processed_at = datetime.now(timezone.utc)
        row.last_error = None

    @staticmethod
    def _record_rejection(
        row: OutboxEventModel, error: str, max_retries: int | None
    ) -> None:
        if max_retries is not None:
            row.retry_count += 1
        row.status = (
            OutboxEventStatus.FAILED
            if max_retries is not None and row.retry_count >= max_retries
            else OutboxEventStatus.PENDING
        )
        row.last_error = error

    async def _prepare(self, db, event: OutboxEvent):
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
            return None
        notice = await self._notice(db, event, candidate)
        if notice is None:
            return None
        chat_id, message = notice
        try:
            address = str(int(chat_id))
        except (TypeError, ValueError) as exc:
            raise ValueError("manager_telegram_recipient_unavailable") from exc
        return address, message

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
        address = await active_admin_telegram_address(db, recipient)
        if address is None:
            raise ValueError("manager_reviewer_telegram_unavailable")
        return address

"""SQLAlchemy outbox repository."""

from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional
from uuid import UUID

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.application.ports import OutboxRepository
from ugc_bot.domain.entities import OutboxEvent
from ugc_bot.domain.enums import OutboxEventStatus
from ugc_bot.infrastructure.db.models import OutboxEventModel
from ugc_bot.infrastructure.db.repositories._shared import _resolve_session


class SqlAlchemyOutboxRepository(OutboxRepository):
    """SQLAlchemy implementation of outbox repository."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self.session_factory = session_factory

    async def save(
        self, event: OutboxEvent, session: object | None = None
    ) -> None:
        """Persist outbox event."""
        model = _to_outbox_event_model(event)
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            db_session.add(model)

    async def get_pending_events(
        self, limit: int = 100, session: object | None = None
    ) -> List[OutboxEvent]:
        """Get pending events for processing."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            result = await db_session.execute(
                select(OutboxEventModel)
                .where(
                    OutboxEventModel.status == OutboxEventStatus.PENDING,
                    OutboxEventModel.event_type.not_like("financial.%"),
                )
                .order_by(OutboxEventModel.created_at)
                .limit(limit)
            )
            models = result.scalars().all()
            return [_to_outbox_event_entity(model) for model in models]

    async def claim_pending_events(
        self, limit: int = 100, session: object | None = None
    ) -> List[OutboxEvent]:
        """Claim pending events (set to PROCESSING) and return them."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            result = await db_session.execute(
                select(OutboxEventModel)
                .where(
                    OutboxEventModel.status == OutboxEventStatus.PENDING,
                    OutboxEventModel.event_type.not_like("financial.%"),
                )
                .order_by(OutboxEventModel.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            models = result.scalars().all()
            if models:
                event_ids = [m.event_id for m in models]
                await db_session.execute(
                    update(OutboxEventModel)
                    .where(OutboxEventModel.event_id.in_(event_ids))
                    .values(
                        status=OutboxEventStatus.PROCESSING,
                        claimed_at=datetime.now(timezone.utc),
                    )
                )
            return [_to_outbox_event_entity(model) for model in models]

    async def mark_as_processing(
        self, event_id: UUID, session: object | None = None
    ) -> None:
        """Mark event as processing."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            await db_session.execute(
                update(OutboxEventModel)
                .where(OutboxEventModel.event_id == event_id)
                .values(status=OutboxEventStatus.PROCESSING)
            )

    async def mark_as_published(
        self,
        event_id: UUID,
        processed_at: datetime,
        session: object | None = None,
    ) -> None:
        """Mark event as published."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            await db_session.execute(
                update(OutboxEventModel)
                .where(OutboxEventModel.event_id == event_id)
                .values(
                    status=OutboxEventStatus.PUBLISHED,
                    processed_at=processed_at,
                )
            )

    async def mark_as_failed(
        self,
        event_id: UUID,
        error: str,
        retry_count: int,
        session: object | None = None,
    ) -> None:
        """Mark event as failed (terminal state)."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            await db_session.execute(
                update(OutboxEventModel)
                .where(OutboxEventModel.event_id == event_id)
                .values(
                    status=OutboxEventStatus.FAILED,
                    last_error=error,
                    retry_count=retry_count,
                )
            )

    async def mark_for_retry(
        self,
        event_id: UUID,
        error: str,
        retry_count: int,
        session: object | None = None,
    ) -> None:
        """Reset event to PENDING for retry."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            await db_session.execute(
                update(OutboxEventModel)
                .where(OutboxEventModel.event_id == event_id)
                .values(
                    status=OutboxEventStatus.PENDING,
                    last_error=error,
                    retry_count=retry_count,
                )
            )

    async def get_by_id(
        self, event_id: UUID, session: object | None = None
    ) -> Optional[OutboxEvent]:
        """Get event by ID."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(OutboxEventModel).where(
                    OutboxEventModel.event_id == event_id
                )
            )
            model = exec_result.scalar_one_or_none()
            return _to_outbox_event_entity(model) if model else None

    async def delete_processed_events(
        self,
        retention_days: int,
        batch_size: int,
        session: object | None = None,
    ) -> int:
        """Delete PUBLISHED/FAILED events older than retention_days."""
        if retention_days <= 0:
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            subq = (
                select(OutboxEventModel.event_id)
                .where(
                    # These records are also immutable capture/intent identity;
                    # delivery retention must not erase financial idempotency.
                    OutboxEventModel.event_type.not_like("financial.%"),
                    or_(
                        and_(
                            OutboxEventModel.status
                            == OutboxEventStatus.PUBLISHED,
                            OutboxEventModel.processed_at < cutoff,
                        ),
                        and_(
                            OutboxEventModel.status == OutboxEventStatus.FAILED,
                            OutboxEventModel.created_at < cutoff,
                        ),
                    ),
                )
                .limit(batch_size)
            )

            result = await db_session.execute(
                delete(OutboxEventModel).where(
                    OutboxEventModel.event_id.in_(subq)
                )
            )
            return getattr(result, "rowcount", None) or 0

    async def reset_stale_processing_events(
        self,
        stale_after_minutes: int = 15,
        session: object | None = None,
    ) -> int:
        """Reset stale PROCESSING events back to PENDING."""
        cutoff = datetime.now(timezone.utc) - timedelta(
            minutes=stale_after_minutes
        )
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            result = await db_session.execute(
                update(OutboxEventModel)
                .where(
                    OutboxEventModel.status == OutboxEventStatus.PROCESSING,
                    OutboxEventModel.event_type.not_like("financial.%"),
                    OutboxEventModel.claimed_at < cutoff,
                )
                .values(status=OutboxEventStatus.PENDING)
            )
            return getattr(result, "rowcount", None) or 0


class SqlAlchemyFinancialDeliveryRepository(SqlAlchemyOutboxRepository):
    """Separate delivery owner; invoice control is never work."""

    async def reset_stale_processing_events(
        self, stale_after_minutes: int = 15, session: object | None = None
    ) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(
            minutes=stale_after_minutes
        )
        async with _resolve_session(self.session_factory, session) as db:
            result = await db.execute(
                update(OutboxEventModel)
                .where(
                    OutboxEventModel.status == OutboxEventStatus.PROCESSING,
                    OutboxEventModel.event_type.like("financial.%"),
                    OutboxEventModel.event_type != "financial.capture_intent",
                    OutboxEventModel.claimed_at < cutoff,
                )
                .values(status=OutboxEventStatus.PENDING)
            )
            return getattr(result, "rowcount", None) or 0

    async def delete_processed_events(
        self,
        retention_days: int,
        batch_size: int,
        session: object | None = None,
    ) -> int:
        """Financial rows are durable identity, not disposable delivery logs."""
        return 0

    async def get_pending_events(
        self, limit: int = 100, session: object | None = None
    ) -> List[OutboxEvent]:
        async with _resolve_session(self.session_factory, session) as db:
            rows = await db.scalars(
                select(OutboxEventModel)
                .where(
                    OutboxEventModel.status == OutboxEventStatus.PENDING,
                    OutboxEventModel.event_type.like("financial.%"),
                    OutboxEventModel.event_type != "financial.capture_intent",
                )
                .order_by(OutboxEventModel.created_at)
                .limit(limit)
            )
            return [_to_outbox_event_entity(row) for row in rows]

    async def claim_pending_events(
        self, limit: int = 100, session: object | None = None
    ) -> List[OutboxEvent]:
        async with _resolve_session(self.session_factory, session) as db:
            rows = list(
                await db.scalars(
                    select(OutboxEventModel)
                    .where(
                        OutboxEventModel.status == OutboxEventStatus.PENDING,
                        OutboxEventModel.event_type.like("financial.%"),
                        OutboxEventModel.event_type
                        != "financial.capture_intent",
                    )
                    .order_by(OutboxEventModel.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            events = [_to_outbox_event_entity(row) for row in rows]
            for row in rows:
                row.status = OutboxEventStatus.PROCESSING
                row.claimed_at = datetime.now(timezone.utc)
            return events


def _to_outbox_event_entity(model: OutboxEventModel) -> OutboxEvent:
    """Map outbox event ORM model to entity."""
    return OutboxEvent(
        event_id=model.event_id,
        event_type=model.event_type,
        aggregate_id=model.aggregate_id,
        aggregate_type=model.aggregate_type,
        payload=model.payload,
        status=model.status,
        created_at=model.created_at,
        processed_at=model.processed_at,
        retry_count=model.retry_count,
        last_error=model.last_error,
    )


def _to_outbox_event_model(event: OutboxEvent) -> OutboxEventModel:
    """Map domain outbox event to ORM model."""
    return OutboxEventModel(
        event_id=event.event_id,
        event_type=event.event_type,
        aggregate_id=event.aggregate_id,
        aggregate_type=event.aggregate_type,
        payload=event.payload,
        status=event.status,
        created_at=event.created_at,
        processed_at=event.processed_at,
        retry_count=event.retry_count,
        last_error=event.last_error,
    )

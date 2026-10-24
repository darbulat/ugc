"""Wait for specified financial facts through the actual bounded worker."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ugc_bot.application.financial_delivery_ownership import (
    SEPARATE_DELIVERY_EVENT_TYPES,
)
from ugc_bot.domain.enums import OutboxEventStatus
from ugc_bot.infrastructure.db.models import OutboxEventModel


def _snapshot(engine, targets):
    with Session(engine) as db:
        rows = db.execute(
            select(
                OutboxEventModel.event_id,
                OutboxEventModel.status,
                OutboxEventModel.retry_count,
                OutboxEventModel.last_error,
            ).where(
                OutboxEventModel.event_type.like("financial.%"),
                OutboxEventModel.event_type.not_in(
                    SEPARATE_DELIVERY_EVENT_TYPES
                ),
            )
        ).all()
    own = {row.event_id: row for row in rows if row.event_id in targets}
    assert set(own) == targets, "financial_worker_target_missing_or_unowned"
    for row in own.values():
        assert row.last_error is None and row.retry_count == 0, (
            "financial_worker_target_error: "
            f"{row.event_id} status={row.status} "
            f"retries={row.retry_count} error={row.last_error}"
        )
        assert row.status != OutboxEventStatus.FAILED, (
            f"financial_worker_target_failed: {row.event_id}"
        )
    active = frozenset(
        (row.event_id, row.status, row.retry_count)
        for row in rows
        if row.status
        in (OutboxEventStatus.PENDING, OutboxEventStatus.PROCESSING)
    )
    return own, active


async def process_until_published(
    worker, engine, event_ids: Iterable[UUID]
) -> None:
    """Drain earlier shared fixtures without retrying a broken target.

    The module-scoped PG schema keeps immutable facts from prior test cases.
    One production pass claims a bounded global batch, not a test's event.
    The finite budget allows every initially active event its normal retry
    allowance; unchanged progress and any target error fail immediately.
    """
    targets = set(event_ids)
    assert targets, "financial_worker_targets_empty"
    own, active = _snapshot(engine, targets)
    budget = max(1, len(active) * max(1, worker.max_retries) + 1)
    for _ in range(budget):
        if all(
            row.status == OutboxEventStatus.PUBLISHED for row in own.values()
        ):
            return
        previous = active
        await worker.process_once()
        own, active = _snapshot(engine, targets)
        assert active != previous, "financial_worker_no_progress"
    raise AssertionError("financial_worker_target_budget_exhausted")

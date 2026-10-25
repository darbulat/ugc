"""Captured authority, current identities and immutable grant receipts."""

from dataclasses import fields

from sqlalchemy import insert, select, text

from ugc_bot.application.manual_grant_ports import ManualGrantSource
from ugc_bot.infrastructure.db.manual_grant_models import TABLES
from ugc_bot.infrastructure.db.models import OutboxEventModel
from ugc_bot.infrastructure.db.repositories.corrections import (
    SqlAlchemyCorrectionRepository,
)
from ugc_bot.infrastructure.db.repositories.entitlements import _require, _row
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.repositories.outbox import (
    _to_outbox_event_entity,
)
from ugc_bot.infrastructure.db.repositories.selection_delivery_funding import (
    SqlAlchemySelectionFundingRepository,
)
from ugc_bot.infrastructure.db.repositories.work_entitlements import (
    SqlAlchemyWorkEntitlementRepository,
)


class SqlAlchemyManualGrantRepository:
    async def load_capture(self, item_id, *, session):
        db = _session(session)
        item = await _row(db, "order_items", "paid_item_id", item_id)
        event = (
            await db.scalars(
                select(OutboxEventModel).where(
                    OutboxEventModel.aggregate_type == "order",
                    OutboxEventModel.aggregate_id == str(item["order_id"]),
                    OutboxEventModel.event_type
                    == "financial.client_snapshot_requested",
                )
            )
        ).one_or_none()
        _require(event is not None, "manual_grant_capture_required")
        capture = await SqlAlchemySelectionFundingRepository().load_capture(
            _to_outbox_event_entity(event), session=db
        )
        _require(
            any(i.paid_item_id == item_id for i in capture.items),
            "manual_grant_capture_required",
        )
        return capture

    async def lock_funding(self, capture, *, session):
        await SqlAlchemySelectionFundingRepository().lock_funding(
            capture, session=session
        )

    async def actor(self, identity, *, session):
        return await SqlAlchemyCorrectionRepository().actor(
            identity, session=session
        )

    async def require_work_clear(self, item_id, *, session):
        if (
            await SqlAlchemyWorkEntitlementRepository().get_dispute_case(
                item_id, session=session
            )
            is not None
        ):
            raise ValueError("work_disputed")

    async def source(self, identity, *, session):
        row = (
            (
                await _session(session).execute(
                    select(TABLES["grants"]).where(
                        TABLES["grants"].c.grant_id == identity
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return (
            ManualGrantSource(
                **{f.name: row[f.name] for f in fields(ManualGrantSource)}
            )
            if row
            else None
        )

    async def append_grant(self, fact, *, session):
        await _session(session).execute(insert(TABLES["grants"]).values(**fact))

    async def command(self, actor_id, key, *, session):
        table = TABLES["commands"]
        return (
            (
                await _session(session).execute(
                    select(table).where(
                        table.c.actor_id == actor_id,
                        table.c.operation_key == key,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )

    async def save_command(
        self, actor_id, key, digest, result, now, *, session
    ):
        await _session(session).execute(
            insert(TABLES["commands"]).values(
                actor_id=actor_id,
                operation_key=key,
                payload_hash=digest,
                result=result,
                recorded_at=now,
            )
        )

    async def list_ready(self, now, limit, *, after=None, session):
        rows = await _session(session).execute(
            text("""
SELECT g.release_at,g.grant_id FROM financial_manual_grants g
JOIN financial_obligations o
ON o.business_key='manual-grant:'||g.grant_id::text
JOIN financial_movements m ON m.obligation_id=o.id
WHERE g.release_at<=:now
AND (CAST(:after_at AS timestamptz) IS NULL OR (g.release_at,g.grant_id)>
 (CAST(:after_at AS timestamptz),CAST(:after_id AS uuid)))
GROUP BY g.grant_id,g.release_at
HAVING sum(CASE WHEN m.bucket_to='hold' THEN m.amount_minor ELSE 0 END
- CASE WHEN m.bucket_from='hold' THEN m.amount_minor ELSE 0 END)>0
ORDER BY g.release_at,g.grant_id LIMIT :limit
"""),
            {
                "now": now,
                "limit": limit,
                "after_at": after[0] if after else None,
                "after_id": after[1] if after else None,
            },
        )
        return tuple((row.release_at, row.grant_id) for row in rows)

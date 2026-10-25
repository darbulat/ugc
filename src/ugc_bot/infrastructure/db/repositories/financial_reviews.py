"""Read actual captured grounds and append immutable economic review facts."""

from types import SimpleNamespace

from sqlalchemy import insert, select, text

from ugc_bot.infrastructure.db.financial_review_models import TABLES
from ugc_bot.infrastructure.db.repositories.corrections import (
    SqlAlchemyCorrectionRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)
from ugc_bot.infrastructure.db.repositories.manual_grants import (
    SqlAlchemyManualGrantRepository,
)


class SqlAlchemyFinancialReviewRepository:
    async def load_scope(self, key, *, session):
        db = _session(session)
        original = await SqlAlchemyFinancialLedgerRepository().get_issue(
            key, session=db
        )
        if original is None:
            return None
        basis = original.basis
        capture = await SqlAlchemyManualGrantRepository().load_capture(
            basis.paid_item_id, session=db
        )
        if (
            basis.order_id,
            basis.payment_id,
            basis.policy_version,
            basis.currency,
        ) != (
            capture.order_id,
            capture.payment_id,
            capture.policy.version,
            "RUB",
        ):
            raise ValueError("financial_review_source_changed")
        document = await db.scalar(
            text("SELECT financial_review_document(:id)"),
            {"id": original.obligation_id},
        )
        if document is None:
            raise ValueError("financial_review_source_changed")
        digest = await db.scalar(
            text(
                "SELECT correction_approval_hash("
                "financial_review_document(:id))"
            ),
            {"id": original.obligation_id},
        )
        users = {basis.referred_user_id, basis.recipient_id, capture.client_id}
        if basis.assignment_id is not None:
            parties = await db.execute(
                text(
                    "SELECT creator_id,manager_id FROM item_assignments "
                    "WHERE assignment_id=:assignment"
                ),
                {"assignment": basis.assignment_id},
            )
            for creator, manager in parties:
                users.add(creator)
                if manager is not None:
                    users.add(manager)
        return SimpleNamespace(
            original=original,
            capture=capture,
            user_ids=tuple(sorted(users, key=str)),
            source_document=document,
            source_hash=digest,
        )

    async def lock_scope(self, scope, *, session):
        await SqlAlchemyManualGrantRepository().lock_funding(
            scope.capture, session=session
        )

    async def actor(self, actor_id, *, session):
        return await SqlAlchemyCorrectionRepository().actor(
            actor_id, session=session
        )

    async def command(self, actor_id, key, *, session):
        t = TABLES["commands"]
        return (
            (
                await _session(session).execute(
                    select(t).where(
                        t.c.actor_id == actor_id, t.c.operation_key == key
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

    async def active_case(self, obligation_id, *, session):
        cases, resolutions = TABLES["cases"], TABLES["resolutions"]
        return (
            (
                await _session(session).execute(
                    select(cases).where(
                        cases.c.obligation_id == obligation_id,
                        ~select(resolutions.c.case_id)
                        .where(resolutions.c.case_id == cases.c.case_id)
                        .exists(),
                    )
                )
            )
            .mappings()
            .one_or_none()
        )

    async def case(self, identity, *, session):
        return (
            (
                await _session(session).execute(
                    select(TABLES["cases"]).where(
                        TABLES["cases"].c.case_id == identity
                    )
                )
            )
            .mappings()
            .one_or_none()
        )

    async def append_case(self, fact, *, session):
        await _session(session).execute(insert(TABLES["cases"]).values(**fact))

    async def resolution(self, identity, *, session):
        return (
            (
                await _session(session).execute(
                    select(TABLES["resolutions"]).where(
                        TABLES["resolutions"].c.case_id == identity
                    )
                )
            )
            .mappings()
            .one_or_none()
        )

    async def append_resolution(self, fact, *, session):
        await _session(session).execute(
            insert(TABLES["resolutions"]).values(**fact)
        )

    async def context(self, *, page, limit, business_key, session):
        db = _session(session)
        grounds = (
            (
                await db.execute(
                    text("""
SELECT o.business_key,o.id obligation_id,o.kind,o.recipient_id,o.paid_item_id,
 o.amount_minor,o.currency,
 correction_approval_hash(financial_review_document(o.id)) current_source_hash,
 (SELECT jsonb_object_agg(bucket,balance) FROM (
  SELECT bucket,COALESCE(sum(CASE WHEN m.bucket_to=bucket THEN m.amount_minor
   ELSE 0 END-CASE WHEN m.bucket_from=bucket THEN m.amount_minor ELSE 0 END
   +CASE WHEN bucket IN ('debt','cancelled') AND m.movement_type='debt'
     THEN m.amount_minor WHEN bucket='debt' AND m.movement_type='recovery'
     THEN -m.amount_minor ELSE 0 END),0)
   balance FROM unnest(ARRAY['pending','hold','available','reserved','blocked',
    'paid','cancelled','debt']) bucket LEFT JOIN financial_movements m
   ON m.obligation_id=o.id GROUP BY bucket) balances) buckets
FROM financial_obligations o
WHERE (CAST(:key AS text) IS NULL OR o.business_key=:key)
 AND financial_review_document(o.id) IS NOT NULL
ORDER BY o.id LIMIT :limit OFFSET :offset
"""),
                    {
                        "key": business_key,
                        "limit": limit + 1,
                        "offset": page * limit,
                    },
                )
            )
            .mappings()
            .all()
        )
        cases, resolutions = TABLES["cases"], TABLES["resolutions"]
        rows = (
            (
                await db.execute(
                    select(cases)
                    .where(
                        ~select(resolutions.c.case_id)
                        .where(resolutions.c.case_id == cases.c.case_id)
                        .exists()
                    )
                    .order_by(cases.c.case_id)
                    .limit(limit + 1)
                    .offset(page * limit)
                )
            )
            .mappings()
            .all()
        )
        entries = []
        for row in rows[:limit]:
            entries.append(
                dict(
                    case_id=str(row["case_id"]),
                    version=1,
                    state="open",
                    business_key=row["business_key"],
                    obligation_id=str(row["obligation_id"]),
                    paid_item_id=str(row["paid_item_id"]),
                    recipient_id=str(row["recipient_id"]),
                    opened_at=row["opened_at"].isoformat(),
                    reason=row["reason"],
                    evidence_reference=row["evidence_reference"],
                )
            )
        return dict(
            cases=entries,
            grounds=[dict(g) for g in grounds[:limit]],
            has_more=len(rows) > limit or len(grounds) > limit,
            page=page,
        )

"""Actual campaign barriers and append-only lifecycle/quota persistence."""

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import insert, select, text

from ugc_bot.application.campaign_moderation_ports import (
    CampaignActorFacts,
    CampaignAuthority,
    CampaignCandidateFacts,
    CampaignCapabilities,
    CampaignExpiryBatch,
    CampaignExpiryItem,
    CampaignGrantFacts,
    CampaignPolicyFacts,
    CampaignPreflight,
    CampaignReadContext,
    CampaignSenderSnapshot,
    CampaignState,
    CampaignWriteContext,
)
from ugc_bot.application.native_principal_ports import require_current_principal
from ugc_bot.domain.campaign_capacity import (
    CampaignCapacityFacts,
    apply_capacity_delta,
)
from ugc_bot.domain.campaign_moderation import (
    CampaignLifecycleVersion,
    CampaignRevision,
)
from ugc_bot.domain.campaign_review import (
    CampaignDraftContent,
    CampaignSegmentV1,
)
from ugc_bot.domain.campaigns import CampaignConflict, digest
from ugc_bot.domain.financial import utc
from ugc_bot.infrastructure.campaign_codec import decode, encode
from ugc_bot.infrastructure.db.campaign_review_models import DRAFTS, REVISIONS
from ugc_bot.infrastructure.db.campaign_runtime_models import (
    CAPACITY,
    COMMANDS,
    DECISIONS,
    JOBS,
    STATES,
    SUBMISSIONS,
    TABLES,
)
from ugc_bot.infrastructure.db.identity_history_schema import (
    HISTORY_SNAPSHOT_LOCK_SQL,
)
from ugc_bot.infrastructure.db.models import UserModel, UserReferralBindingModel
from ugc_bot.infrastructure.db.repositories.campaign_review import (
    SqlAlchemyCampaignReviewRepository,
)
from ugc_bot.infrastructure.db.repositories.campaigns import (
    SqlAlchemyCampaignRepository,
    mapping,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session

CAMPAIGN_LOCK = "SELECT pg_advisory_xact_lock(2119754201, 170434820)"


@dataclass
class SqlAlchemyCampaignModerationRepository:
    foundation: SqlAlchemyCampaignRepository
    drafts: SqlAlchemyCampaignReviewRepository

    async def capabilities(self, *, session):
        db = _session(session)
        if db.get_bind().dialect.name != "postgresql":
            return CampaignCapabilities(False, False, False)
        ready = bool(
            await db.scalar(
                text(
                    "SELECT "
                    + " AND ".join(
                        f"to_regclass('{table.name}') IS NOT NULL"
                        for table in TABLES
                    )
                )
            )
        )
        return CampaignCapabilities(ready, ready, ready)

    async def preflight(
        self, actor_id, campaign_id, submission_id, *, purpose, session
    ):
        db = _session(session)
        owner = None
        if campaign_id is not None:
            owner = await db.scalar(
                select(DRAFTS.c.owner_id).where(
                    DRAFTS.c.campaign_id == campaign_id
                )
            )
        users = {actor_id}
        if owner:
            users.add(owner)
            users.update(
                await db.scalars(
                    select(UserReferralBindingModel.referred_user_id).where(
                        UserReferralBindingModel.referrer_user_id == owner
                    )
                )
            )
            for document in await db.scalars(
                select(SUBMISSIONS.c.document).where(
                    SUBMISSIONS.c.campaign_id == campaign_id
                )
            ):
                record = decode(document)
                users.update(row.candidate.user_id for row in record.sources)
            for document in await db.scalars(
                select(DECISIONS.c.document)
                .join(
                    SUBMISSIONS,
                    SUBMISSIONS.c.submission_id == DECISIONS.c.submission_id,
                )
                .where(SUBMISSIONS.c.campaign_id == campaign_id)
            ):
                users.add(decode(document).context.reviewer_id)
        return CampaignPreflight(
            actor_id,
            tuple(sorted(users, key=str)),
            purpose,
            campaign_id,
            submission_id,
        )

    async def prepare(self, preflight, *, principal, session):
        db = _session(session)
        for uid in preflight.user_ids:
            await db.execute(
                select(UserModel.user_id)
                .where(UserModel.user_id == uid)
                .with_for_update(read=True)
            )
        await db.execute(text(HISTORY_SNAPSHOT_LOCK_SQL))
        await db.execute(text(CAMPAIGN_LOCK))
        current = await self.preflight(
            preflight.actor_id,
            preflight.campaign_id,
            preflight.submission_id,
            purpose=preflight.purpose,
            session=session,
        )
        if not set(current.user_ids).issubset(preflight.user_ids):
            raise CampaignConflict("campaign_scope_changed")
        actor = await self._actor(preflight.actor_id, db)
        require_current_principal(
            principal,
            preflight.actor_id,
            actor.user_id,
            actor.telegram_id,
            actor.max_id,
        )
        return CampaignWriteContext(preflight, session, db.get_transaction())

    async def begin_read(self, actor_id, *, principal, session):
        at = await self.foundation.begin_snapshot(session=session)
        actor = await self._actor(actor_id, _session(session))
        require_current_principal(
            principal, actor_id, actor.user_id, actor.telegram_id, actor.max_id
        )
        return CampaignReadContext(actor_id, utc(at))

    async def _actor(self, actor_id, db):
        row = await mapping(
            db,
            select(
                UserModel.user_id,
                UserModel.status,
                UserModel.admin,
                UserModel.telegram_id,
                UserModel.max_id,
            ).where(UserModel.user_id == actor_id),
        )
        if row is None:
            raise LookupError("existing_campaign_account_required")
        return CampaignActorFacts(**row)

    def _context(self, context, session):
        db = _session(session)
        if isinstance(context, CampaignWriteContext) and (
            context.owner_session is not session
            or context.root_transaction is not db.get_transaction()
        ):
            raise ValueError("campaign_caller_transaction_required")
        return db

    async def authority(self, actor_id, *, context, session):
        actor = await self._actor(actor_id, self._context(context, session))
        policy = await self.foundation.current("policy", session=session)
        grant = await self.publisher(actor_id, context=context, session=session)
        return CampaignAuthority(
            actor,
            CampaignPolicyFacts.from_mapping(policy) if policy else None,
            grant,
        )

    async def publisher(self, owner_id, *, context, session):
        self._context(context, session)
        row = await self.foundation.current(
            "publisher", owner_id, session=session
        )
        return (
            CampaignGrantFacts(owner_id, row["version"], row["active"])
            if row
            else None
        )

    async def command(self, actor_id, operation_key, *, context, session):
        doc = await self._context(context, session).scalar(
            select(COMMANDS.c.document).where(
                COMMANDS.c.actor_id == actor_id,
                COMMANDS.c.operation_key == operation_key,
            )
        )
        return decode(doc) if doc is not None else None

    async def state(self, campaign_id, *, context, session):
        db = self._context(context, session)
        row = await mapping(
            db,
            select(REVISIONS)
            .where(REVISIONS.c.campaign_id == campaign_id)
            .order_by(REVISIONS.c.version.desc())
            .limit(1),
        )
        if row is None:
            return None
        current = await mapping(
            db,
            select(STATES)
            .where(STATES.c.campaign_id == campaign_id)
            .order_by(STATES.c.version.desc())
            .limit(1),
        )
        if current and current["version"] >= row["version"]:
            return decode(current["document"])
        revision = CampaignRevision(
            row["owner_id"],
            campaign_id,
            row["version"],
            row["policy_version"],
            row["terms_hash"],
            CampaignDraftContent.parse(row["content"]),
            CampaignSegmentV1.parse(row["segment"]),
            row["revision_digest"],
        )
        return CampaignState(
            revision,
            CampaignLifecycleVersion(row["version"], row["version"]),
            "draft",
        )

    async def candidates(self, owner_id, *, context, session):
        self._context(context, session)
        return tuple(
            [
                CampaignCandidateFacts.from_member(row)
                async for row in self.drafts.candidates(
                    owner_id, session=session
                )
            ]
        )

    async def sender_snapshot(self, owner_id, *, context, session):
        self._context(context, session)
        label = (
            await self.foundation._label(_session(session), owner_id) or "UMC"
        )
        return CampaignSenderSnapshot(
            label, digest({"owner_id": str(owner_id), "label": label})
        )

    async def submission(self, submission_id, *, context, session):
        doc = await self._context(context, session).scalar(
            select(SUBMISSIONS.c.document).where(
                SUBMISSIONS.c.submission_id == submission_id
            )
        )
        return decode(doc) if doc is not None else None

    async def capacity_facts(
        self, owner_id, recipients, *, at, context, session
    ):
        db = self._context(context, session)
        facts = CampaignCapacityFacts((), (), ())
        for document in await db.scalars(
            select(CAPACITY.c.document).order_by(CAPACITY.c.sequence)
        ):
            facts = apply_capacity_delta(facts, decode(document))
        return facts

    async def append_capacity(self, delta, event_id, at, *, session):
        await _session(session).execute(
            insert(CAPACITY).values(
                event_id=event_id,
                kind="delta",
                document=encode(delta),
                recorded_at=utc(at),
            )
        )

    async def due(self, *, at, limit, context, session):
        self._context(context, session)
        facts = await self.capacity_facts(
            None, (), at=at, context=context, session=session
        )
        items = []
        for occupation in facts.occupations:
            expired_reservations = tuple(
                row.reservation_id
                for row in facts.reservations
                if row.campaign_id == occupation.campaign_id
                and row.status == "reserved"
                and row.expires_at <= at
            )
            if occupation.deadline <= at or expired_reservations:
                state = await self.state(
                    occupation.campaign_id, context=context, session=session
                )
                terminal = occupation.deadline <= at
                ids = tuple(
                    row.reservation_id
                    for row in facts.reservations
                    if row.campaign_id == occupation.campaign_id
                    and row.status == "reserved"
                    and (terminal or row.expires_at <= at)
                )
                items.append(
                    CampaignExpiryItem(
                        state,
                        ids,
                        terminal,
                        min(occupation.deadline, at),
                        "campaign_expired",
                    )
                )
        return CampaignExpiryBatch(tuple(items[:limit]), len(items) > limit)

    async def review_page(self, page, *, context, session):
        db = self._context(context, session)
        docs = await db.scalars(
            select(SUBMISSIONS.c.document)
            .order_by(SUBMISSIONS.c.recorded_at, SUBMISSIONS.c.submission_id)
            .offset(page * 25)
            .limit(26)
        )
        return tuple(decode(doc) for doc in docs)

    async def apply(self, write, *, context, session):
        db = self._context(context, session)
        at = write.receipt.recorded_at
        for state in write.states:
            await db.execute(
                insert(STATES).values(
                    campaign_id=state.campaign_id,
                    version=state.version.campaign_version,
                    owner_id=state.owner_id,
                    state=state.state,
                    document=encode(state),
                    recorded_at=at,
                )
            )
        for record in write.submissions:
            await db.execute(
                insert(SUBMISSIONS).values(
                    submission_id=record.seal.submission_id,
                    campaign_id=record.seal.revision.campaign_id,
                    owner_id=record.seal.revision.owner_id,
                    document=encode(record),
                    recorded_at=at,
                )
            )
        for decision in write.decisions:
            await db.execute(
                insert(DECISIONS).values(
                    review_id=decision.review_id,
                    submission_id=decision.context.submission.submission_id,
                    document=encode(decision),
                    recorded_at=at,
                )
            )
        for job in write.jobs:
            record = await self.submission(
                job.submission_id, context=context, session=session
            )
            source = next(
                row for row in record.sources if row.source_id == job.source_id
            )
            await db.execute(
                insert(JOBS).values(
                    job_id=job.job_id,
                    campaign_id=job.campaign_id,
                    submission_id=job.submission_id,
                    review_id=job.review_id,
                    source_id=job.source_id,
                    recipient_id=source.candidate.user_id,
                    document=encode(job),
                    recorded_at=at,
                )
            )
        await self.append_capacity(
            write.capacity,
            uuid5(
                NAMESPACE_URL,
                f"campaign:{write.receipt.actor_id}:{write.receipt.operation_key}",
            ),
            at,
            session=session,
        )
        await db.execute(
            insert(COMMANDS).values(
                actor_id=write.receipt.actor_id,
                operation_key=write.receipt.operation_key,
                document=encode(write.receipt),
                recorded_at=at,
            )
        )

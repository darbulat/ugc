"""SQL campaign dispatch, delivery evidence and recipient responses."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid5

from sqlalchemy import exists, func, insert, select, text

from ugc_bot.application.campaign_runtime_ports import CampaignAttempt
from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.services.campaign_eligibility import revalidate_sources
from ugc_bot.domain.campaign_capacity import (
    CampaignCapacityDelta,
    CampaignOccupationClose,
    CampaignReservationRelease,
    CampaignUsage,
    apply_capacity_delta,
    evaluate_capacity,
)
from ugc_bot.domain.campaigns import CampaignConflict, digest
from ugc_bot.domain.financial import utc
from ugc_bot.infrastructure.campaign_codec import decode, encode
from ugc_bot.infrastructure.db.campaign_runtime_models import (
    ATTEMPTS,
    DECISIONS,
    JOBS,
    OBSERVATIONS,
    OUTCOMES,
    RESPONSES,
)
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.repositories.campaign_moderation import (
    CAMPAIGN_LOCK,
    SqlAlchemyCampaignModerationRepository,
)
from ugc_bot.infrastructure.db.repositories.campaigns import mapping
from ugc_bot.infrastructure.db.repositories.financial_items import _session


@dataclass
class SqlAlchemyCampaignDeliveryRepository:
    moderation: SqlAlchemyCampaignModerationRepository
    clock: Clock

    async def pending(self, at, limit, *, session):
        db = _session(session)
        policy = await self.moderation.foundation.current(
            "policy", session=session
        )
        if policy is not None:
            limit = min(limit, policy["limits"]["claim_batch_size"])
        # Detached candidates only; prepare performs all final authority checks.
        return tuple(
            await db.scalars(
                select(JOBS.c.job_id)
                .where(
                    ~exists(
                        select(OUTCOMES.c.job_id).where(
                            OUTCOMES.c.job_id == JOBS.c.job_id
                        )
                    )
                )
                .order_by(JOBS.c.recorded_at, JOBS.c.job_id)
                .limit(limit)
            )
        )

    async def _source(self, job_id, *, principal=None, actor_id=None, session):
        db = _session(session)
        row = await mapping(db, select(JOBS).where(JOBS.c.job_id == job_id))
        if row is None:
            raise LookupError("campaign_submission_not_found")
        job = decode(row["document"])
        # Actual ownership comes from the retained submission.
        record = await self.moderation.submission(
            job.submission_id, context=None, session=session
        )
        owner = record.seal.revision.owner_id
        preflight = await self.moderation.preflight(
            actor_id or owner,
            job.campaign_id,
            None,
            purpose="cancel",
            session=session,
        )
        context = await self.moderation.prepare(
            preflight, principal=principal, session=session
        )
        return row, job, record, context

    async def _eligible(
        self, row, job, record, context, at, session, *, dispatch=True
    ):
        authority = await self.moderation.authority(
            record.seal.revision.owner_id, context=context, session=session
        )
        policy, grant = authority.policy, authority.grant
        decision = decode(
            await _session(session).scalar(
                select(DECISIONS.c.document).where(
                    DECISIONS.c.review_id == job.review_id
                )
            )
        )
        reviewer = await self.moderation._actor(
            decision.context.reviewer_id, _session(session)
        )
        state = await self.moderation.state(
            job.campaign_id, context=context, session=session
        )
        if not (
            authority.actor.status == "active"
            and policy
            and policy.enabled
            and grant
            and grant.active
            and grant.version == record.seal.grant_version
            and policy.publication_version == job.publication_version
            and reviewer.admin
            and reviewer.status == "active"
            and state.state == "approved_waiting"
            and state.submission_id == job.submission_id
            and job.envelope_digest == record.seal.envelope.digest
            and job.revision_digest == record.seal.revision.revision_digest
            and job.audience_digest == decision.context.audience.digest
            and job.source_id
            in {
                source.source_id for source in decision.context.audience.sources
            }
            and (not dispatch or at < job.dispatch_deadline)
        ):
            return None
        members = await self.moderation.candidates(
            state.owner_id, context=context, session=session
        )
        eligibility, _ = revalidate_sources(
            record.sources,
            members,
            owner_id=state.owner_id,
            policy=policy,
            segment=state.revision.segment,
            at=at,
        )
        return next(
            (
                member
                for member in eligibility.selected
                if member.user_id == row["recipient_id"]
            ),
            None,
        )

    async def _outcome(
        self, job_id, state, at, *, reason=None, reference=None, session
    ):
        await _session(session).execute(
            insert(OUTCOMES).values(
                outcome_id=uuid5(job_id, "outcome"),
                job_id=job_id,
                state=state,
                provider_reference=reference,
                reason=reason,
                recorded_at=at,
            )
        )

    async def _release(self, job, context, at, reason, *, session):
        facts = await self.moderation.capacity_facts(
            None, (), at=at, context=context, session=session
        )
        releases = tuple(
            CampaignReservationRelease(row.reservation_id, at, reason)
            for row in facts.reservations
            if row.job_id == job.job_id and row.status == "reserved"
        )
        return CampaignCapacityDelta(releases=releases)

    async def prepare(self, job_id, at, *, access, session):
        db = _session(session)
        row, job, record, context = await self._source(job_id, session=session)
        at = utc(self.clock.now())
        if await db.scalar(
            select(OUTCOMES.c.job_id).where(OUTCOMES.c.job_id == job_id)
        ):
            return None
        previous = await mapping(
            db, select(ATTEMPTS).where(ATTEMPTS.c.job_id == job_id)
        )
        if previous:
            if previous["deadline"] <= at:
                await self._outcome(
                    job_id,
                    "unknown",
                    at,
                    reason="campaign_attempt_interrupted",
                    session=session,
                )
                await self._close(job.campaign_id, context, at, session=session)
            return None
        member = await self._eligible(row, job, record, context, at, session)
        delta = await self._release(
            job, context, at, "attempt_started", session=session
        )
        facts = await self.moderation.capacity_facts(
            None, (), at=at, context=context, session=session
        )
        authority = await self.moderation.authority(
            record.seal.revision.owner_id, context=context, session=session
        )
        if access is not None and member is not None:
            try:
                await access.require_access(
                    record.seal.revision.owner_id,
                    action="send",
                    at=at,
                    session=session,
                )
            except PermissionError:
                member = None
        if member is not None:
            observation = evaluate_capacity(
                apply_capacity_delta(facts, delta),
                limits=authority.policy.limits,
                owner_id=record.seal.revision.owner_id,
                recipients=(member.scope,),
                at=at,
                intent="approve",
            )
            if observation.reasons:
                member = None
        if member is None:
            await self._outcome(
                job_id,
                "skipped",
                at,
                reason="campaign_recipient_or_terms_changed",
                session=session,
            )
            await self.moderation.append_capacity(
                delta, uuid5(job_id, "release"), at, session=session
            )
            await self._close(job.campaign_id, context, at, session=session)
            return None
        limits = authority.policy.limits
        inflight = await db.scalar(
            select(func.count())
            .select_from(ATTEMPTS)
            .where(
                ~exists(
                    select(OUTCOMES.c.job_id).where(
                        OUTCOMES.c.job_id == ATTEMPTS.c.job_id
                    )
                ),
                ATTEMPTS.c.deadline > at,
            )
        )
        recent = sum(
            value.kind == "attempt_started"
            and at - value.occurred_at < timedelta(seconds=1)
            for value in facts.usage
        )
        if (
            inflight >= limits["worker_concurrency"]
            or recent >= limits["starts_per_second"]
        ):
            return None
        locale = await db.scalar(
            select(UserModel.language).where(
                UserModel.user_id == member.user_id
            )
        )
        envelopes = {
            envelope.locale: envelope
            for envelope in record.seal.envelope.locales
        }
        envelope = envelopes.get(
            locale, envelopes[record.seal.envelope.default_locale]
        )
        attempt = CampaignAttempt(
            uuid5(job_id, "attempt"),
            job_id,
            "telegram",
            member.scope.destination,
            "chat_id",
            envelope.text,
            envelope.action_url,
            envelope.action_label,
            at,
            at + timedelta(seconds=120),
        )
        await db.execute(
            insert(ATTEMPTS).values(
                attempt_id=attempt.attempt_id,
                job_id=job_id,
                deadline=attempt.deadline,
                document=encode(attempt),
                recorded_at=at,
            )
        )
        delta = delta.plus(
            CampaignCapacityDelta(
                usage=(
                    CampaignUsage(
                        uuid5(job_id, "start"),
                        "attempt_started",
                        record.seal.revision.owner_id,
                        at,
                        member.scope,
                    ),
                )
            )
        )
        await self.moderation.append_capacity(
            delta, uuid5(job_id, "start-capacity"), at, session=session
        )
        return attempt

    async def _close(self, campaign_id, context, at, *, session):
        db = _session(session)
        pending = await db.scalar(
            select(JOBS.c.job_id)
            .where(
                JOBS.c.campaign_id == campaign_id,
                ~exists(
                    select(OUTCOMES.c.job_id).where(
                        OUTCOMES.c.job_id == JOBS.c.job_id
                    )
                ),
            )
            .limit(1)
        )
        if pending is None:
            await self.moderation.append_capacity(
                CampaignCapacityDelta(
                    closed=(
                        CampaignOccupationClose(
                            campaign_id, at, "dispatch_completed"
                        ),
                    )
                ),
                uuid5(campaign_id, "dispatch-completed"),
                at,
                session=session,
            )

    async def finish(self, attempt, status, reference, reason, at, *, session):
        db = _session(session)
        # Retaining a real transport result needs no renewed send permission.
        await db.execute(text(CAMPAIGN_LOCK))
        row = await mapping(
            db, select(JOBS).where(JOBS.c.job_id == attempt.job_id)
        )
        if row is None:
            raise ValueError("campaign_attempt_mismatch")
        job = decode(row["document"])
        stored = await db.scalar(
            select(ATTEMPTS.c.document).where(
                ATTEMPTS.c.job_id == attempt.job_id
            )
        )
        if stored is None or decode(stored) != attempt:
            raise ValueError("campaign_attempt_mismatch")
        observation_id = uuid5(
            attempt.attempt_id, digest([status, reference, reason])
        )
        if not await db.scalar(
            select(OBSERVATIONS.c.observation_id).where(
                OBSERVATIONS.c.observation_id == observation_id
            )
        ):
            await db.execute(
                insert(OBSERVATIONS).values(
                    observation_id=observation_id,
                    attempt_id=attempt.attempt_id,
                    job_id=attempt.job_id,
                    state=status,
                    provider_reference=reference,
                    reason=reason,
                    recorded_at=at,
                )
            )
        if await db.scalar(
            select(OUTCOMES.c.job_id).where(OUTCOMES.c.job_id == attempt.job_id)
        ):
            return
        if reference and await db.scalar(
            select(OUTCOMES.c.job_id).where(
                OUTCOMES.c.provider_reference == reference
            )
        ):
            status, reference, reason = (
                "unknown",
                None,
                "campaign_receipt_reused",
            )
        await self._outcome(
            attempt.job_id,
            status,
            at,
            reason=reason,
            reference=reference,
            session=session,
        )
        await self._close(job.campaign_id, None, at, session=session)

    async def _response(self, actor_id, campaign_id, db):
        return await mapping(
            db,
            select(RESPONSES)
            .where(
                RESPONSES.c.campaign_id == campaign_id,
                RESPONSES.c.recipient_id == actor_id,
            )
            .order_by(RESPONSES.c.version.desc())
            .limit(1),
        )

    async def recipient_view(
        self, actor_id, campaign_id, *, principal, at, session
    ):
        context = await self.moderation.begin_read(
            actor_id, principal=principal, session=session
        )
        db = _session(session)
        row = await mapping(
            db,
            select(JOBS)
            .where(
                JOBS.c.campaign_id == campaign_id,
                JOBS.c.recipient_id == actor_id,
            )
            .order_by(JOBS.c.recorded_at.desc())
            .limit(1),
        )
        if row is None:
            raise LookupError("campaign_submission_not_found")
        job = decode(row["document"])
        record = await self.moderation.submission(
            job.submission_id, context=context, session=session
        )
        member = await self._eligible(
            row, job, record, context, at, session, dispatch=False
        )
        response = await self._response(actor_id, campaign_id, db)
        choices = ["interested", "declined"] if member is not None else []
        if response and response["choice"] != "withdrawn":
            choices.append("withdrawn")
        return {
            "campaign_id": str(campaign_id),
            "content": record.seal.revision.content.payload,
            "sender_label": record.seal.envelope.sender_label,
            "version": response["version"] if response else 0,
            "choice": response["choice"] if response else None,
            "allowed_choices": choices,
            "as_of": utc(at).isoformat(),
        }

    async def respond(
        self,
        actor_id,
        campaign_id,
        operation_key,
        expected_version,
        choice,
        payload_hash,
        *,
        principal,
        at,
        session,
    ):
        db = _session(session)
        row = await mapping(
            db,
            select(JOBS)
            .where(
                JOBS.c.campaign_id == campaign_id,
                JOBS.c.recipient_id == actor_id,
            )
            .order_by(JOBS.c.recorded_at.desc())
            .limit(1),
        )
        if row is None:
            raise LookupError("campaign_submission_not_found")
        row, job, record, context = await self._source(
            row["job_id"],
            principal=principal,
            actor_id=actor_id,
            session=session,
        )
        actor = await self.moderation._actor(actor_id, db)
        if actor.status != "active":
            raise PermissionError("campaign_active_actor_required")
        previous = await mapping(
            db,
            select(RESPONSES).where(
                RESPONSES.c.recipient_id == actor_id,
                RESPONSES.c.operation_key == operation_key,
            ),
        )
        if previous:
            if previous["payload_hash"] != payload_hash:
                raise CampaignConflict("campaign_operation_conflict")
            return {
                "campaign_id": str(campaign_id),
                "version": previous["version"],
                "choice": previous["choice"],
            }
        current = await self._response(actor_id, campaign_id, db)
        version = current["version"] if current else 0
        if version != expected_version:
            raise CampaignConflict("campaign_version_conflict")
        at = utc(self.clock.now())
        member = await self._eligible(
            row, job, record, context, at, session, dispatch=False
        )
        if choice == "withdrawn":
            if not current or current["choice"] == "withdrawn":
                raise CampaignConflict("campaign_not_active")
        elif member is None:
            raise PermissionError("campaign_recipient_no_longer_eligible")
        await db.execute(
            insert(RESPONSES).values(
                recipient_id=actor_id,
                operation_key=operation_key,
                campaign_id=campaign_id,
                version=version + 1,
                choice=choice,
                payload_hash=payload_hash,
                recorded_at=at,
            )
        )
        return {
            "campaign_id": str(campaign_id),
            "version": version + 1,
            "choice": choice,
        }

    async def report(self, actor_id, campaign_id, *, principal, at, session):
        from collections import Counter

        context = await self.moderation.begin_read(
            actor_id, principal=principal, session=session
        )
        state = await self.moderation.state(
            campaign_id, context=context, session=session
        )
        if state is None or state.owner_id != actor_id:
            raise PermissionError("campaign_owner_required")
        db = _session(session)
        rows = (
            await db.execute(
                select(
                    JOBS.c.job_id,
                    JOBS.c.recipient_id,
                    OUTCOMES.c.state,
                    ATTEMPTS.c.attempt_id,
                )
                .outerjoin(OUTCOMES, OUTCOMES.c.job_id == JOBS.c.job_id)
                .outerjoin(ATTEMPTS, ATTEMPTS.c.job_id == JOBS.c.job_id)
                .where(JOBS.c.campaign_id == campaign_id)
            )
        ).mappings()
        counts = Counter()
        for row in rows:
            counts[
                row["state"] or ("preparing" if row["attempt_id"] else "queued")
            ] += 1
        responses = (
            await db.execute(
                select(RESPONSES)
                .where(RESPONSES.c.campaign_id == campaign_id)
                .order_by(RESPONSES.c.version)
            )
        ).mappings()
        current = {row["recipient_id"]: row["choice"] for row in responses}
        return {
            "campaign_id": str(campaign_id),
            "delivery": dict(counts),
            "responses": dict(Counter(current.values())),
            "as_of": utc(at).isoformat(),
            "accepted_means": "provider_accepted_not_read",
        }

"""Dormant exact-subset review; approved jobs have no delivery capability."""

from collections import Counter
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from ugc_bot.application.campaign_moderation_ports import (
    CampaignDecisionFacts,
    CampaignDeliveryJob,
    CampaignGrantFacts,
    CampaignModerationRepository,
    CampaignReadContext,
    CampaignState,
    CampaignSubmissionRecord,
)
from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.campaign_eligibility import revalidate_sources
from ugc_bot.application.services.campaign_submission_service import (
    advance,
    command_state,
    commit_result,
    ensure_scope,
    open_write,
    require_authority,
    require_capabilities,
    retained_result,
)
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.domain.campaign_capacity import (
    CampaignCapacityDelta,
    CampaignOccupation,
    CampaignReservation,
)
from ugc_bot.domain.campaign_moderation import (
    CampaignAudience,
    CampaignReviewContext,
    CancelCampaign,
    ReviewCampaign,
)
from ugc_bot.domain.campaigns import CampaignConflict
from ugc_bot.domain.financial import utc


@dataclass
class CampaignModerationService:
    repository: CampaignModerationRepository
    capacity: Any
    clock: Clock

    async def _read(self, actor_id, principal, session):
        context = await self.repository.begin_read(
            actor_id, principal=principal, session=session
        )
        await require_capabilities(self.repository, session)
        if (
            not isinstance(context, CampaignReadContext)
            or context.actor_id != actor_id
        ):
            raise ValueError("campaign_read_context_unavailable")
        authority = await self.repository.authority(
            actor_id, context=context, session=session
        )
        require_authority(authority, actor_id, principal, "admin")
        return context, authority

    async def _pending(
        self,
        actor_id,
        submission_id,
        context,
        authority,
        session,
        *,
        approval,
        expected_state,
    ):
        record = await self.repository.submission(
            submission_id, context=context, session=session
        )
        if not isinstance(record, CampaignSubmissionRecord):
            raise LookupError("campaign_submission_not_found")
        seal = record.seal
        if seal.revision.owner_id == actor_id:
            raise PermissionError("campaign_distinct_admin_required")
        state = await self.repository.state(
            seal.revision.campaign_id, context=context, session=session
        )
        if (
            not isinstance(state, CampaignState)
            or state.state != "submitted"
            or state.submission_id != submission_id
        ):
            raise CampaignConflict("campaign_not_submitted")
        if (
            seal.submission_id != submission_id
            or state.revision != seal.revision
            or (expected_state is not None and expected_state != state)
        ):
            raise ValueError("campaign_submission_integrity_unavailable")
        grant = await self.repository.publisher(
            state.owner_id, context=context, session=session
        )
        policy = authority.policy
        if (
            policy is None
            or not isinstance(grant, CampaignGrantFacts)
            or grant.owner_id != state.owner_id
        ):
            raise ValueError("campaign_review_authority_unavailable")
        if approval and (
            not policy.enabled
            or policy.publication_version != seal.revision.policy_version
            or policy.terms_hash != seal.revision.terms_hash
        ):
            raise CampaignConflict("campaign_terms_changed")
        if approval and (
            not grant.active or grant.version != seal.grant_version
        ):
            raise CampaignConflict("campaign_publisher_changed")
        return record, state, policy, grant

    async def _review(
        self,
        actor_id,
        submission_id,
        context,
        authority,
        session,
        *,
        approval=False,
        expected_state=None,
    ):
        record, state, policy, grant = await self._pending(
            actor_id,
            submission_id,
            context,
            authority,
            session,
            approval=approval,
            expected_state=expected_state,
        )
        seal = record.seal
        members = await self.repository.candidates(
            state.owner_id, context=context, session=session
        )
        ensure_scope(context, members, state.owner_id)
        at = utc(self.clock.now())
        if at >= seal.review_deadline:
            raise CampaignConflict("campaign_review_expired")
        eligibility, audience = revalidate_sources(
            record.sources,
            members,
            owner_id=state.owner_id,
            policy=policy,
            segment=state.revision.segment,
            at=at,
        )
        if not callable(getattr(self.capacity, "observe", None)):
            raise ValueError("campaign_capacity_unavailable")
        observation = await self.capacity.observe(
            state.owner_id,
            tuple(row.scope for row in eligibility.selected),
            policy,
            context=context,
            session=session,
        )
        blocked = set(observation.blocked_recipients)
        surviving = tuple(
            row for row in eligibility.selected if row.user_id not in blocked
        )
        blocked_sources = {
            source.source_id
            for source in record.sources
            if source.candidate.user_id in blocked
        }
        audience = CampaignAudience(
            tuple(
                row
                for row in audience.sources
                if row.source_id not in blocked_sources
            )
        )
        if blocked:
            observation = await self.capacity.observe(
                state.owner_id,
                tuple(row.scope for row in surviving),
                policy,
                context=context,
                session=session,
            )
        if observation.observed_at >= seal.review_deadline:
            raise CampaignConflict("campaign_review_expired")
        exclusions = Counter(dict(eligibility.exclusions))
        if blocked_sources:
            exclusions["recipient_capacity"] += len(blocked_sources)
        reviewed = CampaignReviewContext(
            seal,
            state.version,
            actor_id,
            policy.stream_version,
            grant.version,
            audience,
            observation.digest,
        )
        detail = {
            **state.safe,
            "submission_id": str(submission_id),
            "submitted_count": len(record.sources),
            "surviving_count": len(audience.sources),
            "exclusions": dict(sorted(exclusions.items())),
            "content": state.revision.content.payload,
            "segment": state.revision.segment.payload,
            "envelope": seal.envelope.payload,
            "envelope_digest": seal.envelope.digest,
            "review_context": reviewed.digest,
            "capacity": observation.safe,
            "screening_matches": ContentModerationService().get_banned_matches(
                state.revision.content.title
                + "\n"
                + state.revision.content.text
            ),
        }
        return detail, reviewed, record, state, policy, surviving

    async def review_detail(
        self,
        actor_id: UUID,
        submission_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
        session: object,
    ):
        context, authority = await self._read(actor_id, principal, session)
        detail, *_ = await self._review(
            actor_id, submission_id, context, authority, session
        )
        return detail

    async def queue(
        self,
        actor_id: UUID,
        page: int,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
        session: object,
    ):
        if type(page) is not int or not 0 <= page <= 100000:
            raise ValueError("campaign_invalid_page")
        context, _ = await self._read(actor_id, principal, session)
        rows = await self.repository.review_page(
            page, context=context, session=session
        )
        result = []
        for row in rows[:25]:
            state = await self.repository.state(
                row.seal.revision.campaign_id, context=context, session=session
            )
            if (
                state is not None
                and state.state == "submitted"
                and state.owner_id != actor_id
            ):
                result.append(
                    {
                        **state.safe,
                        "submission_id": str(row.seal.submission_id),
                        "title": row.seal.revision.content.title,
                        "submitted_count": len(row.sources),
                    }
                )
        return {
            "submissions": result,
            "page": page,
            "has_more": len(rows) > 25,
            "as_of": utc(context.as_of).isoformat(),
        }

    async def decide(
        self,
        command: ReviewCampaign,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
        session: object,
    ):
        if not isinstance(command, ReviewCampaign):
            raise ValueError("typed_campaign_review_required")
        context, authority = await open_write(
            self.repository, command, "decide", "admin", principal, session
        )
        replay = await retained_result(
            self.repository, command, context, authority, session
        )
        if replay is not None:
            return replay
        state = await command_state(self.repository, command, context, session)
        if (
            state.revision.revision_digest != command.revision_digest
            or state.submission_id != command.submission_id
        ):
            raise CampaignConflict("campaign_revision_changed")
        _, reviewed, record, state, policy, surviving = await self._review(
            command.actor_id,
            command.submission_id,
            context,
            authority,
            session,
            approval=command.decision == "approve",
            expected_state=state,
        )
        if reviewed.digest != command.review_context:
            raise CampaignConflict("campaign_review_context_changed")
        at = utc(self.clock.now())
        review_id = uuid5(
            NAMESPACE_URL,
            f"ugc:campaign-review:{command.actor_id}:{command.operation_key}",
        )
        jobs: tuple[CampaignDeliveryJob, ...]
        if command.decision == "reject":
            delta = await self.capacity.terminal(
                state, at, "rejected", context=context, session=session
            )
            states, jobs, deadline = (), (), None
            current = advance(state, "rejected")
        else:
            if not reviewed.audience.sources:
                raise CampaignConflict("campaign_empty_audience")
            observation, settlement = await self.capacity.admission(
                state.owner_id,
                tuple(row.scope for row in surviving),
                policy,
                "approve",
                context=context,
                session=session,
            )
            at = observation.observed_at
            if at >= record.seal.review_deadline:
                raise CampaignConflict("campaign_review_expired")
            if (
                replace(reviewed, capacity_digest=observation.digest).digest
                != command.review_context
            ):
                raise CampaignConflict("campaign_review_context_changed")
            if observation.reasons:
                raise CampaignConflict("campaign_capacity_exceeded")
            deadline = at + timedelta(
                seconds=policy.limits["dispatch_ttl_seconds"]
            )
            jobs = tuple(
                CampaignDeliveryJob(
                    uuid5(review_id, str(row.source_id)),
                    state.campaign_id,
                    command.submission_id,
                    review_id,
                    row.source_id,
                    state.revision.revision_digest,
                    reviewed.audience.digest,
                    record.seal.envelope.digest,
                    policy.publication_version,
                    deadline,
                )
                for row in reviewed.audience.sources
            )
            members = {row.user_id: row for row in surviving}
            sources = {row.source_id: row for row in record.sources}
            reservations = tuple(
                CampaignReservation(
                    uuid5(job.job_id, "reservation"),
                    job.job_id,
                    state.campaign_id,
                    state.owner_id,
                    members[sources[job.source_id].candidate.user_id].scope,
                    observation.window,
                    min(deadline, observation.window.end),
                )
                for job in jobs
            )
            delta = settlement.capacity.plus(
                CampaignCapacityDelta(
                    reservations=reservations,
                    opened=(
                        CampaignOccupation(
                            state.campaign_id, state.owner_id, deadline
                        ),
                    ),
                )
            )
            states = settlement.states
            current = advance(state, "approved_waiting")
        decision = CampaignDecisionFacts(
            review_id, reviewed, command.decision, command.reason, at, deadline
        )
        result = {
            **current.safe,
            "review_id": str(review_id),
            "decision": command.decision,
            "reason": command.reason,
            "approved_count": len(jobs),
            "delivery_state": "queued" if jobs else "not_applicable",
        }
        return await commit_result(
            self.repository,
            command,
            context,
            session,
            at,
            result,
            states=states + (current,),
            decisions=(decision,),
            jobs=jobs,
            capacity=delta,
        )

    async def cancel(
        self,
        command: CancelCampaign,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
        session: object,
    ):
        if not isinstance(command, CancelCampaign):
            raise ValueError("typed_campaign_cancel_required")
        context, authority = await open_write(
            self.repository, command, "cancel", "owner", principal, session
        )
        replay = await retained_result(
            self.repository, command, context, authority, session
        )
        if replay is not None:
            return replay
        if not callable(getattr(self.capacity, "terminal", None)):
            raise ValueError("campaign_capacity_unavailable")
        state = await command_state(self.repository, command, context, session)
        if state.owner_id != command.actor_id:
            raise PermissionError("campaign_owner_required")
        if state.state not in ("submitted", "approved_waiting"):
            raise CampaignConflict("campaign_not_active")
        at = utc(self.clock.now())
        delta = await self.capacity.terminal(
            state, at, "cancelled", context=context, session=session
        )
        current = advance(state, "cancelled")
        return await commit_result(
            self.repository,
            command,
            context,
            session,
            at,
            current.safe,
            states=(current,),
            capacity=delta,
        )

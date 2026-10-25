"""Dormant sealed submissions in one supplied caller transaction."""

from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from ugc_bot.application.campaign_message_templates import (
    CAMPAIGN_TEMPLATES,
    CampaignMessageTemplates,
    render_campaign_envelope,
)
from ugc_bot.application.campaign_moderation_ports import (
    CampaignAuthority,
    CampaignCapabilities,
    CampaignCommandReceipt,
    CampaignFrozenMap,
    CampaignGrantFacts,
    CampaignModerationRepository,
    CampaignMutation,
    CampaignPolicyFacts,
    CampaignSourceFacts,
    CampaignState,
    CampaignSubmissionRecord,
    CampaignWriteContext,
)
from ugc_bot.application.campaign_runtime_ports import CampaignAccess
from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
    require_current_principal,
)
from ugc_bot.application.services.campaign_eligibility import evaluate_audience
from ugc_bot.domain.campaign_capacity import (
    CampaignCapacityDelta,
    CampaignOccupation,
    CampaignUsage,
)
from ugc_bot.domain.campaign_moderation import (
    CampaignAudience,
    CampaignLifecycleVersion,
    CampaignSourceEvidence,
    CampaignSubmissionSeal,
    SubmitCampaign,
)
from ugc_bot.domain.campaigns import CampaignConflict
from ugc_bot.domain.financial import utc


async def require_capabilities(repository, session):
    if session is None or not callable(
        getattr(repository, "capabilities", None)
    ):
        raise ValueError("campaign_moderation_unavailable")
    ready = await repository.capabilities(session=session)
    if not isinstance(ready, CampaignCapabilities) or any(
        value is not True
        for value in (ready.context, ready.capacity, ready.persistence)
    ):
        raise ValueError("campaign_moderation_unavailable")


def require_authority(authority, actor_id, principal, role):
    if (
        not isinstance(authority, CampaignAuthority)
        or authority.actor.user_id != actor_id
    ):
        raise ValueError("campaign_moderation_unavailable")
    actor = authority.actor
    try:
        require_current_principal(
            principal, actor_id, actor.user_id, actor.telegram_id, actor.max_id
        )
    except ValueError:
        raise PermissionError("campaign_principal_changed") from None
    if role != "owner" and actor.status != "active":
        raise PermissionError("campaign_active_actor_required")
    if role == "admin" and not actor.admin:
        raise PermissionError("campaign_current_admin_required")
    if role == "publisher" and (
        authority.grant is None
        or not authority.grant.active
        or authority.grant.owner_id != actor_id
    ):
        raise PermissionError("campaign_current_publisher_required")
    if role == "publisher" and (
        authority.policy is None or not authority.policy.enabled
    ):
        raise PermissionError("campaign_current_policy_required")


async def open_write(repository, command, purpose, role, principal, session):
    await require_capabilities(repository, session)
    preflight = await repository.preflight(
        command.actor_id,
        getattr(command, "campaign_id", None),
        getattr(command, "submission_id", None),
        purpose=purpose,
        session=session,
    )
    context = await repository.prepare(
        preflight, principal=principal, session=session
    )
    if (
        not isinstance(context, CampaignWriteContext)
        or context.owner_session is not session
        or context.preflight.actor_id != command.actor_id
    ):
        raise ValueError("campaign_caller_transaction_required")
    authority = await repository.authority(
        command.actor_id, context=context, session=session
    )
    require_authority(authority, command.actor_id, principal, role)
    return context, authority


async def retained_result(repository, command, context, authority, session):
    receipt = await repository.command(
        command.actor_id,
        command.operation_key,
        context=context,
        session=session,
    )
    if receipt is None:
        return None
    if not isinstance(receipt, CampaignCommandReceipt) or (
        receipt.actor_id,
        receipt.operation_key,
    ) != (command.actor_id, command.operation_key):
        raise ValueError("campaign_receipt_unavailable")
    if receipt.payload_hash != command.payload_hash:
        raise CampaignConflict("campaign_operation_conflict")
    result = receipt.result.payload
    campaign_id = getattr(command, "campaign_id", None)
    if campaign_id is not None:
        current = await repository.state(
            campaign_id, context=context, session=session
        )
        if not isinstance(current, CampaignState):
            raise ValueError("campaign_state_unavailable")
        return {
            **result,
            "current_state": current.state,
            "current_version": current.version.campaign_version,
            "is_current": result.get("version")
            == current.version.campaign_version,
        }
    return {
        **result,
        "current_policy_version": authority.policy.stream_version
        if authority.policy
        else None,
    }


def ensure_scope(context, members, owner_id):
    required = {owner_id}
    for member in members:
        required.add(member.user_id)
        inviter = member.member["context"]["inviter"]
        if inviter:
            required.add(inviter["user_id"])
    if isinstance(context, CampaignWriteContext) and not required.issubset(
        context.preflight.user_ids
    ):
        raise CampaignConflict("campaign_scope_changed")


async def command_state(repository, command, context, session):
    state = await repository.state(
        command.campaign_id, context=context, session=session
    )
    if not isinstance(state, CampaignState):
        raise LookupError("campaign_draft_not_found")
    if state.version.campaign_version != command.expected_version:
        raise CampaignConflict("campaign_version_conflict")
    return state


def advance(state, name, submission_id=None):
    return replace(
        state,
        state=name,
        version=CampaignLifecycleVersion(
            state.version.campaign_version + 1, state.version.revision_version
        ),
        submission_id=submission_id or state.submission_id,
    )


async def commit_result(
    repository,
    command,
    context,
    session,
    at,
    result,
    *,
    states=(),
    submissions=(),
    decisions=(),
    jobs=(),
    capacity=None,
):
    if capacity is None:
        capacity = CampaignCapacityDelta()
    receipt = CampaignCommandReceipt(
        command.actor_id,
        command.operation_key,
        command.payload_hash,
        CampaignFrozenMap.from_mapping(result),
        utc(at),
    )
    await repository.apply(
        CampaignMutation(
            states, submissions, decisions, jobs, capacity, receipt
        ),
        context=context,
        session=session,
    )
    return result


@dataclass
class CampaignSubmissionService:
    repository: CampaignModerationRepository
    capacity: Any
    clock: Clock
    miniapp_url: str
    templates: CampaignMessageTemplates = CAMPAIGN_TEMPLATES
    access: CampaignAccess | None = None

    async def submit(
        self,
        command: SubmitCampaign,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
        session: object,
    ):
        if not isinstance(command, SubmitCampaign):
            raise ValueError("typed_campaign_submission_required")
        context, authority = await open_write(
            self.repository, command, "submit", "publisher", principal, session
        )
        replay = await retained_result(
            self.repository, command, context, authority, session
        )
        if replay is not None:
            return replay
        if self.access is not None:
            await self.access.require_access(
                command.actor_id,
                action="submit",
                at=utc(self.clock.now()),
                session=session,
            )
        if not callable(getattr(self.capacity, "admission", None)):
            raise ValueError("campaign_capacity_unavailable")
        state = await command_state(self.repository, command, context, session)
        if state.owner_id != command.actor_id:
            raise PermissionError("campaign_owner_required")
        if (
            state.state != "draft"
            or state.revision.revision_digest != command.revision_digest
        ):
            raise CampaignConflict("campaign_revision_changed")
        # open_write already validated the immutable publisher authority.
        policy = cast(CampaignPolicyFacts, authority.policy)
        grant = cast(CampaignGrantFacts, authority.grant)
        if (
            command.policy_version != policy.publication_version
            or command.terms_hash != policy.terms_hash
            or state.revision.policy_version != policy.publication_version
            or state.revision.terms_hash != policy.terms_hash
        ):
            raise CampaignConflict("campaign_terms_changed")
        state.revision.content.validate(policy.limits.payload)
        members = await self.repository.candidates(
            state.owner_id, context=context, session=session
        )
        ensure_scope(context, members, state.owner_id)
        selected = evaluate_audience(
            members,
            owner_id=state.owner_id,
            policy=policy,
            segment=state.revision.segment,
        ).selected
        if not selected:
            raise CampaignConflict("campaign_empty_audience")
        sender = await self.repository.sender_snapshot(
            state.owner_id, context=context, session=session
        )
        envelope = render_campaign_envelope(
            state.revision.content,
            campaign_id=state.campaign_id,
            sender_label=sender.label,
            sender_source=sender.source_fingerprint,
            default_locale=policy.default_locale,
            miniapp_url=self.miniapp_url,
            templates=self.templates,
        )
        observation, settlement = await self.capacity.admission(
            state.owner_id,
            tuple(row.scope for row in selected),
            policy,
            "submit",
            context=context,
            session=session,
        )
        if observation.reasons:
            raise CampaignConflict("campaign_capacity_exceeded")
        at = observation.observed_at
        submission_id = uuid5(
            NAMESPACE_URL,
            f"ugc:campaign-submission:{command.actor_id}:{command.operation_key}",
        )
        sources = tuple(
            sorted(
                (
                    CampaignSourceFacts(
                        uuid5(submission_id, str(row.user_id)), row, at
                    )
                    for row in selected
                ),
                key=lambda row: str(row.source_id),
            )
        )
        audience = CampaignAudience(
            tuple(
                CampaignSourceEvidence(
                    row.source_id, row.candidate.digest, row.candidate.digest
                )
                for row in sources
            )
        )
        seal = CampaignSubmissionSeal(
            submission_id,
            state.revision,
            grant.version,
            audience,
            envelope,
            at,
            at + timedelta(seconds=policy.limits["review_ttl_seconds"]),
        )
        current = advance(state, "submitted", submission_id)
        delta = settlement.capacity.plus(
            CampaignCapacityDelta(
                usage=(
                    CampaignUsage(
                        uuid5(submission_id, "accepted"),
                        "submission",
                        state.owner_id,
                        at,
                    ),
                ),
                opened=(
                    CampaignOccupation(
                        state.campaign_id, state.owner_id, seal.review_deadline
                    ),
                ),
            )
        )
        result = {
            **current.safe,
            "submission_id": str(submission_id),
            "submission_digest": seal.digest,
            "eligible_count": len(sources),
            "capacity": observation.safe,
        }
        return await commit_result(
            self.repository,
            command,
            context,
            session,
            at,
            result,
            states=settlement.states + (current,),
            submissions=(CampaignSubmissionRecord(seal, sources),),
            capacity=delta,
        )

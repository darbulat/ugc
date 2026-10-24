"""Dormant bounded quota/expiry plans in the caller's write bundle."""

from dataclasses import dataclass

from ugc_bot.application.campaign_moderation_ports import (
    CampaignExpiryBatch,
    CampaignModerationRepository,
    CampaignSettlement,
    CampaignWriteContext,
)
from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.services.campaign_submission_service import (
    advance,
    commit_result,
    open_write,
    retained_result,
)
from ugc_bot.domain.campaign_capacity import (
    CampaignCapacityDelta,
    CampaignCapacityFacts,
    CampaignOccupationClose,
    CampaignReservationRelease,
    apply_capacity_delta,
    evaluate_capacity,
)
from ugc_bot.domain.campaign_moderation import SettleCampaignExpiry
from ugc_bot.domain.campaigns import CampaignConflict
from ugc_bot.domain.financial import utc


def _check_context(context, session):
    if (
        not isinstance(context, CampaignWriteContext)
        or context.owner_session is not session
    ):
        raise ValueError("campaign_caller_transaction_required")


def _settlement(batch, facts, at, limit):
    if (
        not isinstance(batch, CampaignExpiryBatch)
        or len(batch.items) > limit
        or len({row.state.campaign_id for row in batch.items})
        != len(batch.items)
        or any(row.deadline > at for row in batch.items)
    ):
        raise ValueError("campaign_expiry_facts_unavailable")
    available = {
        row.reservation_id
        for row in facts.reservations
        if row.status == "reserved"
    }
    releases, closed, states = [], [], []
    for item in batch.items:
        if not set(item.reservation_ids).issubset(available):
            raise ValueError("campaign_expiry_facts_unavailable")
        releases.extend(
            CampaignReservationRelease(identifier, at, item.reason)
            for identifier in item.reservation_ids
        )
        if item.terminal:
            if item.state.state not in ("submitted", "approved_waiting"):
                raise ValueError("campaign_expiry_facts_unavailable")
            states.append(advance(item.state, "expired"))
            closed.append(
                CampaignOccupationClose(item.state.campaign_id, at, item.reason)
            )
    return CampaignSettlement(
        tuple(states),
        CampaignCapacityDelta(releases=tuple(releases), closed=tuple(closed)),
    )


@dataclass
class CampaignCapacityService:
    repository: CampaignModerationRepository
    clock: Clock

    async def _facts(self, owner_id, recipients, at, context, session):
        facts = await self.repository.capacity_facts(
            owner_id, recipients, at=at, context=context, session=session
        )
        if not isinstance(facts, CampaignCapacityFacts):
            raise ValueError("campaign_capacity_unavailable")
        return facts

    async def admission(
        self, owner_id, recipients, policy, intent, *, context, session
    ):
        _check_context(context, session)
        at = utc(self.clock.now())
        batch = await self.repository.due(
            at=at,
            limit=policy.limits["claim_batch_size"],
            context=context,
            session=session,
        )
        if not isinstance(batch, CampaignExpiryBatch):
            raise ValueError("campaign_capacity_unavailable")
        if batch.has_more:
            raise CampaignConflict("campaign_capacity_settlement_required")
        facts = await self._facts(owner_id, recipients, at, context, session)
        at = utc(self.clock.now())
        settlement = _settlement(
            batch, facts, at, policy.limits["claim_batch_size"]
        )
        adjusted = apply_capacity_delta(facts, settlement.capacity)
        observation = evaluate_capacity(
            adjusted,
            limits=policy.limits,
            owner_id=owner_id,
            recipients=recipients,
            at=at,
            intent=intent,
        )
        return observation, settlement

    async def observe(self, owner_id, recipients, policy, *, context, session):
        at = utc(self.clock.now())
        facts = await self._facts(owner_id, recipients, at, context, session)
        return evaluate_capacity(
            facts,
            limits=policy.limits,
            owner_id=owner_id,
            recipients=recipients,
            at=utc(self.clock.now()),
            intent="approve",
        )

    async def terminal(self, state, at, reason, *, context, session):
        _check_context(context, session)
        facts = await self._facts(state.owner_id, (), at, context, session)
        releases = tuple(
            CampaignReservationRelease(row.reservation_id, at, reason)
            for row in facts.reservations
            if row.campaign_id == state.campaign_id and row.status == "reserved"
        )
        return CampaignCapacityDelta(
            releases=releases,
            closed=(CampaignOccupationClose(state.campaign_id, at, reason),),
        )

    async def settle_expired(
        self, command: SettleCampaignExpiry, *, principal=None, session: object
    ):
        if not isinstance(command, SettleCampaignExpiry):
            raise ValueError("typed_campaign_expiry_required")
        context, authority = await open_write(
            self.repository, command, "settle", "admin", principal, session
        )
        replay = await retained_result(
            self.repository, command, context, authority, session
        )
        if replay is not None:
            return replay
        policy = authority.policy
        if policy is None:
            raise ValueError("campaign_current_policy_required")
        if policy.stream_version != command.expected_policy_version:
            raise CampaignConflict("campaign_policy_changed")
        at = utc(self.clock.now())
        batch = await self.repository.due(
            at=at,
            limit=policy.limits["claim_batch_size"],
            context=context,
            session=session,
        )
        facts = await self._facts(command.actor_id, (), at, context, session)
        at = utc(self.clock.now())
        settlement = _settlement(
            batch, facts, at, policy.limits["claim_batch_size"]
        )
        result = {"settled_count": len(batch.items), "has_more": batch.has_more}
        return await commit_result(
            self.repository,
            command,
            context,
            session,
            at,
            result,
            states=settlement.states,
            capacity=settlement.capacity,
        )

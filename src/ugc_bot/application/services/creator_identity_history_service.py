"""Count observed historical facts at the server's payment timestamp."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ugc_bot.application.identity_history_ports import (
    CreatorIdentityHistoryRepository,
)
from ugc_bot.domain.identity_history import (
    DirectBindingObservation,
    HistoricalDirectAttribution,
    IdentityHistoryCoverage,
    IdentityHistoryUnavailable,
    IdentityObservation,
    VerifiedCreatorCount,
    aware_utc,
)


def _require_coverage(
    coverage: IdentityHistoryCoverage | None,
    as_of: datetime,
    checked_at: datetime,
) -> IdentityHistoryCoverage:
    if (
        coverage is None
        or not coverage.complete
        or as_of < coverage.covered_from
        or as_of > checked_at
    ):
        raise IdentityHistoryUnavailable("identity_history_out_of_coverage")
    return coverage


@dataclass(slots=True)
class CreatorIdentityHistoryService:
    repository: CreatorIdentityHistoryRepository

    async def acquire_snapshot_barrier(self, *, session: object | None) -> None:
        """Call after all User/wallet/order locks, before final assessment.

        The caller must not acquire User/profile locks after this barrier.
        Ordinary discovery reads intentionally do not acquire this lock.
        """
        await self.repository.acquire_snapshot_barrier(session=session)

    async def resolve_direct_binding(
        self,
        referred_user_id: UUID,
        as_of: datetime,
        *,
        session: object | None = None,
    ) -> HistoricalDirectAttribution:
        as_of = aware_utc(as_of)
        inputs = await self.repository.read_direct_binding(
            referred_user_id, as_of, session=session
        )
        coverage = _require_coverage(inputs.coverage, as_of, inputs.checked_at)
        binding = inputs.binding
        reason = None
        recipient = None
        effective_at = None
        if binding is None:
            reason = "unbound"
        else:
            effective_at = max(binding.observed_at, binding.created_at)
            if not binding.active:
                reason = "revoked"
                effective_at = binding.observed_at
            elif effective_at > as_of:
                reason = "not_yet_effective"
            elif binding.referrer_user_id == referred_user_id:
                reason = "self_referral"
            elif binding.registered_at is None or binding.registered_at > as_of:
                raise IdentityHistoryUnavailable(
                    "identity_history_registration_unavailable"
                )
            else:
                recipient = binding.referrer_user_id
        return HistoricalDirectAttribution(
            referred_user_id=referred_user_id,
            referrer_user_id=recipient,
            as_of=as_of,
            registered_at=binding.registered_at if binding else None,
            binding_created_at=binding.created_at if binding else None,
            binding_effective_at=effective_at,
            observation_sequence=binding.sequence if binding else None,
            reason=reason,
            covered_from=coverage.covered_from,
            observed_through=inputs.checked_at,
            coverage_version=coverage.version,
        )

    async def count_verified_direct_creators(
        self,
        partner_user_id: UUID,
        as_of: datetime,
        *,
        session: object | None = None,
    ) -> VerifiedCreatorCount:
        as_of = aware_utc(as_of)
        inputs = await self.repository.read_network(
            partner_user_id, as_of, session=session
        )
        coverage = _require_coverage(inputs.coverage, as_of, inputs.checked_at)
        identities: dict[UUID, IdentityObservation] = {}
        for fact in inputs.identities:
            previous = identities.get(fact.creator_user_id)
            if fact.observed_at <= as_of and (
                previous is None
                or (fact.observed_at, fact.sequence)
                > (previous.observed_at, previous.sequence)
            ):
                identities[fact.creator_user_id] = fact
        bindings: dict[UUID, DirectBindingObservation] = {}
        for binding in inputs.bindings:
            previous_binding = bindings.get(binding.referred_user_id)
            if binding.observed_at <= as_of and (
                previous_binding is None
                or (binding.observed_at, binding.sequence)
                > (previous_binding.observed_at, previous_binding.sequence)
            ):
                bindings[binding.referred_user_id] = binding
        stable_ids = set()
        for creator_id, binding in bindings.items():
            identity = identities.get(creator_id)
            if (
                binding.active
                and creator_id != partner_user_id
                and binding.referrer_user_id == partner_user_id
                and binding.created_at <= as_of
                and identity is not None
                and identity.active
                and identity.instagram_user_id
            ):
                stable_ids.add(identity.instagram_user_id.strip())
        return VerifiedCreatorCount(
            partner_user_id,
            as_of,
            len(stable_ids),
            coverage.covered_from,
            inputs.checked_at,
            max(
                (
                    f.sequence
                    for f in inputs.identities
                    if f.observed_at <= as_of
                ),
                default=0,
            ),
            max(
                (b.sequence for b in inputs.bindings if b.observed_at <= as_of),
                default=0,
            ),
            coverage.version,
        )

"""In-memory canonical mutation observations with explicit cutover coverage."""

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from ugc_bot.application.identity_history_ports import current_identity_evidence
from ugc_bot.domain.entities import BloggerProfile, User, UserReferralBinding
from ugc_bot.domain.identity_history import (
    DirectBindingObservation,
    HistoricalBindingInputs,
    IdentityCountInputs,
    IdentityHistoryCoverage,
    IdentityObservation,
    aware_utc,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state(profile: BloggerProfile | None) -> tuple | None:
    if profile is None:
        return None
    return (
        profile.user_id,
        profile.confirmed,
        (profile.instagram_user_id or "").strip(),
        profile.instagram_url,
    )


@dataclass
class InMemoryCreatorIdentityHistoryRepository:
    clock: Callable[[], datetime] = _now
    _identity_observations: list[IdentityObservation] = field(
        default_factory=list
    )
    _binding_observations: list[DirectBindingObservation] = field(
        default_factory=list
    )
    _profile_seeds: int | None = None
    _binding_seeds: int | None = None
    _covered_from: datetime | None = None
    _registrations: dict[UUID, datetime | None] = field(default_factory=dict)

    async def acquire_snapshot_barrier(self, *, session: object | None) -> None:
        # Memory canonical writes/read projections do not yield mid-mutation.
        return None

    def observe_user(self, user: User) -> None:
        if user.user_id not in self._registrations:
            self._registrations[user.user_id] = (
                aware_utc(user.created_at)
                if user.created_at is not None
                and user.created_at.tzinfo is not None
                and user.created_at.utcoffset() is not None
                else None
            )

    @property
    def identity_observations(self) -> tuple[IdentityObservation, ...]:
        return tuple(self._identity_observations)

    @property
    def binding_observations(self) -> tuple[DirectBindingObservation, ...]:
        return tuple(self._binding_observations)

    def seed_profiles(self, profiles: Iterable[BloggerProfile]) -> None:
        if self._profile_seeds is not None:
            return
        profiles = tuple(profiles)
        now = aware_utc(self.clock())
        self._covered_from = max(self._covered_from or now, now)
        for profile in profiles:
            self._identity_observations.append(
                IdentityObservation(
                    len(self._identity_observations) + 1,
                    profile.user_id,
                    (profile.instagram_user_id or "").strip() or None,
                    profile.confirmed
                    and bool((profile.instagram_user_id or "").strip()),
                    now,
                    None,
                    "canonical_profile_cutover",
                    f"cutover-profile:{profile.user_id}",
                )
            )
        self._profile_seeds = len(profiles)

    def seed_bindings(self, bindings: Iterable[UserReferralBinding]) -> None:
        if self._binding_seeds is not None:
            return
        bindings = tuple(bindings)
        now = aware_utc(self.clock())
        self._covered_from = max(self._covered_from or now, now)
        for binding in bindings:
            self._binding_observations.append(
                DirectBindingObservation(
                    len(self._binding_observations) + 1,
                    binding.referrer_user_id,
                    binding.referred_user_id,
                    True,
                    binding.created_at,
                    now,
                    "direct_binding_cutover",
                    f"cutover-binding:{binding.referred_user_id}",
                    self._registrations.get(binding.referred_user_id),
                )
            )
        self._binding_seeds = len(bindings)

    def observe_profile(
        self, old: BloggerProfile | None, new: BloggerProfile | None
    ) -> None:
        evidence = current_identity_evidence()
        if _state(old) == _state(new) and evidence is None:
            return
        now = aware_utc(self.clock())
        if evidence is not None and evidence.fact_at > now:
            raise ValueError("identity_fact_time_in_future")
        source = (
            evidence.source
            if evidence is not None
            else "canonical_profile_observed"
        )
        old_id = (
            (old.instagram_user_id or "").strip() if old is not None else ""
        )
        new_id = (
            (new.instagram_user_id or "").strip() if new is not None else ""
        )
        changes = []
        if old is not None and (
            new is None or old.user_id != new.user_id or old_id != new_id
        ):
            changes.append((old.user_id, old_id or None, False, "revoke"))
        if new is not None:
            changes.append(
                (
                    new.user_id,
                    new_id or None,
                    new.confirmed and bool(new_id),
                    "current",
                )
            )
        candidates: list[IdentityObservation] = []
        for creator, instagram_id, active, phase in changes:
            prefix = (
                evidence.business_key
                if evidence is not None
                else str(len(self._identity_observations))
                + hashlib.sha256(
                    repr((_state(old), _state(new))).encode()
                ).hexdigest()
            )
            key = f"profile:{prefix}:{creator}:{phase}"
            existing = next(
                (
                    o
                    for o in self._identity_observations
                    if o.business_key == key
                ),
                None,
            )
            if existing is not None:
                if (
                    existing.creator_user_id,
                    existing.instagram_user_id,
                    existing.active,
                    existing.source,
                ) != (creator, instagram_id, active, source):
                    raise ValueError("identity_proof_replay_conflict")
                continue
            candidates.append(
                IdentityObservation(
                    len(self._identity_observations) + len(candidates) + 1,
                    creator,
                    instagram_id,
                    active,
                    now,
                    evidence.fact_at if evidence is not None else None,
                    source,
                    key,
                )
            )
        self._identity_observations.extend(candidates)

    def observe_binding(
        self, old: UserReferralBinding | None, new: UserReferralBinding | None
    ) -> None:
        if old == new:
            return
        now = aware_utc(self.clock())
        changes = []
        if old is not None:
            changes.append((old, False))
        if new is not None:
            changes.append((new, True))
        for binding, active in changes:
            sequence = len(self._binding_observations) + 1
            self._binding_observations.append(
                DirectBindingObservation(
                    sequence,
                    binding.referrer_user_id,
                    binding.referred_user_id,
                    active,
                    aware_utc(binding.created_at),
                    now,
                    "direct_binding_observed",
                    f"binding:{binding.referred_user_id}:{sequence}",
                    self._registrations.get(binding.referred_user_id),
                )
            )

    def _coverage(self) -> IdentityHistoryCoverage | None:
        coverage = None
        if (
            self._covered_from is not None
            and self._profile_seeds is not None
            and self._binding_seeds is not None
        ):
            complete = (
                sum(
                    o.source == "canonical_profile_cutover"
                    for o in self._identity_observations
                )
                == self._profile_seeds
                and sum(
                    o.source == "direct_binding_cutover"
                    for o in self._binding_observations
                )
                == self._binding_seeds
            )
            coverage = IdentityHistoryCoverage(self._covered_from, complete)
        return coverage

    async def read_direct_binding(
        self,
        referred_user_id: UUID,
        as_of: datetime,
        *,
        session: object | None = None,
    ) -> HistoricalBindingInputs:
        binding = max(
            (
                fact
                for fact in self._binding_observations
                if fact.referred_user_id == referred_user_id
                and fact.observed_at <= as_of
            ),
            key=lambda fact: (fact.observed_at, fact.sequence),
            default=None,
        )
        return HistoricalBindingInputs(
            self._coverage(), aware_utc(self.clock()), binding
        )

    async def read_network(
        self,
        partner_user_id: UUID,
        as_of: datetime,
        *,
        session: object | None = None,
    ) -> IdentityCountInputs:
        return IdentityCountInputs(
            self._coverage(),
            aware_utc(self.clock()),
            tuple(self._identity_observations),
            tuple(self._binding_observations),
        )

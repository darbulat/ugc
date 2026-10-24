"""Shared own-network consent/filter truth; legacy metrics remain unknown."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from ugc_bot.application.campaign_moderation_ports import (
    CampaignCandidateFacts,
    CampaignPolicyFacts,
    CampaignSourceFacts,
)
from ugc_bot.application.services.campaign_consent import (
    effective_consent_reason,
)
from ugc_bot.domain.campaign_moderation import (
    CampaignAudience,
    CampaignSourceEvidence,
)
from ugc_bot.domain.campaign_review import CampaignSegmentV1, token


def segment_reason(
    segment: CampaignSegmentV1, member: dict[str, Any]
) -> str | None:
    profile = member["profile"] or {}
    for name in ("country", "region", "city"):
        selected = getattr(segment, name)
        actual = profile.get(name)
        if selected is not None and (not actual or token(actual) != selected):
            return "segment_mismatch"
    topics = {
        token(value)
        for value in (profile.get("topics") or {}).get("selected", [])
        if isinstance(value, str) and value.strip()
    }
    if segment.topics_any and not topics.intersection(segment.topics_any):
        return "segment_mismatch"
    if (
        segment.profile_work_format is not None
        and profile.get("work_format") != segment.profile_work_format
    ):
        return "segment_mismatch"
    if segment.social is not None:
        account = next(
            (
                value
                for value in member["socials"]
                if value["platform"] == segment.social.platform
            ),
            None,
        )
        if segment.social.platform == "instagram":
            account = {"work_format": profile.get("work_format")}
        if account is None or (
            segment.social.work_format is not None
            and account["work_format"] != segment.social.work_format
        ):
            return "segment_mismatch"
        if segment.social.numeric:
            return "metric_unknown"
    return None


@dataclass(frozen=True, slots=True)
class CampaignEligibility:
    network_total: int
    selected: tuple[CampaignCandidateFacts, ...]
    exclusions: tuple[tuple[str, int], ...]
    member_reasons: tuple


def evaluate_audience(
    members: tuple[CampaignCandidateFacts | dict[str, Any], ...],
    *,
    owner_id: UUID,
    policy: CampaignPolicyFacts | dict[str, Any],
    segment: CampaignSegmentV1,
    at: datetime | None = None,
) -> CampaignEligibility:
    del at  # No admitted successful-observation writer exists in this phase.
    policy = policy.payload if hasattr(policy, "payload") else policy
    exclusions: Counter[str] = Counter()
    seen, selected, reasons = set(), [], []
    reason: str | None
    for supplied in members:
        member = (
            supplied.member
            if isinstance(supplied, CampaignCandidateFacts)
            else supplied
        )
        context = member["context"]
        identifier = context["actor"]["user_id"]
        if identifier in seen:
            continue
        seen.add(identifier)
        if identifier == owner_id:
            reason = "self"
        elif (
            context["inviter"] is None
            or context["inviter"]["user_id"] != owner_id
        ):
            reason = "foreign_network"
        else:
            reason = effective_consent_reason(
                context,
                policy,
                member["publisher"],
                member["consent"],
                member["receipt"],
            )
        reason = reason or segment_reason(segment, member)
        if reason:
            exclusions[reason] += 1
            reasons.append((identifier, reason))
        else:
            selected.append(
                supplied
                if isinstance(supplied, CampaignCandidateFacts)
                else CampaignCandidateFacts.from_member(member)
            )
    identities = Counter(value.scope.canonical_identity for value in selected)
    if any(count > 1 for count in identities.values()):
        raise ValueError("campaign_audience_integrity_unavailable")
    destinations = Counter(value.scope.destination for value in selected)
    survivors = []
    for member in selected:
        if destinations[member.scope.destination] > 1:
            exclusions["duplicate_destination"] += 1
            reasons.append((member.user_id, "duplicate_destination"))
        else:
            survivors.append(member)
    return CampaignEligibility(
        len(seen),
        tuple(survivors),
        tuple(sorted(exclusions.items())),
        tuple(reasons),
    )


def revalidate_sources(
    sources: tuple[CampaignSourceFacts, ...],
    current: tuple[CampaignCandidateFacts, ...],
    *,
    owner_id: UUID,
    policy: CampaignPolicyFacts,
    segment: CampaignSegmentV1,
    at: datetime,
) -> tuple[CampaignEligibility, CampaignAudience]:
    evaluated = evaluate_audience(
        current, owner_id=owner_id, policy=policy, segment=segment, at=at
    )
    members = {row.user_id: row for row in evaluated.selected}
    reasons = dict(evaluated.member_reasons)
    exclusions: Counter[str] = Counter()
    selected, evidence = [], []
    for source in sources:
        member = members.get(source.candidate.user_id)
        if member is None:
            exclusions[
                reasons.get(source.candidate.user_id, "source_missing")
            ] += 1
        elif member.source_key != source.candidate.source_key:
            exclusions["source_changed"] += 1
        else:
            selected.append(member)
            evidence.append(
                CampaignSourceEvidence(
                    source.source_id, source.candidate.digest, member.digest
                )
            )
    return CampaignEligibility(
        len(sources), tuple(selected), tuple(sorted(exclusions.items())), ()
    ), CampaignAudience(
        tuple(sorted(evidence, key=lambda row: str(row.source_id)))
    )

"""Own consenting network aggregates; metric success is never inferred."""

from dataclasses import dataclass
from uuid import UUID

from ugc_bot.application.campaign_ports import CampaignRepository
from ugc_bot.application.campaign_review_ports import CampaignReviewRepository
from ugc_bot.application.services.campaign_eligibility import evaluate_audience
from ugc_bot.application.services.campaign_eligibility import (
    segment_reason as segment_reason,
)
from ugc_bot.application.services.campaign_review_service import (
    require_publisher,
)
from ugc_bot.domain.campaign_review import CampaignSegmentV1
from ugc_bot.domain.campaigns import CampaignConflict, digest
from ugc_bot.domain.financial import utc


@dataclass
class CampaignAudienceService:
    repository: CampaignReviewRepository
    foundation: CampaignRepository

    async def preview(
        self,
        actor_id: UUID,
        campaign_id: UUID,
        revision_digest: str,
        *,
        session: object,
    ):
        at = await self.foundation.begin_snapshot(session=session)
        policy, grant = await require_publisher(
            self.foundation, actor_id, lock=False, session=session
        )
        row = await self.repository.draft(
            actor_id, campaign_id, session=session
        )
        if row is None:
            raise LookupError("campaign_draft_not_found")
        if (
            row["revision_digest"] != revision_digest
            or row["policy_version"] != policy["publication_version"]
            or row["terms_hash"] != policy["terms_hash"]
        ):
            raise CampaignConflict("campaign_preview_changed")
        segment = CampaignSegmentV1.parse(row["segment"])
        members = tuple(
            [
                member
                async for member in self.repository.candidates(
                    actor_id, session=session
                )
            ]
        )
        evaluated = evaluate_audience(
            members, owner_id=actor_id, policy=policy, segment=segment
        )
        count = len(evaluated.selected)
        result = {
            "campaign_id": str(campaign_id),
            "revision_digest": revision_digest,
            "policy_version": policy["publication_version"],
            "grant_version": grant["version"],
            "as_of": utc(at).isoformat(),
            "network_total": evaluated.network_total,
            "eligible_count": count,
            "exclusions": dict(evaluated.exclusions),
            "recipients_per_campaign": policy["limits"][
                "recipients_per_campaign"
            ],
            "within_campaign_limit": count
            <= policy["limits"]["recipients_per_campaign"],
            "metric_capability": "successful_observation_unavailable",
            "submission_state": "not_implemented",
        }
        return {**result, "preview_fingerprint": digest(result)}

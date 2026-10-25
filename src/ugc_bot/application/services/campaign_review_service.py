"""Own immutable draft revisions, separate from submission and moderation."""

from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from ugc_bot.application.campaign_ports import CampaignRepository
from ugc_bot.application.campaign_review_ports import CampaignReviewRepository
from ugc_bot.application.financial_ports import Clock
from ugc_bot.domain.campaign_review import SaveCampaignDraft
from ugc_bot.domain.campaigns import CampaignConflict, digest
from ugc_bot.domain.financial import utc


async def require_publisher(foundation, actor_id, *, lock, session):
    context = await foundation.context(actor_id, lock=lock, session=session)
    grant = await foundation.current("publisher", actor_id, session=session)
    policy = await foundation.current("policy", session=session)
    if (
        context["actor"]["status"] != "active"
        or not grant
        or not grant["active"]
    ):
        raise PermissionError("campaign_current_publisher_required")
    if policy is None or not policy["enabled"]:
        raise PermissionError("campaign_current_policy_required")
    return policy, grant


def draft_view(row):
    return {
        "campaign_id": str(row["campaign_id"]),
        "version": row["version"],
        "revision_digest": row["revision_digest"],
        "state": row.get("state", "draft"),
        "content": row["content"],
        "segment": row["segment"],
        "policy_version": row["policy_version"],
        "terms_hash": row["terms_hash"],
        "recorded_at": utc(row["recorded_at"]).isoformat(),
        "submission_state": "not_implemented",
    }


@dataclass
class CampaignReviewService:
    repository: CampaignReviewRepository
    foundation: CampaignRepository
    clock: Clock

    async def save_draft(self, command: SaveCampaignDraft, *, session: object):
        if not isinstance(command, SaveCampaignDraft):
            raise ValueError("typed_campaign_draft_required")
        policy, grant = await require_publisher(
            self.foundation, command.actor_id, lock=True, session=session
        )
        if (
            command.policy_version != policy["publication_version"]
            or command.terms_hash != policy["terms_hash"]
        ):
            raise CampaignConflict("campaign_terms_changed")
        command.content.validate(policy["limits"])
        previous = await self.repository.command(
            command.actor_id, command.operation_key, session=session
        )
        if previous:
            if previous["payload_hash"] != command.payload_hash:
                raise CampaignConflict("campaign_operation_conflict")
            result = previous["result"]
            current = await self.repository.draft(
                command.actor_id, UUID(result["campaign_id"]), session=session
            )
            return {
                **result,
                "is_current": bool(
                    current and current["version"] == result["version"]
                ),
            }
        identifier = command.campaign_id or uuid5(
            NAMESPACE_URL,
            f"ugc:campaign-draft:{command.actor_id}:{command.operation_key}",
        )
        current = await self.repository.draft(
            command.actor_id, identifier, session=session
        )
        if command.campaign_id is not None and current is None:
            raise LookupError("campaign_draft_not_found")
        version = current["version"] if current else 0
        if version != command.expected_version:
            raise CampaignConflict("campaign_version_conflict")
        values = {
            "campaign_id": identifier,
            "owner_id": command.actor_id,
            "version": version + 1,
            "content": command.content.payload,
            "segment": command.segment.payload,
            "policy_version": command.policy_version,
            "terms_hash": command.terms_hash,
            "grant_version": grant["version"],
            "recorded_at": utc(self.clock.now()),
            "operation_key": command.operation_key,
        }
        values["revision_digest"] = digest(
            {
                "schema": "campaign-draft-v1",
                "owner_id": str(command.actor_id),
                "campaign_id": str(identifier),
                "version": version + 1,
                "content": command.content.payload,
                "segment": command.segment.payload,
                "policy_version": command.policy_version,
                "terms_hash": command.terms_hash,
            }
        )
        result = {**draft_view(values), "is_current": True}
        await self.repository.save(
            values,
            {
                "actor_id": command.actor_id,
                "operation_key": command.operation_key,
                "payload_hash": command.payload_hash,
                "result": result,
                "recorded_at": values["recorded_at"],
            },
            session=session,
        )
        return result

    async def detail(
        self, actor_id: UUID, campaign_id: UUID, *, session: object
    ):
        at = await self.foundation.begin_snapshot(session=session)
        await self.foundation.context(actor_id, lock=False, session=session)
        row = await self.repository.draft(
            actor_id, campaign_id, session=session
        )
        if row is None:
            raise LookupError("campaign_draft_not_found")
        return {**draft_view(row), "as_of": utc(at).isoformat()}

    async def list_drafts(self, actor_id: UUID, page: int, *, session: object):
        if type(page) is not int or not 0 <= page <= 100000:
            raise ValueError("campaign_invalid_page")
        at = await self.foundation.begin_snapshot(session=session)
        await self.foundation.context(actor_id, lock=False, session=session)
        rows = await self.repository.list_drafts(
            actor_id, page, session=session
        )
        return {
            "drafts": [draft_view(row) for row in rows[:25]],
            "page": page,
            "has_more": len(rows) > 25,
            "as_of": utc(at).isoformat(),
        }

    async def operation_status(
        self, actor_id: UUID, operation_key: str, *, session: object
    ):
        if (
            not isinstance(operation_key, str)
            or not operation_key.strip()
            or len(operation_key) > 256
        ):
            raise ValueError("campaign_request_invalid")
        at = await self.foundation.begin_snapshot(session=session)
        await self.foundation.context(actor_id, lock=False, session=session)
        receipt = await self.repository.command(
            actor_id, operation_key, session=session
        )
        status = {
            "operation_key": operation_key,
            "recorded": receipt is not None,
            "as_of": utc(at).isoformat(),
        }
        if receipt is None:
            return status
        original = receipt["result"]
        current = await self.repository.draft(
            actor_id, UUID(original["campaign_id"]), session=session
        )
        if current is None:
            raise ValueError("campaign_drafts_unavailable")
        current_view = draft_view(current)
        # Only the same own-draft DTO crosses the private read boundary.
        original_view = {key: original[key] for key in current_view}
        original_view["is_current"] = original["is_current"]
        return {
            **status,
            "original_result": original_view,
            "current": current_view,
            "is_current": original["version"] == current["version"]
            and original["revision_digest"] == current["revision_digest"],
        }

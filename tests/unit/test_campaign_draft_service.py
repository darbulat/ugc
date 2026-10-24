"""Saved drafts and aggregate previews imply no moderation or delivery."""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from tests.unit.test_campaign_consent_epochs import (
    CREATOR,
    OWNER,
    context,
)
from ugc_bot.domain.campaigns import LIMIT_NAMES, CampaignConflict, digest

AT = datetime(2026, 10, 24, tzinfo=timezone.utc)


class Foundation:
    def __init__(self):
        self.policy = {
            "version": 1,
            "publication_version": 1,
            "enabled": True,
            "terms_version": "v1",
            "terms_hash": "a" * 64,
            "limits": dict.fromkeys(LIMIT_NAMES, 100),
        }
        self.grant = {"active": True, "version": 1}

    async def begin_snapshot(self, *, session):
        return AT

    async def context(self, actor_id, *, lock, session):
        return {"actor": {"user_id": actor_id, "status": "active"}}

    async def current(self, stream, subject=None, *, session):
        return self.policy if stream == "policy" else self.grant


class Drafts:
    def __init__(self):
        self.rows = {}
        self.commands = {}
        self.members = []

    async def draft(self, owner_id, campaign_id, *, session):
        value = self.rows.get(campaign_id)
        return (
            deepcopy(value) if value and value["owner_id"] == owner_id else None
        )

    async def command(self, actor_id, key, *, session):
        return deepcopy(self.commands.get((actor_id, key)))

    async def save(self, values, receipt, *, session):
        self.rows[values["campaign_id"]] = deepcopy(values)
        self.commands[receipt["actor_id"], receipt["operation_key"]] = deepcopy(
            receipt
        )

    async def list_drafts(self, owner_id, page, *, session):
        return [
            deepcopy(row)
            for row in self.rows.values()
            if row["owner_id"] == owner_id
        ]

    async def candidates(self, owner_id, *, session):
        for value in self.members:
            yield value


def make_service():
    from ugc_bot.application.services.campaign_review_service import (
        CampaignReviewService,
    )

    return CampaignReviewService(
        Drafts(), Foundation(), SimpleNamespace(now=lambda: AT)
    )


def save_command(
    *, key="draft-create", campaign_id=None, version=0, segment=None
):
    from ugc_bot.domain.campaign_review import SaveCampaignDraft

    return SaveCampaignDraft.parse(
        OWNER,
        {
            "operation_key": key,
            "expected_version": version,
            "campaign_id": str(campaign_id) if campaign_id else None,
            "policy_version": 1,
            "terms_hash": "a" * 64,
            "content": {"title": "Task", "text": "Exact task"},
            "segment": segment or {},
        },
    )


def candidate(
    *,
    user=CREATOR,
    destination="101",
    consent=True,
    identity="real-ig-identity",
):
    ctx = context()
    ctx["actor"]["user_id"] = user
    ctx["actor"]["telegram_id"] = destination
    ctx["canonical_identity"] = identity
    grant = {"active": True}
    event = {
        "version": 1,
        "active": consent,
        "actor_id": user,
        "creator_id": user,
        "owner_id": OWNER,
        "canonical_identity": identity,
        "binding_created_at": AT,
        "policy_version": 1,
        "terms_version": "v1",
        "terms_hash": "a" * 64,
        "operation_key": "allow",
    }
    receipt = {
        "actor_id": user,
        "operation_key": "allow",
        "action": "consent",
        "result": {
            "consent_context": digest(
                {
                    "purpose": "umc:campaign-consent-context:v1",
                    "actor_id": str(user),
                    "owner_id": str(OWNER),
                    "canonical_identity": identity,
                    "binding_created_at": "2026-10-24T00:00:00+00:00",
                    "binding_sequence": 1,
                }
            )
        },
    }
    return {
        "context": ctx,
        "consent": event,
        "receipt": receipt,
        "publisher": grant,
        "profile": {
            "city": "Moscow",
            "country": "russia",
            "topics": {"selected": ["beauty"]},
            "work_format": "ugc_only",
        },
        "socials": [],
    }


@pytest.mark.asyncio
async def test_draft_save_replay_and_read_are_actor_scoped_and_versioned():
    service = make_service()
    first = await service.save_draft(save_command(), session=object())
    assert first["version"] == 1 and first["state"] == "draft"
    replay = await service.save_draft(save_command(), session=object())
    assert replay["campaign_id"] == first["campaign_id"]
    assert len(service.repository.rows) == 1
    identifier = UUID(first["campaign_id"])
    detail = await service.detail(OWNER, identifier, session=object())
    assert detail["content"] == {"title": "Task", "text": "Exact task"}
    with pytest.raises(LookupError):
        await service.detail(UUID(int=999), identifier, session=object())
    await service.save_draft(
        save_command(key="edit", campaign_id=identifier, version=1),
        session=object(),
    )
    with pytest.raises(CampaignConflict):
        await service.save_draft(
            save_command(key="stale", campaign_id=identifier, version=1),
            session=object(),
        )
    service.foundation.grant["active"] = False
    with pytest.raises(PermissionError):
        await service.save_draft(save_command(), session=object())
    assert (await service.detail(OWNER, identifier, session=object()))[
        "version"
    ] == 2


@pytest.mark.asyncio
async def test_preview_is_aggregate_and_numeric_metrics_stay_unknown():
    from ugc_bot.application.services.campaign_audience_service import (
        CampaignAudienceService,
    )

    service = make_service()
    result = await service.save_draft(
        save_command(
            segment={"social": {"platform": "instagram", "followers_min": 0}}
        ),
        session=object(),
    )
    service.repository.members = [
        candidate(),
        candidate(user=UUID(int=9), consent=False),
    ]
    audience = CampaignAudienceService(service.repository, service.foundation)
    preview = await audience.preview(
        OWNER,
        UUID(result["campaign_id"]),
        result["revision_digest"],
        session=object(),
    )
    assert preview["network_total"] == 2 and preview["eligible_count"] == 0
    assert preview["exclusions"] == {"metric_unknown": 1, "consent_absent": 1}
    assert "telegram_id" not in str(preview) and "101" not in str(preview)
    assert (
        len(service.repository.rows) == 1
        and len(service.repository.commands) == 1
    )
    with pytest.raises(CampaignConflict):
        await audience.preview(
            OWNER, UUID(result["campaign_id"]), "0" * 64, session=object()
        )


@pytest.mark.asyncio
async def test_preview_excludes_both_alias_destinations_without_exposing_them():
    from ugc_bot.application.services.campaign_audience_service import (
        CampaignAudienceService,
    )

    service = make_service()
    result = await service.save_draft(save_command(), session=object())
    first = candidate(destination="00101")
    service.repository.members = [
        first,
        deepcopy(first),
        candidate(user=UUID(int=9), identity="other-ig", destination="101"),
    ]
    audience = CampaignAudienceService(service.repository, service.foundation)
    preview = await audience.preview(
        OWNER,
        UUID(result["campaign_id"]),
        result["revision_digest"],
        session=object(),
    )
    assert preview["network_total"] == 2
    assert preview["eligible_count"] == 0
    assert preview["exclusions"] == {"duplicate_destination": 2}
    service.repository.members[2] = candidate(
        user=UUID(int=9), destination="202"
    )
    with pytest.raises(ValueError, match="integrity_unavailable"):
        await audience.preview(
            OWNER,
            UUID(result["campaign_id"]),
            result["revision_digest"],
            session=object(),
        )


@pytest.mark.parametrize(
    "segment,wanted",
    [
        ({}, None),
        (
            {"country": "russia", "city": "moscow", "topics_any": ["beauty"]},
            None,
        ),
        ({"city": "other"}, "segment_mismatch"),
        ({"region": "missing"}, "segment_mismatch"),
        ({"topics_any": ["travel"]}, "segment_mismatch"),
        ({"profile_work_format": "ads_in_account"}, "segment_mismatch"),
        ({"social": {"platform": "youtube"}}, "segment_mismatch"),
        (
            {"social": {"platform": "instagram", "work_format": "ugc_only"}},
            None,
        ),
        (
            {
                "social": {
                    "platform": "instagram",
                    "work_format": "ads_in_account",
                }
            },
            "segment_mismatch",
        ),
        (
            {"social": {"platform": "instagram", "followers_max": 0}},
            "metric_unknown",
        ),
    ],
)
def test_existing_filter_semantics_and_missing_metrics_are_explicit(
    segment, wanted
):
    from ugc_bot.application.services.campaign_audience_service import (
        segment_reason,
    )
    from ugc_bot.domain.campaign_review import CampaignSegmentV1

    member = candidate()
    member["socials"] = [
        {
            "platform": "vk",
            "work_format": "ads_in_account",
            "followers_count": 999999,
            "metrics_source": "caller-supplied",
            "metrics_fetched_at": AT,
        }
    ]
    assert segment_reason(CampaignSegmentV1.parse(segment), member) == wanted
    assert (
        segment_reason(
            CampaignSegmentV1.parse(
                {"social": {"platform": "vk", "followers_min": 0}}
            ),
            member,
        )
        == "metric_unknown"
    )


@pytest.mark.asyncio
async def test_key_conflict_and_replay_preserve_new_revision():
    from dataclasses import replace

    service = make_service()
    first = await service.save_draft(save_command(), session=object())
    edit = save_command(
        key="edit", campaign_id=UUID(first["campaign_id"]), version=1
    )
    await service.save_draft(edit, session=object())
    replay = await service.save_draft(save_command(), session=object())
    assert replay["version"] == 1 and not replay["is_current"]
    with pytest.raises(CampaignConflict, match="operation_conflict"):
        await service.save_draft(
            replace(edit, expected_version=2), session=object()
        )
    with pytest.raises(LookupError):
        await service.save_draft(
            save_command(key="foreign", campaign_id=UUID(int=999)),
            session=object(),
        )
    service.foundation.policy["enabled"] = False
    with pytest.raises(PermissionError):
        await service.save_draft(save_command(), session=object())


@pytest.mark.asyncio
async def test_foundation_settings_uses_same_epoch_predicate_as_audience():
    from ugc_bot.application.services.campaign_service import (
        CampaignFoundationService,
    )

    member = candidate()
    member["context"]["binding_sequence"] = 9
    member["context"]["binding_witness_sequences"] = (9,)
    foundation = Foundation()
    foundation.policy.update(
        default_locale="ru", terms={"ru": "Exact terms"}, recorded_at=AT
    )

    async def ctx(actor_id, **kwargs):
        return member["context"]

    async def current(stream, subject=None, **kwargs):
        return (
            member["consent"]
            if stream == "consent"
            else foundation.policy
            if stream == "policy"
            else foundation.grant
        )

    async def receipt(*args, **kwargs):
        return member["receipt"]

    foundation.context, foundation.current, foundation.receipt = (
        ctx,
        current,
        receipt,
    )
    member["context"]["actor"]["admin"] = False
    member["context"]["inviter"]["label"] = "Safe owner"
    result = await CampaignFoundationService(
        foundation, SimpleNamespace(now=lambda: AT)
    ).view(CREATOR, session=object())
    assert not result["consent"]["effective"] and result["can_consent"]
    assert result["consent_effective_reason"] == "consent_binding_changed"


@pytest.mark.asyncio
async def test_preview_rejects_missing_draft_and_excludes_self_and_foreign():
    from ugc_bot.application.services.campaign_audience_service import (
        CampaignAudienceService,
    )

    service = make_service()
    audience = CampaignAudienceService(service.repository, service.foundation)
    with pytest.raises(LookupError, match="draft_not_found"):
        await audience.preview(OWNER, UUID(int=999), "a" * 64, session=object())
    result = await service.save_draft(save_command(), session=object())
    foreign = candidate(user=UUID(int=9))
    foreign["context"]["inviter"]["user_id"] = UUID(int=8)
    service.repository.members = [candidate(user=OWNER), foreign]
    preview = await audience.preview(
        OWNER,
        UUID(result["campaign_id"]),
        result["revision_digest"],
        session=object(),
    )
    assert preview["eligible_count"] == 0
    assert preview["exclusions"] == {"self": 1, "foreign_network": 1}


@pytest.mark.asyncio
async def test_internal_save_and_list_reject_untyped_or_ambiguous_intent():
    service = make_service()
    with pytest.raises(ValueError, match="typed_campaign_draft_required"):
        await service.save_draft({"actor": "forged"}, session=object())
    for page in (True, -1, 100001):
        with pytest.raises(ValueError, match="invalid_page"):
            await service.list_drafts(OWNER, page, session=object())

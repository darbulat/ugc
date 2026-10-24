"""Independent pure reproductions; these establish no SQL provenance."""

from dataclasses import replace

import pytest

from tests.unit.test_campaign_moderation_service import reviewing
from tests.unit.test_campaign_submission_service import ADMIN, SESSION
from ugc_bot.domain.campaign_review import CampaignDraftContent
from ugc_bot.domain.campaigns import digest


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["detail", "approve"])
async def test_source_review_refuses_current_revision_different_from_seal(
    boundary,
):
    repository, service, _, intent = await reviewing()
    state = repository.states[intent.campaign_id]
    content = CampaignDraftContent("Different retained title", "Different text")
    payload = {**state.revision.payload, "content": content.payload}
    changed = replace(
        state.revision,
        content=content,
        revision_digest=digest(payload),
    )
    repository.states[intent.campaign_id] = replace(state, revision=changed)
    sealed = repository.submissions[intent.submission_id].seal
    assert changed != sealed.revision
    assert changed.revision_version == sealed.revision.revision_version

    if boundary == "detail":
        with pytest.raises(ValueError):
            await service.review_detail(
                ADMIN, intent.submission_id, session=SESSION
            )
    else:
        with pytest.raises(ValueError):
            detail = await service.review_detail(
                ADMIN, intent.submission_id, session=SESSION
            )
            await service.decide(
                replace(
                    intent,
                    revision_digest=changed.revision_digest,
                    review_context=detail["review_context"],
                ),
                session=SESSION,
            )
    assert len(repository.writes) == 1
    assert not repository.jobs and not repository.decisions


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked", ["policy", "grant"])
async def test_source_admin_can_reject_after_publisher_authority_revoked(
    revoked,
):
    repository, service, _, intent = await reviewing()
    if revoked == "policy":
        repository.policy = replace(
            repository.policy, enabled=False, stream_version=3
        )
    else:
        repository.grant = replace(repository.grant, active=False, version=5)
    detail = await service.review_detail(
        ADMIN, intent.submission_id, session=SESSION
    )
    result = await service.decide(
        replace(
            intent, decision="reject", review_context=detail["review_context"]
        ),
        session=SESSION,
    )
    assert result["state"] == "rejected"
    assert not repository.jobs and not repository.facts.occupations
    assert len(repository.facts.usage) == 1

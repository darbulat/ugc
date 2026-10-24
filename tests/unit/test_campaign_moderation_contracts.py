"""Dormant moderation contracts retain exact intent and sealed evidence."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from ugc_bot.domain.campaign_review import (
    CampaignDraftContent,
    CampaignSegmentV1,
)
from ugc_bot.domain.campaigns import digest

ACTOR = UUID(int=11)
CAMPAIGN = UUID(int=12)
SUBMISSION = UUID(int=13)
REVIEWER = UUID(int=14)
AT = datetime(2026, 10, 24, tzinfo=timezone.utc)


def intent_payload(action):
    common = {"operation_key": "synthetic-key"}
    if action == "settle":
        return {**common, "expected_policy_version": 2, "reason": " Review "}
    common.update(campaign_id=str(CAMPAIGN), expected_version=3)
    if action == "cancel":
        return {**common, "reason": " Review "}
    common["revision_digest"] = "a" * 64
    if action == "submit":
        return {**common, "policy_version": 2, "terms_hash": "b" * 64}
    return {
        **common,
        "submission_id": str(SUBMISSION),
        "review_context": "c" * 64,
        "decision": "approve",
        "reason": " Review ",
    }


def command_type(action):
    from ugc_bot.domain.campaign_moderation import (
        CancelCampaign,
        ReviewCampaign,
        SettleCampaignExpiry,
        SubmitCampaign,
    )

    return {
        "submit": SubmitCampaign,
        "review": ReviewCampaign,
        "cancel": CancelCampaign,
        "settle": SettleCampaignExpiry,
    }[action]


@pytest.mark.parametrize("action", ["submit", "review", "cancel", "settle"])
def test_intents_are_typed_frozen_and_native_proof_is_not_intent(action):
    cls = command_type(action)
    command = cls.parse(ACTOR, intent_payload(action))
    assert command.actor_id == ACTOR
    if action != "settle":
        assert command.campaign_id == CAMPAIGN
    if action != "submit":
        assert command.reason == "Review"
    with pytest.raises(FrozenInstanceError):
        command.operation_key = "replaced"
    assert (
        command.payload_hash == replace(command, actor_id=REVIEWER).payload_hash
    )
    assert (
        command.payload_hash
        != replace(command, operation_key="another-key").payload_hash
    )
    assert "actor_id" not in command.payload
    for private in ("native", "external_id", "platform", "principal"):
        assert private not in command.payload


@pytest.mark.parametrize("action", ["submit", "review", "cancel", "settle"])
@pytest.mark.parametrize(
    "extra",
    [
        {"owner_id": str(REVIEWER)},
        {"recipient_ids": [str(REVIEWER)]},
        {"is_admin": True},
        {"address": "private"},
        {"platform": "telegram"},
        {"as_of": AT.isoformat()},
    ],
)
def test_intent_parsers_reject_targeting_authority_and_clock_overrides(
    action, extra
):
    with pytest.raises(ValueError, match="campaign_"):
        command_type(action).parse(ACTOR, {**intent_payload(action), **extra})


@pytest.mark.parametrize("action", ["submit", "review", "cancel", "settle"])
@pytest.mark.parametrize("bad", [True, 0, -1, "3", None])
def test_intents_require_strict_positive_expected_versions(action, bad):
    key = (
        "expected_policy_version" if action == "settle" else "expected_version"
    )
    with pytest.raises(ValueError):
        command_type(action).parse(ACTOR, {**intent_payload(action), key: bad})


@pytest.mark.parametrize(
    "change",
    [
        {"campaign_id": str(UUID(int=0))},
        {"campaign_id": 12},
        {"campaign_id": "not a UUID"},
        {"operation_key": " "},
        {"operation_key": "x" * 257},
        {"policy_version": True},
        {"terms_hash": "A" * 64},
        {"revision_digest": "f" * 63},
    ],
)
def test_submission_intent_rejects_invalid_references(change):
    with pytest.raises(ValueError):
        command_type("submit").parse(
            ACTOR, {**intent_payload("submit"), **change}
        )


def test_command_hashes_bind_each_intent_value_without_native_or_actor_fields():
    submit = command_type("submit").parse(ACTOR, intent_payload("submit"))
    assert submit.payload == {
        "action": "submit",
        "operation_key": "synthetic-key",
        "campaign_id": str(CAMPAIGN),
        "expected_version": 3,
        "revision_digest": "a" * 64,
        "policy_version": 2,
        "terms_hash": "b" * 64,
    }
    for changes in (
        {"campaign_id": REVIEWER},
        {"expected_version": 4},
        {"revision_digest": "d" * 64},
        {"policy_version": 3},
        {"terms_hash": "d" * 64},
    ):
        assert replace(submit, **changes).payload_hash != submit.payload_hash
    review = command_type("review").parse(REVIEWER, intent_payload("review"))
    for changes in (
        {"submission_id": ACTOR},
        {"review_context": "d" * 64},
        {"decision": "reject"},
        {"reason": "Different decision"},
    ):
        assert replace(review, **changes).payload_hash != review.payload_hash
    for action in ("cancel", "settle"):
        value = command_type(action).parse(ACTOR, intent_payload(action))
        assert replace(value, reason="Other").payload_hash != value.payload_hash


@pytest.mark.parametrize(
    "action,change",
    [
        ("review", {"decision": "automatic"}),
        ("review", {"submission_id": str(UUID(int=0))}),
        ("review", {"review_context": None}),
        ("cancel", {"reason": " "}),
        ("settle", {"reason": "x" * 1001}),
    ],
)
def test_review_cancel_and_expiry_require_exact_explicit_intent(action, change):
    with pytest.raises(ValueError):
        command_type(action).parse(ACTOR, {**intent_payload(action), **change})


def revision():
    from ugc_bot.domain.campaign_moderation import CampaignRevision

    content = CampaignDraftContent(
        "Task", "Exact text", "https://product.example/x"
    )
    segment = CampaignSegmentV1.parse({"city": "Орёл"})
    return CampaignRevision(
        owner_id=ACTOR,
        campaign_id=CAMPAIGN,
        revision_version=3,
        policy_version=2,
        terms_hash="b" * 64,
        content=content,
        segment=segment,
        revision_digest=digest(
            {
                "schema": "campaign-draft-v1",
                "owner_id": str(ACTOR),
                "campaign_id": str(CAMPAIGN),
                "version": 3,
                "content": content.payload,
                "segment": segment.payload,
                "policy_version": 2,
                "terms_hash": "b" * 64,
            }
        ),
    )


def audience(*ids, current="a" * 64):
    from ugc_bot.domain.campaign_moderation import (
        CampaignAudience,
        CampaignSourceEvidence,
    )

    return CampaignAudience(
        tuple(
            CampaignSourceEvidence(UUID(int=i), "a" * 64, current) for i in ids
        )
    )


def seal():
    from ugc_bot.application.campaign_message_templates import (
        render_campaign_envelope,
    )
    from ugc_bot.domain.campaign_moderation import CampaignSubmissionSeal

    value = revision()
    envelope = render_campaign_envelope(
        value.content,
        campaign_id=CAMPAIGN,
        sender_label="Synthetic inviter",
        sender_source="advertiser-brand:synthetic-row",
        default_locale="ru",
        miniapp_url="https://app.example/miniapp/app.html",
    )
    return CampaignSubmissionSeal(
        SUBMISSION,
        value,
        4,
        audience(21, 22),
        envelope,
        AT,
        AT + timedelta(seconds=10),
    )


def context():
    from ugc_bot.domain.campaign_moderation import (
        CampaignLifecycleVersion,
        CampaignReviewContext,
    )

    return CampaignReviewContext(
        seal(),
        CampaignLifecycleVersion(4, 3),
        REVIEWER,
        2,
        4,
        audience(21),
        "c" * 64,
    )


def test_lifecycle_versions_do_not_reinterpret_accepted_revision_hash():
    from ugc_bot.domain.campaign_moderation import CampaignLifecycleVersion

    value = revision()
    state = CampaignLifecycleVersion(4, 3)
    assert replace(state, campaign_version=5).revision_version == 3
    assert value.revision_digest == revision().revision_digest
    for changes in (
        {"revision_digest": "f" * 64},
        {"content": {"title": "mutable"}},
        {"segment": {"city": "mutable"}},
        {"revision_version": 4},
    ):
        with pytest.raises(ValueError):
            replace(value, **changes)
    for versions in ((True, 1), (0, 0), (2, 3)):
        with pytest.raises(ValueError):
            CampaignLifecycleVersion(*versions)


def test_audience_hash_binds_exact_source_ids_and_both_evidence_versions():
    first = audience(21, 22)
    assert first.digest != audience(21, 23).digest
    assert first.digest != audience(21, 22, current="b" * 64).digest
    exposed = first.payload
    exposed["sources"][0]["source_id"] = str(ACTOR)
    assert first.payload["sources"][0]["source_id"] == str(UUID(int=21))
    for sources in (
        list(first.sources),
        first.sources[::-1],
        (first.sources[0],) * 2,
    ):
        with pytest.raises(ValueError):
            replace(first, sources=sources)


def test_submission_seal_binds_exact_revision_source_envelope_facts():
    from ugc_bot.application.campaign_message_templates import (
        render_campaign_envelope,
    )

    value = seal()
    foreign_envelope = render_campaign_envelope(
        value.revision.content,
        campaign_id=ACTOR,
        sender_label="Synthetic inviter",
        sender_source="advertiser-brand:synthetic-row",
        default_locale="ru",
        miniapp_url="https://app.example/miniapp/app.html",
    )
    assert value.envelope.campaign_id == value.revision.campaign_id
    assert value.digest != replace(value, grant_version=5).digest
    assert value.digest != replace(value, audience=audience(21)).digest
    assert (
        value.digest
        != replace(
            value, envelope=replace(value.envelope, template_version="changed")
        ).digest
    )
    for changes in (
        {"submission_id": UUID(int=0)},
        {"audience": audience()},
        {"audience": audience(21, current="b" * 64)},
        {"review_deadline": AT},
        {"submitted_at": AT.replace(tzinfo=None)},
        {"envelope": foreign_envelope},
    ):
        with pytest.raises(ValueError):
            replace(value, **changes)
    with pytest.raises(FrozenInstanceError):
        value.grant_version = 99


def test_review_context_binds_members_capacity_versions_and_each_locale():
    value = context()
    for changes in (
        {"audience": audience(22)},
        {"audience": audience(21, current="b" * 64)},
        {"capacity_digest": "d" * 64},
        {"policy_stream_version": 3},
        {"grant_stream_version": 5},
        {"reviewer_id": UUID(int=15)},
    ):
        assert replace(value, **changes).digest != value.digest
    for locale in value.submission.envelope.locales:
        locales = tuple(
            replace(row, text=row.text + "!")
            if row.locale == locale.locale
            else row
            for row in value.submission.envelope.locales
        )
        changed = replace(value.submission.envelope, locales=locales)
        assert (
            replace(
                value, submission=replace(value.submission, envelope=changed)
            ).digest
            != value.digest
        )
    assert "as_of" not in value.payload
    assert "external_id" not in value.payload
    for changes in (
        {"reviewer_id": ACTOR},
        {"audience": audience(23)},
        {
            "audience": replace(
                audience(21),
                sources=(
                    replace(audience(21).sources[0], submitted_digest="b" * 64),
                ),
            )
        },
        {"capacity_digest": "not-proof"},
        {"version": replace(value.version, revision_version=2)},
    ):
        with pytest.raises(ValueError):
            replace(value, **changes)


def test_template_catalog_uses_renderer_five_locales_and_native_uuid():
    from ugc_bot.application.campaign_message_templates import (
        CAMPAIGN_TEMPLATES,
        render_campaign_envelope,
    )
    from ugc_bot.domain.campaign_envelope import CampaignEnvelopeV1

    value = seal().envelope
    assert isinstance(value, CampaignEnvelopeV1)
    assert {row.locale for row in value.locales} == {
        "ru",
        "en",
        "kk",
        "be",
        "uz",
    }
    assert value.template_digest == CAMPAIGN_TEMPLATES.digest
    for locale in value.locales:
        assert "Exact text" in locale.text
        assert (
            locale.action_url
            == f"https://app.example/miniapp/app.html?campaign={CAMPAIGN}"
        )
        assert locale.payload["parse_mode"] is None
    copied = CAMPAIGN_TEMPLATES.payload
    copied["ru"] = ("forged", "forged")
    assert CAMPAIGN_TEMPLATES.payload["ru"] != copied["ru"]
    for changes in (
        {"entries": list(CAMPAIGN_TEMPLATES.entries)},
        {"entries": CAMPAIGN_TEMPLATES.entries[:4]},
        {"entries": (CAMPAIGN_TEMPLATES.entries[0],) * 5},
        {"version": " "},
    ):
        with pytest.raises(ValueError):
            replace(CAMPAIGN_TEMPLATES, **changes)
    with pytest.raises(ValueError, match="technical_message"):
        render_campaign_envelope(
            CampaignDraftContent("Task", "🙂" * 2048),
            campaign_id=CAMPAIGN,
            sender_label="Synthetic",
            sender_source="synthetic-source",
            default_locale="ru",
            miniapp_url="https://app.example/miniapp/app.html",
        )


def test_context_records_retain_immutable_complete_scope_tokens():
    from ugc_bot.application.campaign_moderation_ports import (
        CampaignPreflight,
        CampaignReadContext,
        CampaignWriteContext,
    )

    preflight = CampaignPreflight(ACTOR, (ACTOR, CAMPAIGN), "submit", CAMPAIGN)
    write = CampaignWriteContext(preflight, object(), object())
    read = CampaignReadContext(ACTOR, AT)
    assert write.preflight.user_ids == (ACTOR, CAMPAIGN)
    assert read.as_of == AT
    with pytest.raises(FrozenInstanceError):
        preflight.user_ids = (ACTOR,)
    for changes in (
        {"user_ids": (CAMPAIGN,)},
        {"user_ids": [ACTOR]},
        {"user_ids": (CAMPAIGN, ACTOR)},
        {"purpose": "send"},
    ):
        with pytest.raises(ValueError):
            replace(preflight, **changes)
    with pytest.raises(ValueError):
        replace(write, owner_session=None)
    with pytest.raises(ValueError):
        replace(read, as_of=AT.replace(tzinfo=None))


@pytest.mark.asyncio
async def test_service_fact_records_refuse_mutable_or_inconsistent_evidence():
    from tests.unit.test_campaign_submission_service import OWNER, submitted
    from ugc_bot.application.campaign_moderation_ports import (
        CampaignActorFacts,
        CampaignAuthority,
        CampaignCandidateFacts,
        CampaignCapabilities,
        CampaignCommandReceipt,
        CampaignDecisionFacts,
        CampaignDeliveryJob,
        CampaignExpiryBatch,
        CampaignExpiryItem,
        CampaignFrozenMap,
        CampaignGrantFacts,
        CampaignMutation,
        CampaignPreflight,
        CampaignSenderSnapshot,
        CampaignSettlement,
        CampaignSourceFacts,
        CampaignSubmissionRecord,
    )
    from ugc_bot.domain.campaign_capacity import (
        CampaignCapacityDelta,
        evaluate_capacity,
    )

    repository, _, _, _ = await submitted()
    state = next(iter(repository.states.values()))
    record = next(iter(repository.submissions.values()))
    receipt = next(iter(repository.receipts.values()))
    actor = CampaignActorFacts(OWNER, "active", False, "101", None)
    authority = CampaignAuthority(actor, repository.policy, repository.grant)
    observation = evaluate_capacity(
        repository.facts,
        limits=repository.policy.limits,
        owner_id=OWNER,
        recipients=(),
        at=AT,
        intent="observe",
    )
    source = record.sources[0]
    for construct in (
        lambda: CampaignFrozenMap([]),
        lambda: CampaignFrozenMap((("a", 1), ("a", 2))),
        lambda: CampaignFrozenMap((("a", []),)),
        lambda: CampaignFrozenMap.from_mapping([]),
        lambda: CampaignFrozenMap.from_mapping({"unknown": object()}),
        lambda: CampaignCandidateFacts({}),
        lambda: replace(actor, admin=1),
        lambda: replace(repository.policy, default_locale="de"),
        lambda: CampaignGrantFacts(OWNER, 1, 1),
        lambda: replace(authority, actor=None),
        lambda: CampaignCapabilities(True, 1, True),
        lambda: replace(state, state="delivered"),
        lambda: CampaignSourceFacts(source.source_id, {}, AT),
        lambda: CampaignSubmissionRecord(record.seal, []),
        lambda: CampaignSubmissionRecord(
            record.seal, (replace(source, source_id=UUID(int=800)),)
        ),
        lambda: CampaignSenderSnapshot(" ", "source"),
        lambda: replace(receipt, result={}),
        lambda: CampaignDecisionFacts(
            UUID(int=900), context(), "unknown", "Synthetic", AT, None
        ),
        lambda: CampaignDecisionFacts(
            UUID(int=900), context(), "approve", "Synthetic", AT, None
        ),
        lambda: CampaignDecisionFacts(
            UUID(int=900), context(), "approve", "Synthetic", AT, AT
        ),
        lambda: CampaignDeliveryJob(
            UUID(int=0),
            CAMPAIGN,
            SUBMISSION,
            REVIEWER,
            ACTOR,
            "a" * 64,
            "b" * 64,
            "c" * 64,
            1,
            AT,
        ),
        lambda: CampaignExpiryItem(state, [], True, AT, "Expired"),
        lambda: CampaignExpiryBatch([], False),
        lambda: CampaignSettlement([], CampaignCapacityDelta()),
        lambda: CampaignMutation(
            [], (), (), (), CampaignCapacityDelta(), receipt
        ),
        lambda: CampaignMutation((), (), (), (), None, receipt),
        lambda: CampaignPreflight(OWNER, (OWNER,), "submit"),
        lambda: replace(observation, summary=[]),
    ):
        with pytest.raises(ValueError):
            construct()
    # Every detached mapping can change independently of its retained evidence.
    before = source.candidate.digest
    exposed = source.candidate.member
    exposed["context"]["actor"]["telegram_id"] = "changed"
    assert source.candidate.digest == before
    assert isinstance(receipt, CampaignCommandReceipt)

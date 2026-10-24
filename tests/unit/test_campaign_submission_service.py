"""Synthetic orchestration facts prove no SQL, provenance or atomicity."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest

from tests.unit.test_campaign_draft_service import AT, Foundation, candidate
from tests.unit.test_campaign_moderation_contracts import revision
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.domain.campaign_moderation import (
    CampaignLifecycleVersion,
    SubmitCampaign,
)

OWNER = UUID(int=11)
ADMIN = UUID(int=81)
SESSION = object()


class SyntheticCampaignRepository:
    """Synthetic adapter with no SQL, real locks, transactions or provider."""

    def __init__(self):
        from ugc_bot.application.campaign_moderation_ports import (
            CampaignActorFacts,
            CampaignCandidateFacts,
            CampaignCapabilities,
            CampaignGrantFacts,
            CampaignPolicyFacts,
            CampaignState,
        )
        from ugc_bot.domain.campaign_capacity import CampaignCapacityFacts

        published = Foundation().policy
        published.update(
            publication_version=2,
            version=2,
            terms_hash="b" * 64,
            default_locale="ru",
        )
        published["limits"].update(
            recipients_per_campaign=3,
            window_seconds=60,
            recipient_cooldown_seconds=30,
            claim_batch_size=2,
        )
        self.policy = CampaignPolicyFacts.from_mapping(published)
        self.grant = CampaignGrantFacts(OWNER, 4, True)
        self.actor_type = CampaignActorFacts
        self.ready = CampaignCapabilities(True, True, True)
        self.at = AT
        self.active, self.native_changed = True, False
        self.admins = {ADMIN}
        self.states = {
            revision().campaign_id: CampaignState(
                revision(), CampaignLifecycleVersion(3, 3), "draft"
            )
        }
        self.members = []
        member = candidate()
        member["profile"]["city"] = "Орёл"
        member["context"]["inviter"]["user_id"] = OWNER
        member["consent"].update(
            owner_id=OWNER, policy_version=2, terms_hash="b" * 64
        )
        from ugc_bot.application.services.campaign_consent import (
            consent_context,
        )

        member["receipt"]["result"]["consent_context"] = consent_context(
            member["context"]
        )
        self.members.append(CampaignCandidateFacts.from_member(member))
        self.receipts, self.submissions, self.decisions, self.jobs = (
            {},
            {},
            {},
            {},
        )
        self.facts = CampaignCapacityFacts((), (), ())
        self.expiry = []
        self.trace, self.writes = [], []
        self.fail_apply = False

    async def capabilities(self, *, session):
        self.trace.append("capabilities")
        return self.ready

    async def preflight(
        self, actor_id, campaign_id, submission_id, *, purpose, session
    ):
        from ugc_bot.application.campaign_moderation_ports import (
            CampaignPreflight,
        )

        self.trace.append("preflight")
        users = {actor_id, OWNER} | {member.user_id for member in self.members}
        return CampaignPreflight(
            actor_id,
            tuple(sorted(users, key=str)),
            purpose,
            campaign_id,
            submission_id,
        )

    async def prepare(self, preflight, *, principal, session):
        from ugc_bot.application.campaign_moderation_ports import (
            CampaignWriteContext,
        )

        self.trace.append("prepare")
        return CampaignWriteContext(preflight, session, object())

    async def begin_read(self, actor_id, *, principal, session):
        from ugc_bot.application.campaign_moderation_ports import (
            CampaignReadContext,
        )

        self.trace.append("snapshot")
        return CampaignReadContext(actor_id, self.at)

    async def authority(self, actor_id, *, context, session):
        from ugc_bot.application.campaign_moderation_ports import (
            CampaignAuthority,
        )

        self.trace.append("authority")
        actor = self.actor_type(
            actor_id,
            "active" if self.active else "pause",
            actor_id in self.admins,
            "changed" if self.native_changed else "101",
            "101",
        )
        return CampaignAuthority(
            actor, self.policy, self.grant if actor_id == OWNER else None
        )

    async def command(self, actor_id, operation_key, *, context, session):
        self.trace.append("receipt")
        return self.receipts.get((actor_id, operation_key))

    async def state(self, campaign_id, *, context, session):
        self.trace.append("state")
        return self.states.get(campaign_id)

    async def candidates(self, owner_id, *, context, session):
        self.trace.append("candidates")
        return tuple(self.members)

    async def publisher(self, owner_id, *, context, session):
        return self.grant

    async def sender_snapshot(self, owner_id, *, context, session):
        from ugc_bot.application.campaign_moderation_ports import (
            CampaignSenderSnapshot,
        )

        self.trace.append("sender")
        return CampaignSenderSnapshot("Synthetic sender", "synthetic-brand-row")

    async def submission(self, submission_id, *, context, session):
        return self.submissions.get(submission_id)

    async def capacity_facts(
        self, owner_id, recipients, *, at, context, session
    ):
        self.trace.append("capacity")
        return self.facts

    async def due(self, *, at, limit, context, session):
        from ugc_bot.application.campaign_moderation_ports import (
            CampaignExpiryBatch,
        )

        self.trace.append("due")
        return CampaignExpiryBatch(
            tuple(self.expiry[:limit]), len(self.expiry) > limit
        )

    async def review_page(self, page, *, context, session):
        return tuple(self.submissions.values())[page * 25 : page * 25 + 26]

    async def apply(self, write, *, context, session):
        from ugc_bot.domain.campaign_capacity import apply_capacity_delta

        assert session is SESSION and context.owner_session is SESSION
        self.trace.append("apply")
        if self.fail_apply:
            raise RuntimeError("synthetic persistence refusal")
        self.writes.append(write)
        self.receipts[write.receipt.actor_id, write.receipt.operation_key] = (
            write.receipt
        )
        self.states.update({state.campaign_id: state for state in write.states})
        self.submissions.update(
            {row.seal.submission_id: row for row in write.submissions}
        )
        self.decisions.update({row.review_id: row for row in write.decisions})
        self.jobs.update({row.job_id: row for row in write.jobs})
        self.facts = apply_capacity_delta(self.facts, write.capacity)
        settled = {row.campaign_id for row in write.states}
        released = {row.reservation_id for row in write.capacity.releases}
        self.expiry = [
            row
            for row in self.expiry
            if row.state.campaign_id not in settled
            and not (
                row.reservation_ids and set(row.reservation_ids) <= released
            )
        ]


def environment():
    from ugc_bot.application.services.campaign_capacity_service import (
        CampaignCapacityService,
    )
    from ugc_bot.application.services.campaign_submission_service import (
        CampaignSubmissionService,
    )

    repository = SyntheticCampaignRepository()
    clock = SimpleNamespace(now=lambda: repository.at)
    capacity = CampaignCapacityService(repository, clock)
    service = CampaignSubmissionService(
        repository, capacity, clock, "https://app.example/miniapp/app.html"
    )
    return repository, service, capacity


def command(key="submit"):
    value = revision()
    return SubmitCampaign(
        OWNER, key, value.campaign_id, 3, value.revision_digest, 2, "b" * 64
    )


def add_member(repository, number):
    from ugc_bot.application.campaign_moderation_ports import (
        CampaignCandidateFacts,
    )
    from ugc_bot.application.services.campaign_consent import consent_context

    member = candidate(
        user=UUID(int=number),
        identity=f"synthetic-ig-{number}",
        destination=str(1000 + number),
    )
    member["profile"]["city"] = "Орёл"
    member["context"]["inviter"]["user_id"] = OWNER
    member["consent"].update(
        owner_id=OWNER, policy_version=2, terms_hash="b" * 64
    )
    member["receipt"]["result"]["consent_context"] = consent_context(
        member["context"]
    )
    repository.members.append(CampaignCandidateFacts.from_member(member))


def revision_for(*, owner=OWNER, campaign=None):
    from ugc_bot.domain.campaigns import digest

    value = revision()
    campaign = campaign or value.campaign_id
    return replace(
        value,
        owner_id=owner,
        campaign_id=campaign,
        revision_digest=digest(
            {
                **value.payload,
                "owner_id": str(owner),
                "campaign_id": str(campaign),
            }
        ),
    )


async def submitted():
    repository, service, capacity = environment()
    result = await service.submit(command(), session=SESSION)
    return repository, service, capacity, result


@pytest.mark.asyncio
async def test_submit_seals_sources_locales_usage_in_one_intended_write():
    repository, service, _ = environment()
    result = await service.submit(command(), session=SESSION)
    assert result["state"] == "submitted" and result["eligible_count"] == 1
    assert (
        len(repository.writes)
        == len(repository.submissions)
        == len(repository.facts.usage)
        == 1
    )
    sealed = next(iter(repository.submissions.values()))
    assert len(sealed.seal.envelope.locales) == 5
    assert sealed.seal.revision.revision_digest == revision().revision_digest
    assert (
        repository.trace.index("prepare")
        < repository.trace.index("authority")
        < repository.trace.index("receipt")
        < repository.trace.index("candidates")
    )
    assert "telegram" not in str(result) and "101" not in str(result)


@pytest.mark.asyncio
async def test_native_remap_plus_over_cap_denies_before_private_admission():
    repository, service, _ = environment()
    repository.native_changed = True
    repository.policy = replace(
        repository.policy,
        limits=repository.policy.limits.with_values(recipients_per_campaign=1),
    )
    for number in range(500, 504):
        add_member(repository, number)
    assert (
        len({row.user_id for row in repository.members})
        > repository.policy.limits["recipients_per_campaign"]
    )
    proof = AuthenticatedMessengerPrincipal(OWNER, "telegram", "101")
    with pytest.raises(PermissionError, match="^campaign_principal_changed$"):
        await service.submit(command(), principal=proof, session=SESSION)
    assert (
        "receipt" not in repository.trace
        and "candidates" not in repository.trace
    )
    assert not repository.writes


@pytest.mark.asyncio
async def test_accepted_replay_after_growth_retains_result_and_fresh_state():
    repository, service, _, accepted = await submitted()
    state = repository.states[command().campaign_id]
    repository.states[state.campaign_id] = replace(
        state, state="cancelled", version=CampaignLifecycleVersion(5, 3)
    )
    for number in range(500, 504):
        add_member(repository, number)
    repository.trace.clear()
    replay = await service.submit(command(), session=SESSION)
    assert {key: replay[key] for key in accepted} == accepted
    assert (
        replay["current_state"] == "cancelled"
        and replay["current_version"] == 5
    )
    assert (
        "candidates" not in repository.trace
        and "capacity" not in repository.trace
        and len(repository.writes) == 1
    )
    with pytest.raises(ValueError, match="operation_conflict"):
        await service.submit(
            replace(command(), expected_version=4), session=SESSION
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "empty",
        "over_cap",
        "version",
        "terms",
        "grant",
        "policy",
        "uninstalled",
        "no_session",
        "apply",
    ],
)
async def test_submission_refusals_have_no_partial_intended_effect(failure):
    repository, service, _ = environment()
    intent, session = command(), SESSION
    if failure == "empty":
        repository.members.clear()
    elif failure == "over_cap":
        from ugc_bot.application.campaign_moderation_ports import (
            CampaignCandidateFacts,
        )

        raw = repository.members[0].member
        other = candidate(
            user=UUID(int=500), identity="other-ig", destination="202"
        )
        other["profile"]["city"] = "Орёл"
        other["context"]["inviter"] = raw["context"]["inviter"]
        other["consent"].update(
            owner_id=OWNER, policy_version=2, terms_hash="b" * 64
        )
        from ugc_bot.application.services.campaign_consent import (
            consent_context,
        )

        other["receipt"]["result"]["consent_context"] = consent_context(
            other["context"]
        )
        repository.members.append(CampaignCandidateFacts.from_member(other))
        repository.policy = replace(
            repository.policy,
            limits=repository.policy.limits.with_values(
                recipients_per_campaign=1
            ),
        )
    elif failure == "version":
        intent = replace(intent, expected_version=2)
    elif failure == "terms":
        intent = replace(intent, terms_hash="c" * 64)
    elif failure == "grant":
        repository.grant = replace(repository.grant, active=False)
    elif failure == "policy":
        repository.policy = replace(repository.policy, enabled=False)
    elif failure == "uninstalled":
        repository.ready = replace(repository.ready, persistence=False)
    elif failure == "no_session":
        session = None
    else:
        repository.fail_apply = True
    with pytest.raises((ValueError, PermissionError, RuntimeError)):
        await service.submit(intent, session=session)
    assert (
        not repository.writes
        and not repository.receipts
        and not repository.submissions
    )


def test_shared_eligibility_retains_epoch_metric_and_dedup_rules():
    from ugc_bot.application.services.campaign_eligibility import (
        evaluate_audience,
    )
    from ugc_bot.domain.campaign_review import CampaignSegmentV1

    member = candidate()
    policy = Foundation().policy
    selected = evaluate_audience(
        (member,),
        owner_id=member["context"]["inviter"]["user_id"],
        policy=policy,
        segment=CampaignSegmentV1(),
    )
    assert selected.network_total == len(selected.selected) == 1
    numeric = evaluate_audience(
        (member,),
        owner_id=member["context"]["inviter"]["user_id"],
        policy=policy,
        segment=CampaignSegmentV1.parse(
            {"social": {"platform": "instagram", "followers_min": 0}}
        ),
    )
    assert numeric.exclusions == (("metric_unknown", 1),)


@pytest.mark.asyncio
async def test_missing_capacity_service_is_unavailable_after_receipt():
    repository, service, _ = environment()
    service.capacity = None
    with pytest.raises(ValueError, match="^campaign_capacity_unavailable$"):
        await service.submit(command(), session=SESSION)
    assert "receipt" in repository.trace and not repository.writes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "untyped",
        "inactive",
        "foreign",
        "missing_state",
        "not_draft",
        "bad_context",
        "missing_authority",
        "corrupt_receipt",
        "scope_change",
        "missing_repository",
    ],
)
async def test_context_and_scope_refusals_precede_intended_write(failure):
    repository, service, _ = environment()
    intent = command()
    if failure == "untyped":
        intent = {}
    elif failure == "inactive":
        repository.active = False
    elif failure == "foreign":
        state = repository.states[intent.campaign_id]
        repository.states[intent.campaign_id] = replace(
            state, revision=revision_for(owner=ADMIN)
        )
    elif failure == "missing_state":
        repository.states.clear()
    elif failure == "not_draft":
        state = repository.states[intent.campaign_id]
        repository.states[intent.campaign_id] = replace(
            state, state="submitted"
        )
    elif failure == "bad_context":

        async def bad(*args, **kwargs):
            return object()

        repository.prepare = bad
    elif failure == "missing_authority":

        async def missing(*args, **kwargs):
            return None

        repository.authority = missing
    elif failure == "corrupt_receipt":
        repository.receipts[OWNER, intent.operation_key] = object()
    elif failure == "scope_change":
        original = repository.prepare

        async def changed(*args, **kwargs):
            result = await original(*args, **kwargs)
            add_member(repository, 501)
            return result

        repository.prepare = changed
    else:
        service.repository = object()
    with pytest.raises((ValueError, PermissionError, LookupError)):
        await service.submit(intent, session=SESSION)
    assert not repository.writes


@pytest.mark.asyncio
async def test_grant_loss_blocks_replay_and_missing_history_is_unavailable():
    repository, service, _, _ = await submitted()
    repository.grant = replace(repository.grant, active=False)
    repository.trace.clear()
    with pytest.raises(PermissionError):
        await service.submit(command(), session=SESSION)
    assert "receipt" not in repository.trace
    repository.grant = replace(repository.grant, active=True)
    repository.states.clear()
    with pytest.raises(ValueError, match="state_unavailable"):
        await service.submit(command(), session=SESSION)
    assert len(repository.writes) == 1

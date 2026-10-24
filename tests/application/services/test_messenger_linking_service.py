"""Attach-only state transitions, lost replies and truthful current views."""

import base64
import copy
import importlib
import importlib.util
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import SecretStr

from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.domain.messenger_linking import MaxLinkActor, NativeLinkProposal

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


class Transactions:
    def __init__(self, repo):
        self.repo = repo
        self.fail = False

    @asynccontextmanager
    async def transaction(self):
        before = copy.deepcopy(self.repo.__dict__)
        try:
            yield object()
            if self.fail:
                raise RuntimeError("synthetic commit failure")
        except Exception:
            self.repo.__dict__.clear()
            self.repo.__dict__.update(before)
            raise


class Clock:
    value = NOW

    def now(self):
        return self.value


def setup(*, enabled=True, tokens=True):
    module = "ugc_bot.application.services.messenger_linking_service"
    assert importlib.util.find_spec(module) is not None, (
        "linking service missing"
    )
    service_cls = importlib.import_module(module).MessengerLinkingService
    repo_cls = importlib.import_module(
        "ugc_bot.infrastructure.memory_messenger_linking"
    ).MemoryMessengerLinkingRepository
    from ugc_bot.domain.messenger_linking import LinkScope
    from ugc_bot.infrastructure.messenger.link_tokens import LinkTokens

    actor = MaxLinkActor(UUID(int=100), "12345")
    user = User(
        actor.user_id,
        MessengerType.MAX,
        "max_client",
        UserStatus.ACTIVE,
        0,
        NOW,
        max_id=actor.external_id,
        max_chat_id="actual-chat",
        country="RU",
        language="en",
        admin=True,
    )
    repo = repo_cls({actor.user_id: user}, {actor.user_id})
    tm = Transactions(repo)
    scope = LinkScope(123, "synthetic_test_bot", "test-1", "a" * 64)
    crypto = (
        LinkTokens(
            SecretStr(base64.urlsafe_b64encode(b"s" * 32).decode().rstrip("=")),
            scope,
        )
        if tokens
        else None
    )
    clock = Clock()
    return service_cls(repo, tm, crypto, enabled, clock), repo, actor, tm, clock


def native(view, *, sender="777", source="100"):
    token = view.launch_url.split("start=", 1)[1]
    return NativeLinkProposal(
        123, sender, source, "50", NOW, token, "<TG Name>", "tg_name"
    )


@pytest.mark.asyncio
async def test_only_explicit_max_confirmation_attaches_telegram():
    service, repo, actor, _, _ = setup()
    before = repo.users[actor.user_id]
    view = await service.create(actor, "issue")
    assert view.state == "waiting" and view.can_revoke and not view.can_confirm
    receipt = await service.propose_native(native(view))
    assert receipt.state == "proposed"
    assert repo.users[actor.user_id] == before and len(repo.users) == 1
    proposed = await service.status(actor)
    assert proposed.telegram_identity == {
        "id": "777",
        "display_name": "<TG Name>",
        "username": "tg_name",
    }
    assert proposed.can_confirm
    linked = await service.confirm(
        actor,
        proposed.challenge_id,
        receipt.claim_id,
        proposed.version,
        "confirm",
    )
    assert linked.state == "linked" and linked.launch_url is None
    assert repo.users[actor.user_id] == replace(before, telegram_id="777")
    assert len(repo.users) == 1


@pytest.mark.asyncio
async def test_issue_replay_and_reopen_preserve_one_safe_challenge():
    service, repo, actor, _, _ = setup()
    first = await service.create(actor, "issue")
    replay = await service.create(actor, "issue")
    other = await service.create(actor, "different-click")
    assert first.launch_url == replay.launch_url == other.launch_url
    assert len(repo.challenges) == 1
    assert "lk1_" not in repr(repo.commands) + repr(repo.challenges)


@pytest.mark.asyncio
async def test_separate_canonical_telegram_user_never_merges_even_if_empty():
    service, repo, actor, _, _ = setup()
    view = await service.create(actor, "issue")
    repo.users[UUID(int=200)] = replace(
        repo.users[actor.user_id],
        user_id=UUID(int=200),
        max_id=None,
        telegram_id="777",
    )
    before = copy.deepcopy(repo.users)
    receipt = await service.propose_native(native(view))
    assert receipt.state == "conflict"
    assert repo.users == before
    assert (await service.status(actor)).state == "conflict"


@pytest.mark.asyncio
async def test_consumed_replay_does_not_proclaim_former_pair():
    service, repo, actor, _, _ = setup()
    view = await service.create(actor, "issue")
    receipt = await service.propose_native(native(view))
    proposed = await service.status(actor)
    await service.confirm(
        actor,
        proposed.challenge_id,
        receipt.claim_id,
        proposed.version,
        "confirm",
    )
    repo.users[actor.user_id] = replace(
        repo.users[actor.user_id], telegram_id="888"
    )
    replay = await service.confirm(
        actor,
        proposed.challenge_id,
        receipt.claim_id,
        proposed.version,
        "confirm",
    )
    assert replay.receipt.state == "linked"
    assert replay.state == "identity_changed" and replay.launch_url is None


@pytest.mark.asyncio
async def test_owner_remap_refuses_live_url_or_attachment():
    service, repo, actor, _, _ = setup()
    view = await service.create(actor, "issue")
    repo.users[actor.user_id] = replace(repo.users[actor.user_id], max_id=None)
    with pytest.raises(PermissionError, match="messenger_identity_changed"):
        await service.status(actor)
    assert repo.users[actor.user_id].telegram_id is None
    assert view.launch_url


@pytest.mark.asyncio
async def test_disabled_capability_preserves_safe_read_replay_and_revoke_only():
    service, repo, actor, _, _ = setup()
    waiting = await service.create(actor, "issue")
    service.enabled = False
    replay = await service.create(actor, "issue")
    assert replay.receipt == waiting.receipt and replay.launch_url is None
    assert not replay.can_create and not replay.can_confirm
    receipt = await service.propose_native(native(waiting))
    assert receipt.state == "unavailable" and not repo.claims
    revoked = await service.revoke(
        actor, waiting.challenge_id, waiting.version, "revoke"
    )
    assert revoked.state == "revoked"
    blocked = await service.create(actor, "new")
    assert blocked.state == "unavailable" and len(repo.challenges) == 1


@pytest.mark.asyncio
async def test_expiry_and_key_rotation_never_resurrect_launch_url():
    service, _, actor, _, clock = setup()
    waiting = await service.create(actor, "issue")
    clock.value += timedelta(seconds=600)
    assert (await service.status(actor)).state == "expired"
    assert (await service.create(actor, "issue")).launch_url is None
    clock.value = NOW
    service.tokens = None
    rotated = await service.status(actor)
    assert rotated.state == "unavailable" and rotated.launch_url is None
    assert waiting.launch_url


@pytest.mark.asyncio
async def test_five_new_issuances_rolling_hour_exact_replay_is_free():
    service, repo, actor, _, clock = setup()
    for n in range(5):
        view = await service.create(actor, f"issue-{n}")
        await service.revoke(
            actor, view.challenge_id, view.version, f"revoke-{n}"
        )
    assert (await service.create(actor, "issue-4")).receipt.state == "waiting"
    assert (await service.create(actor, "sixth")).state == "rate_limited"
    assert len(repo.challenges) == 5
    clock.value += timedelta(hours=1, seconds=1)
    assert (await service.create(actor, "later")).state == "waiting"


@pytest.mark.asyncio
async def test_native_twenty_attempt_cap_counts_invalid_replay_is_free():
    service, repo, actor, _, _ = setup()
    waiting = await service.create(actor, "issue")
    for n in range(20):
        receipt = await service.propose_native(
            replace(native(waiting, source=str(n)), token="lk1_!")
        )
        assert receipt.state == "invalid"
    receipt = await service.propose_native(
        replace(native(waiting, source="0"), token="lk1_!")
    )
    assert receipt.state == "invalid"
    blocked = await service.propose_native(native(waiting, source="21"))
    assert blocked.state == "rate_limited" and not repo.claims


@pytest.mark.asyncio
async def test_native_changed_replay_never_replaces_first_claim():
    service, repo, actor, _, _ = setup()
    view = await service.create(actor, "issue")
    first = await service.propose_native(native(view))
    assert await service.propose_native(native(view)) == first
    changed = await service.propose_native(
        replace(native(view), display_name="changed")
    )
    assert changed.state == "conflict"
    other = await service.propose_native(
        native(view, sender="888", source="101")
    )
    assert other.state == "conflict" and len(repo.claims) == 1


@pytest.mark.asyncio
async def test_confirm_payload_version_and_operation_replay_are_fenced():
    service, repo, actor, _, _ = setup()
    view = await service.create(actor, "issue")
    receipt = await service.propose_native(native(view))
    proposed = await service.status(actor)
    with pytest.raises(ValueError, match="link_version_conflict"):
        await service.confirm(
            actor, view.challenge_id, receipt.claim_id, 1, "stale"
        )
    await service.confirm(
        actor, view.challenge_id, receipt.claim_id, proposed.version, "confirm"
    )
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        await service.confirm(
            actor, view.challenge_id, UUID(int=900), proposed.version, "confirm"
        )
    assert repo.users[actor.user_id].telegram_id == "777"


@pytest.mark.parametrize("change", ["blocked", "profile_deleted"])
@pytest.mark.asyncio
async def test_current_active_advertiser_required_even_for_admin(change):
    service, repo, actor, _, _ = setup()
    waiting = await service.create(actor, "issue")
    receipt = await service.propose_native(native(waiting))
    proposed = await service.status(actor)
    if change == "blocked":
        repo.users[actor.user_id] = replace(
            repo.users[actor.user_id], status=UserStatus.BLOCKED
        )
    else:
        repo.advertisers.clear()
    result = await service.confirm(
        actor,
        waiting.challenge_id,
        receipt.claim_id,
        proposed.version,
        "confirm",
    )
    assert (
        result.state == "unavailable"
        and repo.users[actor.user_id].telegram_id is None
    )


@pytest.mark.asyncio
async def test_failed_commit_does_not_leave_challenge_or_attached_user():
    service, repo, actor, tm, _ = setup()
    tm.fail = True
    with pytest.raises(RuntimeError):
        await service.create(actor, "issue")
    assert not repo.challenges and repo.users[actor.user_id].telegram_id is None


@pytest.mark.asyncio
async def test_issuance_and_confirmation_take_clock_after_repository_wait():
    service, repo, actor, _, clock = setup()
    original_create = repo.create

    async def delayed_create(*args, **kwargs):
        clock.value += timedelta(seconds=590)
        return await original_create(*args, **kwargs)

    repo.create = delayed_create
    view = await service.create(actor, "issue")
    assert view.expires_at == clock.value + timedelta(seconds=600)
    await service.propose_native(native(view))
    proposed = await service.status(actor)
    original_confirm = repo.confirm

    async def delayed_confirm(*args, **kwargs):
        clock.value += timedelta(seconds=600)
        return await original_confirm(*args, **kwargs)

    repo.confirm = delayed_confirm
    with pytest.raises(ValueError, match="link_not_confirmable"):
        await service.confirm(
            actor,
            proposed.challenge_id,
            proposed.claim_id,
            proposed.version,
            "confirm",
        )
    assert repo.users[actor.user_id].telegram_id is None


@pytest.mark.asyncio
async def test_changed_secret_with_reused_key_id_cannot_reuse_old_proof():
    from ugc_bot.infrastructure.messenger.link_tokens import LinkTokens

    service, repo, actor, _, _ = setup()
    waiting = await service.create(actor, "issue")
    receipt = await service.propose_native(native(waiting))
    proposed = await service.status(actor)
    service.tokens = LinkTokens(
        SecretStr(base64.urlsafe_b64encode(b"r" * 32).decode().rstrip("=")),
        service.scope,
    )
    current = await service.status(actor)
    assert current.state == "unavailable" and current.launch_url is None
    denied = await service.confirm(
        actor,
        waiting.challenge_id,
        receipt.claim_id,
        proposed.version,
        "confirm",
    )
    assert (
        denied.state == "unavailable"
        and repo.users[actor.user_id].telegram_id is None
    )


@pytest.mark.parametrize("key", ["", "x" * 257])
@pytest.mark.asyncio
async def test_direct_service_rejects_invalid_operation_keys(key):
    service, repo, actor, _, _ = setup()
    with pytest.raises(ValueError, match="invalid_operation_key"):
        await service.create(actor, key)
    assert not repo.challenges


@pytest.mark.asyncio
async def test_foreign_or_missing_challenge_never_leaks_owner_context():
    service, repo, actor, _, _ = setup()
    with pytest.raises(LookupError, match="messenger_link_not_found"):
        await service.status(actor, UUID(int=999))
    waiting = await service.create(actor, "issue")
    other = MaxLinkActor(UUID(int=500), "other-max")
    repo.users[other.user_id] = replace(
        repo.users[actor.user_id],
        user_id=other.user_id,
        max_id=other.external_id,
    )
    repo.advertisers.add(other.user_id)
    with pytest.raises(LookupError):
        await service.status(other, waiting.challenge_id)


@pytest.mark.asyncio
async def test_already_same_canonical_pair_never_issues_or_counts_challenge():
    service, repo, actor, _, _ = setup()
    repo.users[actor.user_id] = replace(
        repo.users[actor.user_id], telegram_id="777"
    )
    view = await service.create(actor, "existing")
    assert view.state == "linked" and view.launch_url is None
    assert not repo.challenges


@pytest.mark.asyncio
async def test_new_telegram_mapping_during_pending_proof_is_not_new_issuance():
    service, repo, actor, _, _ = setup()
    await service.create(actor, "issue")
    repo.users[actor.user_id] = replace(
        repo.users[actor.user_id], telegram_id="999"
    )
    assert (await service.status(actor)).state == "identity_changed"
    assert (
        await service.create(actor, "unexpected-new")
    ).state == "unavailable"
    assert len(repo.challenges) == 1


@pytest.mark.asyncio
async def test_revoke_replay_version_and_terminal_state_are_fenced():
    service, _, actor, _, _ = setup()
    view = await service.create(actor, "issue")
    with pytest.raises(ValueError, match="link_version_conflict"):
        await service.revoke(actor, view.challenge_id, 99, "stale")
    revoked = await service.revoke(
        actor, view.challenge_id, view.version, "revoke"
    )
    assert (
        await service.revoke(actor, view.challenge_id, view.version, "revoke")
    ).receipt == revoked.receipt
    with pytest.raises(ValueError, match="link_not_revocable"):
        await service.revoke(actor, view.challenge_id, revoked.version, "again")


@pytest.mark.asyncio
async def test_ordinary_registration_winning_before_confirm_is_safe_conflict():
    service, repo, actor, _, _ = setup()
    waiting = await service.create(actor, "issue")
    receipt = await service.propose_native(native(waiting))
    view = await service.status(actor)
    other = replace(
        repo.users[actor.user_id],
        user_id=UUID(int=800),
        max_id=None,
        telegram_id="777",
    )
    repo.users[other.user_id] = other
    result = await service.confirm(
        actor, view.challenge_id, receipt.claim_id, view.version, "confirm"
    )
    assert result.state == "conflict"
    assert repo.users[other.user_id] == other
    assert repo.users[actor.user_id].telegram_id is None


@pytest.mark.asyncio
async def test_expired_native_and_changed_max_binding_are_safe_negative_facts():
    service, repo, actor, _, clock = setup()
    waiting = await service.create(actor, "issue")
    clock.value += timedelta(seconds=600)
    assert (await service.propose_native(native(waiting))).state == "expired"
    clock.value -= timedelta(seconds=600)
    repo.users[actor.user_id] = replace(repo.users[actor.user_id], max_id=None)
    assert (
        await service.propose_native(native(waiting, source="101"))
    ).state == "unavailable"


@pytest.mark.asyncio
async def test_same_native_sender_new_source_keeps_original_claim():
    service, repo, actor, _, _ = setup()
    waiting = await service.create(actor, "issue")
    first = await service.propose_native(native(waiting))
    second = await service.propose_native(native(waiting, source="101"))
    assert second.claim_id == first.claim_id and second.version == first.version
    assert len(repo.claims) == 1


@pytest.mark.asyncio
async def test_foreign_active_claim_blocks_then_expiry_allows_reservation():
    service, repo, actor, _, clock = setup()
    first = await service.create(actor, "issue")
    await service.propose_native(native(first))
    other = MaxLinkActor(UUID(int=500), "other-max")
    repo.users[other.user_id] = replace(
        repo.users[actor.user_id],
        user_id=other.user_id,
        max_id=other.external_id,
    )
    repo.advertisers.add(other.user_id)
    clock.value += timedelta(seconds=599)
    second = await service.create(other, "issue-other")
    assert (
        await service.propose_native(native(second, source="101"))
    ).state == "conflict"
    clock.value += timedelta(seconds=2)
    assert (
        await service.propose_native(native(second, source="102"))
    ).state == "proposed"


@pytest.mark.asyncio
async def test_equal_numeric_ids_never_imply_same_authenticated_identity():
    service, repo, actor, _, _ = setup()
    waiting = await service.create(actor, "issue")
    assert repo.users[actor.user_id].telegram_id is None
    result = await service.propose_native(
        native(waiting, sender=actor.external_id)
    )
    assert (
        result.state == "proposed"
        and repo.users[actor.user_id].telegram_id is None
    )


@pytest.mark.asyncio
async def test_memory_projection_corruption_is_not_repaired_or_authority():
    service, repo, actor, _, _ = setup()
    waiting = await service.create(actor, "issue")
    receipt = await service.propose_native(native(waiting))
    view = await service.status(actor)
    await service.revoke(actor, view.challenge_id, view.version, "revoke")
    repo.states[view.challenge_id] = "proposed", view.version, receipt.claim_id
    with pytest.raises(ValueError, match="messenger_state_unavailable"):
        await service.status(actor)
    assert repo.users[actor.user_id].telegram_id is None


@pytest.mark.parametrize("projection", ["owner", "telegram"])
@pytest.mark.parametrize(
    "operation", ["status", "create", "native", "confirm", "revoke"]
)
@pytest.mark.asyncio
async def test_live_facts_require_matching_active_projection(
    projection, operation
):
    service, repo, actor, _, _ = setup()
    waiting = await service.create(actor, "issue")
    proof = native(waiting)
    await service.propose_native(proof)
    view = await service.status(actor)
    if projection == "owner":
        repo.active_owner.pop(actor.user_id)
    else:
        repo.active_tg.pop(proof.sender_id)
    with pytest.raises(ValueError, match="messenger_state_unavailable"):
        if operation == "status":
            await service.status(actor)
        elif operation == "create":
            await service.create(actor, "new")
        elif operation == "native":
            await service.propose_native(replace(proof, update_id="new-source"))
        elif operation == "confirm":
            await service.confirm(
                actor, view.challenge_id, view.claim_id, view.version, "confirm"
            )
        else:
            await service.revoke(
                actor, view.challenge_id, view.version, "revoke"
            )
    assert repo.users[actor.user_id].telegram_id is None


@pytest.mark.asyncio
async def test_waiting_fact_without_pointer_cannot_issue_second_challenge():
    service, repo, actor, _, _ = setup()
    waiting = await service.create(actor, "issue")
    repo.active_owner.clear()
    with pytest.raises(ValueError, match="messenger_state_unavailable"):
        await service.create(actor, "second")
    assert list(repo.challenges) == [waiting.challenge_id]

"""Transport outcomes gate silence finalization; no live messenger calls."""

from datetime import timedelta

import pytest

from tests.application.services.test_collaboration_service import (
    execute,
    started,
)
from ugc_bot.domain.collaboration import CollaborationState


async def setup_delivery(
    *, transport=None, claim=True, evidence="https://example.test/content/proof"
):
    (
        lifecycle,
        work_repo,
        scope,
        clock,
        Command,
        admin,
        current,
    ) = await started()
    await execute(
        lifecycle,
        work_repo,
        Command(
            assignment_id=scope.assignment_id,
            action="claim" if claim else "request_confirmation",
            actor_id=scope.creator_id if claim else scope.manager_id,
            operation_key="notice-source",
            expected_version=current.version,
            evidence=evidence if claim else None,
        ),
    )
    try:
        from ugc_bot.application.notice_delivery_ports import (
            DeliveryContact,
            DeliveryReceipt,
        )
        from ugc_bot.application.services.collaboration_notice_delivery import (
            CollaborationNoticeDelivery,
        )
        from ugc_bot.infrastructure.memory_notice_delivery import (
            InMemoryNoticeDeliveryRepository,
        )
    except ModuleNotFoundError:
        pytest.fail("Durable notice delivery worker is missing")
    contacts = {
        scope.client_id: DeliveryContact(
            scope.client_id, "telegram", "101", "ru", "active"
        ),
        scope.creator_id: DeliveryContact(
            scope.creator_id, "max", "202", "en", "active"
        ),
    }
    repository = InMemoryNoticeDeliveryRepository(work_repo, contacts)
    if transport is None:
        transport = RecordingTransport(work_repo, repository, DeliveryReceipt)
    worker = CollaborationNoticeDelivery(
        lifecycle=lifecycle,
        repository=repository,
        transactions=repository,
        transport=transport,
        miniapp_url="https://miniapp.example.test/miniapp/app.html",
        lease_seconds=60,
    )
    return (
        worker,
        repository,
        work_repo,
        scope,
        clock,
        Command,
        admin,
        transport,
    )


class RecordingTransport:
    def __init__(self, work_repo, repository, Receipt):
        self.work_repo = work_repo
        self.repository = repository
        self.Receipt = Receipt
        self.sent = []

    async def send(self, attempt):
        # A provider call must see a committed attempt and no lifecycle lock.
        assert attempt.attempt_id in self.repository.attempts
        assert not self.work_repo._lock.locked()
        self.sent.append(attempt)
        return self.Receipt(attempt.channel, "provider-message-123")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "locale,label",
    [
        ("ru", "Открыть сотрудничество"),
        ("en", "Open collaboration"),
        ("kk", "Ынтымақтастықты ашу"),
        ("be", "Адкрыць супрацоўніцтва"),
        ("uz", "Hamkorlikni ochish"),
        ("unknown", "Открыть сотрудничество"),
    ],
)
async def test_native_launch_uses_current_recipient_locale_and_frozen_url(
    locale, label
):
    from dataclasses import replace

    (
        worker,
        repository,
        work_repo,
        scope,
        _,
        _,
        _,
        transport,
    ) = await setup_delivery()
    repository.contacts[scope.client_id] = replace(
        repository.contacts[scope.client_id], locale=locale
    )
    attempt = await worker.prepare(event_id(work_repo))
    expected = f"https://miniapp.example.test/miniapp/app.html?assignment={scope.assignment_id}"
    assert getattr(attempt, "action_url", None) == expected
    assert attempt.action_label == label
    assert repository.attempts[attempt.attempt_id].action_url == expected
    worker.miniapp_url = "https://changed.example.test/miniapp/app.html"
    await worker.deliver(attempt)
    sent = transport.sent[0]
    assert sent.action_url == expected and sent.action_label == label


@pytest.mark.asyncio
async def test_first_provider_receipt_enables_only_original_silence_deadline():
    (
        worker,
        repository,
        work_repo,
        scope,
        clock,
        Command,
        _,
        transport,
    ) = await setup_delivery()
    claimed_at = clock.at
    clock.at += timedelta(minutes=1)
    await worker.run_once()
    current = work_repo.records[scope.assignment_id]
    assert current.collaboration.notice_delivered_at == clock.at
    assert current.collaboration.notice_failed_at is None
    assert current.collaboration.objection_deadline == claimed_at + timedelta(
        hours=72
    )
    assert len(transport.sent) == 1
    attempt = transport.sent[0]
    notice = work_repo.notices[attempt.notice_id]
    assert attempt.recipient_id == scope.client_id == notice.recipient_id
    assert attempt.source_event_id == notice.source_event_id
    assert "https://example.test/content/proof" in attempt.text
    assert "2026-10-26" in attempt.text
    outcomes = list(repository.outcomes.values())
    assert outcomes[0].provider_reference == "provider-message-123"
    assert outcomes[0].applied is True
    await worker.run_once()
    assert len(transport.sent) == 1
    clock.at = claimed_at + timedelta(hours=72)
    final = await execute(
        worker.lifecycle,
        work_repo,
        Command(
            assignment_id=scope.assignment_id,
            action="advance",
            system_actor="collaboration_scheduler",
            operation_key="mature-proof",
            expected_version=current.version,
        ),
    )
    assert final.collaboration.state == CollaborationState.SUCCESS_FINAL
    assert final.collaboration.success_final_at == claimed_at + timedelta(
        hours=72
    )


def event_id(work_repo):
    return next(
        key
        for key, event in work_repo.outbox.items()
        if event.event_type == "financial.collaboration.notice_requested"
    )


async def advance(env):
    worker, _, work_repo, scope, clock, Command, _, _ = env
    clock.at += timedelta(hours=73)
    return await execute(
        worker.lifecycle,
        work_repo,
        Command(
            assignment_id=scope.assignment_id,
            action="advance",
            system_actor="collaboration_scheduler",
            operation_key="check-silence",
            expected_version=work_repo.records[scope.assignment_id].version,
        ),
    )


@pytest.mark.asyncio
async def test_failed_then_admin_retry_receipt_never_clears_failure():
    env = await setup_delivery()
    worker, repository, work_repo, scope, clock, _, admin, transport = env
    from ugc_bot.application.notice_delivery_ports import DeliveryFailure

    class Rejected:
        async def send(self, attempt):
            raise DeliveryFailure("provider_rejected", uncertain=False)

    worker.transport = Rejected()
    await worker.run_once()
    failed_at = work_repo.records[
        scope.assignment_id
    ].collaboration.notice_failed_at
    assert failed_at == clock.at
    worker.transport = transport
    await worker.retry_notice(
        event_id(work_repo),
        actor_id=admin,
        reason="verified contact fixed",
        operation_key="admin-retry-1",
    )
    clock.at += timedelta(minutes=1)
    await worker.run_once()
    work = work_repo.records[scope.assignment_id].collaboration
    assert work.notice_failed_at == failed_at
    assert work.notice_delivered_at == clock.at
    assert len(repository.attempts) == 2
    assert (
        await advance(env)
    ).collaboration.state == CollaborationState.SUCCESS_CLAIMED


@pytest.mark.asyncio
async def test_prepared_expiry_is_unknown_without_resend():
    env = await setup_delivery()
    worker, repository, work_repo, scope, clock, _, _, transport = env
    attempt = await worker.prepare(event_id(work_repo))
    assert attempt.attempt_id in repository.attempts
    clock.at += timedelta(seconds=61)
    await worker.run_once()
    assert not transport.sent
    assert (
        work_repo.records[scope.assignment_id].collaboration.notice_failed_at
        == clock.at
    )
    assert any(
        item.kind == "recovery" and item.status == "unknown"
        for item in repository.outcomes.values()
    )
    await worker.run_once()
    assert len(repository.attempts) == 1
    assert (
        await advance(env)
    ).collaboration.state == CollaborationState.SUCCESS_CLAIMED


@pytest.mark.asyncio
async def test_crash_after_send_recovers_unknown():
    env = await setup_delivery()
    worker, repository, work_repo, scope, clock, _, _, transport = env

    class Crash(BaseException):
        pass

    class SentThenCrashed:
        async def send(self, attempt):
            transport.sent.append(attempt)
            raise Crash()

    worker.transport = SentThenCrashed()
    with pytest.raises(Crash):
        await worker.run_once()
    assert len(transport.sent) == 1 and not repository.outcomes
    clock.at += timedelta(seconds=61)
    worker.transport = transport
    await worker.run_once()
    assert len(transport.sent) == 1
    work = work_repo.records[scope.assignment_id].collaboration
    assert (
        work.notice_delivered_at is None and work.notice_failed_at == clock.at
    )
    assert (
        await advance(env)
    ).collaboration.state == CollaborationState.SUCCESS_CLAIMED


@pytest.mark.asyncio
async def test_missing_provider_receipt_is_unknown_not_a_generated_reference():
    env = await setup_delivery()
    worker, repository, work_repo, scope, _, _, _, _ = env

    class NoReceipt:
        async def send(self, attempt):
            return None

    worker.transport = NoReceipt()
    await worker.run_once()
    work = work_repo.records[scope.assignment_id].collaboration
    assert (
        work.notice_failed_at is not None and work.notice_delivered_at is None
    )
    outcomes = list(repository.outcomes.values())
    assert outcomes[0].status == "unknown"
    assert outcomes[0].provider_reference is None


@pytest.mark.asyncio
async def test_competing_workers_and_duplicate_dispatch_send_one_message():
    import asyncio

    env = await setup_delivery()
    worker, repository, work_repo, scope, _, _, _, transport = env
    await asyncio.gather(worker.run_once(), worker.run_once())
    assert len(transport.sent) == 1 and len(repository.attempts) == 1
    assert work_repo.records[scope.assignment_id].version == 4

    second = await setup_delivery()
    worker, repository, work_repo, _, _, _, _, transport = second
    attempt = await worker.prepare(event_id(work_repo))
    await asyncio.gather(worker.deliver(attempt), worker.deliver(attempt))
    assert len(transport.sent) == 1 and len(repository.outcomes) == 1


@pytest.mark.asyncio
async def test_late_receipt_audits_without_overwriting_unknown():
    env = await setup_delivery()
    worker, repository, work_repo, scope, clock, _, _, transport = env
    claimed_at = clock.at

    class LateReceipt:
        async def send(self, attempt):
            clock.at += timedelta(seconds=61)
            await worker.run_once()
            return transport.Receipt(attempt.channel, "late-provider-receipt")

    worker.transport = LateReceipt()
    await worker.run_once()
    outcomes = list(repository.outcomes.values())
    assert any(
        item.status == "unknown" and item.kind == "recovery"
        for item in outcomes
    )
    assert any(
        item.provider_reference == "late-provider-receipt" and not item.applied
        for item in outcomes
    )
    work = work_repo.records[scope.assignment_id].collaboration
    assert (
        work.notice_failed_at is not None and work.notice_delivered_at is None
    )
    assert work.objection_deadline == claimed_at + timedelta(hours=72)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["agree", "dispute"])
async def test_concurrent_party_decision_is_not_rewritten_by_transport_result(
    action,
):
    env = await setup_delivery()
    worker, repository, work_repo, scope, _, Command, _, transport = env

    class DecidingTransport:
        async def send(self, attempt):
            await execute(
                worker.lifecycle,
                work_repo,
                Command(
                    assignment_id=scope.assignment_id,
                    action=action,
                    actor_id=scope.client_id,
                    operation_key="party-decision",
                    expected_version=work_repo.records[
                        scope.assignment_id
                    ].version,
                    reason="actual objection" if action == "dispute" else None,
                ),
            )
            return transport.Receipt(
                attempt.channel, "accepted-before-party-change"
            )

    worker.transport = DecidingTransport()
    await worker.run_once()
    work = work_repo.records[scope.assignment_id]
    assert work.version == 4
    expected = (
        CollaborationState.SUCCESS_FINAL
        if action == "agree"
        else CollaborationState.DISPUTED
    )
    assert work.collaboration.state == expected
    assert work.collaboration.notice_delivered_at is None
    assert list(repository.outcomes.values())[0].applied is False


@pytest.mark.asyncio
async def test_extension_during_send_keeps_original_deadline():
    env = await setup_delivery()
    worker, _, work_repo, scope, clock, Command, _, transport = env
    claimed_at = clock.at

    class ExtendingTransport:
        async def send(self, attempt):
            await execute(
                worker.lifecycle,
                work_repo,
                Command(
                    assignment_id=scope.assignment_id,
                    action="extend_due",
                    actor_id=scope.client_id,
                    operation_key="extend-during-send",
                    expected_version=3,
                    expected_due_version=1,
                    due_at=clock.at + timedelta(days=3),
                    terms_reference="new agreed due",
                    reason="client consent",
                ),
            )
            return transport.Receipt(
                attempt.channel, "provider-after-extension"
            )

    worker.transport = ExtendingTransport()
    await worker.run_once()
    record = work_repo.records[scope.assignment_id]
    assert record.version == 5 and record.collaboration.due_version == 2
    assert record.collaboration.notice_delivered_at == clock.at
    assert record.collaboration.objection_deadline == claimed_at + timedelta(
        hours=72
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["assignment", "role"])
async def test_revoked_scope_is_audited_without_io_or_lifecycle_mutation(
    change,
):
    from dataclasses import replace

    env = await setup_delivery()
    worker, repository, work_repo, scope, clock, _, _, transport = env
    if change == "assignment":
        work_repo.scopes[scope.assignment_id] = replace(
            scope, valid_to=clock.at
        )
    else:
        work_repo.actors[scope.client_id] = replace(
            work_repo.actors[scope.client_id], is_client=False
        )
    await worker.run_once()
    assert not transport.sent
    assert work_repo.records[scope.assignment_id].version == 3
    assert list(repository.outcomes.values())[0].status == "obsolete"


@pytest.mark.asyncio
async def test_recipient_blocked_or_contact_changed_never_creates_success():
    from dataclasses import replace

    env = await setup_delivery()
    worker, repository, work_repo, scope, _, _, _, transport = env
    repository.contacts[scope.client_id] = replace(
        repository.contacts[scope.client_id], status="bot_blocked"
    )
    await worker.run_once()
    assert not transport.sent
    assert (
        work_repo.records[scope.assignment_id].collaboration.notice_failed_at
        is not None
    )

    second = await setup_delivery()
    worker, repository, work_repo, scope, _, _, _, transport = second
    attempt = await worker.prepare(event_id(work_repo))
    repository.contacts[scope.client_id] = replace(
        repository.contacts[scope.client_id], address="999"
    )
    await worker.deliver(attempt)
    assert not transport.sent
    assert (
        work_repo.records[scope.assignment_id].collaboration.notice_delivered_at
        is None
    )


@pytest.mark.asyncio
async def test_confirmation_request_receipts_do_not_mark_objection_delivered():
    env = await setup_delivery(claim=False)
    worker, repository, work_repo, scope, _, _, _, transport = env
    await worker.run_once()
    assert len(transport.sent) == 2 and len(repository.outcomes) == 2
    record = work_repo.records[scope.assignment_id]
    assert record.version == 3
    assert record.collaboration.notice_delivered_at is None
    assert record.collaboration.notice_failed_at is None
    assert {attempt.recipient_id for attempt in transport.sent} == {
        scope.client_id,
        scope.creator_id,
    }


@pytest.mark.asyncio
async def test_forged_event_rejected_and_other_owner_untouched():
    from dataclasses import replace

    env = await setup_delivery()
    worker, repository, work_repo, scope, _, _, _, transport = env
    key = event_id(work_repo)
    original = work_repo.outbox[key]
    work_repo.outbox[key] = replace(
        original,
        payload={"notice_id": str(key), "recipient_id": str(scope.creator_id)},
    )
    await worker.run_once()
    assert not transport.sent and not repository.attempts
    assert work_repo.records[scope.assignment_id].version == 3
    assert work_repo.outbox[key].last_error == "notice_event_proof_invalid"
    other_status = {
        key: value.status
        for key, value in work_repo.outbox.items()
        if key != original.event_id
    }
    await worker.run_once()
    assert {
        key: value.status
        for key, value in work_repo.outbox.items()
        if key != original.event_id
    } == other_status


@pytest.mark.asyncio
async def test_manual_retry_authorization_and_immutable_audit():
    from dataclasses import replace

    env = await setup_delivery()
    worker, repository, work_repo, scope, clock, _, admin, _ = env
    await worker.prepare(event_id(work_repo))
    clock.at += timedelta(seconds=61)
    await worker.run_once()
    with pytest.raises(PermissionError, match="admin"):
        await worker.retry_notice(
            event_id(work_repo),
            actor_id=scope.client_id,
            reason="retry",
            operation_key="denied",
        )
    with pytest.raises(ValueError, match="reason"):
        await worker.retry_notice(
            event_id(work_repo),
            actor_id=admin,
            reason=" ",
            operation_key="empty",
        )
    await worker.retry_notice(
        event_id(work_repo),
        actor_id=admin,
        reason="reviewed unknown",
        operation_key="review-1",
    )
    outcomes = len(repository.outcomes)
    await worker.retry_notice(
        event_id(work_repo),
        actor_id=admin,
        reason="reviewed unknown",
        operation_key="review-1",
    )
    assert len(repository.outcomes) == outcomes
    with pytest.raises(ValueError, match="payload"):
        await worker.retry_notice(
            event_id(work_repo),
            actor_id=admin,
            reason="changed",
            operation_key="review-1",
        )
    work_repo.actors[admin] = replace(work_repo.actors[admin], status="blocked")
    with pytest.raises(PermissionError, match="admin"):
        await worker.retry_notice(
            event_id(work_repo),
            actor_id=admin,
            reason="retry",
            operation_key="denied-blocked",
        )


@pytest.mark.asyncio
async def test_changed_contact_during_send_blocks_silence():
    from dataclasses import replace

    env = await setup_delivery()
    worker, repository, work_repo, scope, _, _, _, transport = env

    class ContactChanged:
        async def send(self, attempt):
            repository.contacts[scope.client_id] = replace(
                repository.contacts[scope.client_id], address="999"
            )
            return transport.Receipt(attempt.channel, "accepted-old-contact")

    worker.transport = ContactChanged()
    await worker.run_once()
    work = work_repo.records[scope.assignment_id].collaboration
    assert work.notice_delivered_at is None
    assert work.notice_failed_at is not None
    assert any(
        item.provider_reference == "accepted-old-contact" and not item.applied
        for item in repository.outcomes.values()
    )
    assert (
        await advance(env)
    ).collaboration.state == CollaborationState.SUCCESS_CLAIMED


@pytest.mark.asyncio
async def test_stale_dispatch_handle_cannot_resend_after_unknown_recovery():
    (
        worker,
        repository,
        work_repo,
        _,
        clock,
        _,
        _,
        transport,
    ) = await setup_delivery()
    attempt = await worker.prepare(event_id(work_repo))
    clock.at += timedelta(seconds=61)
    await worker.run_once()
    await worker.deliver(attempt)
    assert not transport.sent and len(repository.attempts) == 1


@pytest.mark.asyncio
async def test_dispatch_rejects_forged_attempt_snapshot_before_any_io():
    from dataclasses import replace

    worker, _, work_repo, scope, _, _, _, transport = await setup_delivery()
    attempt = await worker.prepare(event_id(work_repo))
    with pytest.raises(ValueError, match="attempt_snapshot"):
        await worker.deliver(
            replace(
                attempt,
                address="999",
                recipient_id=scope.creator_id,
                text="forged",
            )
        )
    assert not transport.sent
    assert work_repo.records[scope.assignment_id].version == 3


@pytest.mark.asyncio
async def test_confirmation_after_extension_skips_old_deadline():
    (
        worker,
        repository,
        work_repo,
        scope,
        clock,
        Command,
        _,
        transport,
    ) = await setup_delivery(claim=False)
    await execute(
        worker.lifecycle,
        work_repo,
        Command(
            assignment_id=scope.assignment_id,
            action="extend_due",
            actor_id=scope.client_id,
            operation_key="extend-before-confirmation",
            expected_version=3,
            expected_due_version=1,
            due_at=clock.at + timedelta(days=3),
            terms_reference="updated agreed terms",
            reason="client consent",
        ),
    )
    await worker.run_once()
    assert not transport.sent
    assert len(repository.outcomes) == 2
    assert all(
        item.status == "obsolete" for item in repository.outcomes.values()
    )
    assert work_repo.records[scope.assignment_id].version == 4


@pytest.mark.asyncio
async def test_old_receipt_after_manual_retry_cannot_overwrite_new_lease():
    env = await setup_delivery()
    worker, repository, work_repo, scope, clock, _, admin, transport = env
    original_claim = clock.at

    class LateOldAttempt:
        async def send(self, attempt):
            clock.at += timedelta(seconds=61)
            await worker.run_once()
            await worker.retry_notice(
                attempt.event_id,
                actor_id=admin,
                reason="reviewed unknown provider result",
                operation_key="review-after-expiry",
            )
            worker.transport = transport
            await worker.run_once()
            return transport.Receipt(attempt.channel, "late-original-reference")

    worker.transport = LateOldAttempt()
    await worker.run_once()
    assert len(repository.attempts) == 2 and len(transport.sent) == 1
    record = work_repo.records[scope.assignment_id]
    assert record.version == 6
    assert record.collaboration.notice_failed_at is not None
    assert (
        record.collaboration.objection_deadline
        == original_claim + timedelta(hours=72)
    )
    assert any(
        item.provider_reference == "late-original-reference"
        and not item.applied
        for item in repository.outcomes.values()
    )
    assert (
        await advance(env)
    ).collaboration.state == CollaborationState.SUCCESS_CLAIMED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "locale,word",
    [
        ("ru", "Доказательство"),
        ("en", "Evidence"),
        ("kk", "Дәлел"),
        ("be", "Доказ"),
        ("uz", "Dalil"),
        ("unsupported", "Доказательство"),
    ],
)
async def test_notice_copy_uses_current_locale_real_proof_and_original_deadline(
    locale, word
):
    from dataclasses import replace

    (
        worker,
        repository,
        work_repo,
        scope,
        clock,
        _,
        _,
        transport,
    ) = await setup_delivery()
    repository.contacts[scope.client_id] = replace(
        repository.contacts[scope.client_id], locale=locale
    )
    worker.miniapp_url = (
        "https://example.test/app?lang=ru&assignment_id=untrusted-old"
    )
    await worker.run_once()
    text = transport.sent[0].text
    assert word in text and "https://example.test/content/proof" in text
    assert f"assignment={scope.assignment_id}" in text
    assert "untrusted-old" not in text
    assert "2026-10-26T00:00:00+00:00" in text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://example.test/app",
        "https://user:password@example.test/app",
        "relative/app",
    ],
)
async def test_unavailable_miniapp_link_fails_without_sending(url):
    (
        worker,
        repository,
        work_repo,
        scope,
        _,
        _,
        _,
        transport,
    ) = await setup_delivery()
    worker.miniapp_url = url
    await worker.run_once()
    assert not transport.sent
    assert (
        work_repo.records[scope.assignment_id].collaboration.notice_failed_at
        is not None
    )
    assert (
        list(repository.outcomes.values())[0].reason
        == "notice_miniapp_url_unavailable"
    )


@pytest.mark.asyncio
async def test_unsupported_channel_followed_by_reviewed_retry_remains_blocked():
    from dataclasses import replace

    env = await setup_delivery()
    worker, repository, work_repo, scope, _, _, admin, transport = env
    original = repository.contacts[scope.client_id]
    repository.contacts[scope.client_id] = replace(original, channel="whatsapp")
    await worker.run_once()
    assert not transport.sent
    repository.contacts[scope.client_id] = original
    await worker.retry_notice(
        event_id(work_repo),
        actor_id=admin,
        reason="reviewed supported contact",
        operation_key="review-unsupported",
    )
    await worker.run_once()
    work = work_repo.records[scope.assignment_id].collaboration
    assert (
        work.notice_failed_at is not None
        and work.notice_delivered_at is not None
    )
    assert (
        await advance(env)
    ).collaboration.state == CollaborationState.SUCCESS_CLAIMED


@pytest.mark.asyncio
async def test_mutated_source_envelope_after_io_keeps_receipt_audit_only():
    from dataclasses import replace

    (
        worker,
        repository,
        work_repo,
        scope,
        _,
        _,
        _,
        transport,
    ) = await setup_delivery()

    class EnvelopeChanged:
        async def send(self, attempt):
            work_repo.outbox[attempt.event_id] = replace(
                work_repo.outbox[attempt.event_id],
                payload={"notice_id": str(attempt.notice_id), "forged": True},
            )
            return transport.Receipt(
                attempt.channel, "accepted-before-envelope-change"
            )

    worker.transport = EnvelopeChanged()
    await worker.run_once()
    assert any(
        item.provider_reference == "accepted-before-envelope-change"
        and not item.applied
        for item in repository.outcomes.values()
    )
    assert work_repo.records[scope.assignment_id].version == 3


@pytest.mark.asyncio
async def test_unknown_or_other_owner_event_cannot_be_dispatched_or_retried():
    from uuid import uuid4

    worker, _, work_repo, _, _, _, admin, transport = await setup_delivery()
    other = next(
        key
        for key, item in work_repo.outbox.items()
        if item.event_type != "financial.collaboration.notice_requested"
    )
    for key in (uuid4(), other):
        assert await worker.prepare(key) is None
        with pytest.raises(ValueError, match="proof_invalid"):
            await worker.retry_notice(
                key,
                actor_id=admin,
                reason="manual review",
                operation_key="not-owned",
            )
    assert not transport.sent


@pytest.mark.asyncio
async def test_notice_event_without_authoritative_fact_is_rejected():
    from dataclasses import replace
    from uuid import uuid4

    (
        worker,
        repository,
        work_repo,
        _,
        _,
        _,
        _,
        transport,
    ) = await setup_delivery()
    original = work_repo.outbox[event_id(work_repo)]
    forged_id = uuid4()
    work_repo.outbox[forged_id] = replace(
        original, event_id=forged_id, payload={"notice_id": str(forged_id)}
    )
    assert await worker.prepare(forged_id) is None
    assert (
        work_repo.outbox[forged_id].last_error == "notice_event_proof_invalid"
    )
    assert not repository.attempts and not transport.sent


@pytest.mark.asyncio
async def test_confirmation_requester_revocation_is_obsolete_without_send():
    from dataclasses import replace

    (
        worker,
        repository,
        work_repo,
        scope,
        _,
        _,
        _,
        transport,
    ) = await setup_delivery(claim=False)
    work_repo.actors[scope.manager_id] = replace(
        work_repo.actors[scope.manager_id], manager_order_ids=()
    )
    await worker.run_once()
    assert not transport.sent
    assert all(
        item.reason == "requester_role_revoked"
        for item in repository.outcomes.values()
    )
    assert work_repo.records[scope.assignment_id].version == 3


@pytest.mark.asyncio
async def test_elapsed_deadline_blocks_send_without_extension():
    (
        worker,
        repository,
        work_repo,
        scope,
        clock,
        _,
        _,
        transport,
    ) = await setup_delivery()
    deadline = work_repo.records[
        scope.assignment_id
    ].collaboration.objection_deadline
    clock.at = deadline
    await worker.run_once()
    assert not transport.sent
    work = work_repo.records[scope.assignment_id].collaboration
    assert (
        work.notice_delivered_at is None and work.notice_failed_at == deadline
    )
    assert work.objection_deadline == deadline
    assert (
        list(repository.outcomes.values())[0].reason
        == "notice_deadline_elapsed"
    )


@pytest.mark.asyncio
async def test_direct_dispatch_of_expired_lease_recovers_unknown_without_io():
    (
        worker,
        repository,
        work_repo,
        scope,
        clock,
        _,
        _,
        transport,
    ) = await setup_delivery()
    attempt = await worker.prepare(event_id(work_repo))
    clock.at += timedelta(seconds=61)
    await worker.deliver(attempt)
    assert not transport.sent
    assert (
        work_repo.records[scope.assignment_id].collaboration.notice_failed_at
        == clock.at
    )
    assert list(repository.outcomes.values())[0].status == "unknown"


@pytest.mark.asyncio
async def test_transport_exception_is_unknown_without_error_content():
    worker, repository, work_repo, scope, _, _, _, _ = await setup_delivery()

    class Unexpected:
        async def send(self, attempt):
            raise RuntimeError("sensitive provider body")

    worker.transport = Unexpected()
    await worker.run_once()
    assert (
        work_repo.records[scope.assignment_id].collaboration.notice_failed_at
        is not None
    )
    result = list(repository.outcomes.values())[0]
    assert result.status == "unknown" and result.reason == "transport_exception"


@pytest.mark.asyncio
async def test_late_receipt_without_second_worker_stays_unknown():
    (
        worker,
        repository,
        work_repo,
        scope,
        clock,
        _,
        _,
        transport,
    ) = await setup_delivery()

    class Late:
        async def send(self, attempt):
            clock.at += timedelta(seconds=61)
            return transport.Receipt(attempt.channel, "late-no-second-worker")

    worker.transport = Late()
    await worker.run_once()
    work = work_repo.records[scope.assignment_id].collaboration
    assert (
        work.notice_failed_at is not None and work.notice_delivered_at is None
    )
    assert any(
        item.provider_reference == "late-no-second-worker" and not item.applied
        for item in repository.outcomes.values()
    )


@pytest.mark.asyncio
async def test_retry_requires_valid_key_failed_state_and_current_assignment():
    from dataclasses import replace

    worker, _, work_repo, scope, clock, _, admin, _ = await setup_delivery()
    key = event_id(work_repo)
    with pytest.raises(ValueError, match="key_required"):
        await worker.retry_notice(
            key, actor_id=admin, reason="review", operation_key=" "
        )
    with pytest.raises(ValueError, match="state_conflict"):
        await worker.retry_notice(
            key, actor_id=admin, reason="review", operation_key="not-failed"
        )
    await worker.prepare(key)
    clock.at += timedelta(seconds=61)
    await worker.prepare(key)
    work_repo.scopes[scope.assignment_id] = replace(scope, valid_to=clock.at)
    with pytest.raises(ValueError, match="assignment_obsolete"):
        await worker.retry_notice(
            key, actor_id=admin, reason="review", operation_key="revoked"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limit,lease", [(0, 60), (1001, 60), (True, 60), (1, 0)]
)
async def test_invalid_batch_configuration_is_rejected_before_work(
    limit, lease
):
    worker, repository, _, _, _, _, _, transport = await setup_delivery()
    worker.lease_seconds = lease
    with pytest.raises(ValueError, match="batch_or_lease"):
        await worker.run_once(limit=limit)
    assert not repository.attempts and not transport.sent


@pytest.mark.asyncio
async def test_memory_facts_and_transaction_contract():
    from dataclasses import replace

    worker, repository, work_repo, _, clock, _, _, _ = await setup_delivery()
    key = event_id(work_repo)
    attempt = await worker.prepare(key)
    await worker.deliver(attempt)
    outcome = list(repository.outcomes.values())[0]
    async with repository.transaction() as db:
        with pytest.raises(ValueError, match="attempt_immutable"):
            await repository.save_attempt(attempt, session=db)
        with pytest.raises(ValueError, match="outcome_immutable"):
            await repository.save_outcome(
                replace(outcome, provider_reference="forged"), session=db
            )
        other = next(
            key
            for key, item in work_repo.outbox.items()
            if item.event_type != "financial.collaboration.notice_requested"
        )
        with pytest.raises(ValueError, match="owner_required"):
            await repository.settle_event(
                other, "complete", clock.at, session=db
            )
    async with work_repo.transaction() as db:
        with pytest.raises(ValueError, match="caller_notice_transaction"):
            await repository.contact(attempt.recipient_id, session=db)
    assert repository.outcomes[outcome.outcome_id] == outcome


@pytest.mark.asyncio
async def test_full_evidence_over_provider_limit_is_failed_without_truncation():
    (
        worker,
        repository,
        work_repo,
        scope,
        _,
        _,
        _,
        transport,
    ) = await setup_delivery(evidence="https://example.test/" + "x" * 4200)
    await worker.run_once()
    assert not transport.sent
    assert (
        work_repo.records[scope.assignment_id].collaboration.notice_failed_at
        is not None
    )
    assert (
        list(repository.outcomes.values())[0].reason
        == "notice_text_exceeds_provider_limit"
    )


@pytest.mark.asyncio
async def test_notice_links_use_actual_recipient_platform_shell():
    worker, _, _, _, _, _, _, transport = await setup_delivery(claim=False)
    worker.miniapp_url = {
        "telegram": "https://telegram.example.test/miniapp/app.html",
        "max": "https://max.example.test/miniapp/max_app.html",
    }
    await worker.run_once()
    assert len(transport.sent) == 2
    for attempt in transport.sent:
        expected = worker.miniapp_url[attempt.channel]
        assert expected + "?assignment=" in attempt.text
        other = (
            "max.example"
            if attempt.channel == "telegram"
            else "telegram.example"
        )
        assert other not in attempt.text


@pytest.mark.asyncio
async def test_notice_canonical_assignment_query_replaces_all_old_values():
    from urllib.parse import parse_qsl, urlsplit

    worker, _, _, scope, _, _, _, transport = await setup_delivery()
    worker.miniapp_url = (
        "https://example.test/app?assignment=old&assignment_id=also-old&lang=ru"
    )
    await worker.run_once()
    link = transport.sent[0].text.rsplit("Mini App: ", 1)[1]
    query = parse_qsl(urlsplit(link).query)
    assert query == [("lang", "ru"), ("assignment", str(scope.assignment_id))]

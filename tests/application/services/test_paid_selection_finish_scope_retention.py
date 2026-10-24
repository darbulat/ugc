"""Synthetic pure delivery: a real accepted result survives a scope refresh.

The repository models immutable outcomes and transaction rollback, without SQL
or locks. These checks prove application behavior, not PostgreSQL races.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5

import pytest

from ugc_bot.application.notice_delivery_ports import (
    DeliveryContact,
    DeliveryReceipt,
)
from ugc_bot.application.paid_selection_delivery_ports import (
    SelectionDeliveryAttempt,
    SelectionDeliveryJob,
    SelectionDeliveryOutcome,
    SelectionDeliverySource,
)
from ugc_bot.application.services.paid_selection_delivery import (
    PaidSelectionDelivery,
)

SCOPE_CHANGED = "selection_scope_changed_retry_required"
REFERENCE = "synthetic-telegram:100:7"


class Clock:
    def __init__(self):
        self.at = datetime(2026, 10, 24, 6, tzinfo=timezone.utc)

    def now(self):
        return self.at


class Repository:
    def __init__(self, source, job):
        self.source = source
        self.current_job = job
        self.attempts: dict[UUID, SelectionDeliveryAttempt] = {}
        self.outcomes: dict[UUID, SelectionDeliveryOutcome] = {}
        self.accepted: list[tuple] = []
        self.source_requests = 0
        self.source_error: Exception | None = None
        self.job_error: Exception | None = None
        self.session = None

    async def candidates(self, at, limit, *, session):
        assert session is self.session
        return (self.current_job.job_id,)

    async def lock_source(self, job_id, at, *, session):
        assert session is self.session
        assert job_id == self.current_job.job_id
        self.source_requests += 1
        if self.source_error is not None:
            raise self.source_error
        return self.source

    async def job(self, job_id, *, session):
        assert session is self.session
        if self.job_error is not None:
            raise self.job_error
        return self.current_job

    async def save_job(self, job, *, session):
        assert session is self.session
        self.current_job = job

    async def save_attempt(self, attempt, *, session):
        assert session is self.session
        assert attempt.attempt_id not in self.attempts
        self.attempts[attempt.attempt_id] = attempt

    async def attempt(self, attempt_id, *, session):
        assert session is self.session
        return self.attempts[attempt_id]

    async def outcome(self, outcome_id, *, session):
        assert session is self.session
        return self.outcomes.get(outcome_id)

    async def save_outcome(self, outcome, *, session):
        assert session is self.session
        assert outcome.outcome_id not in self.outcomes
        self.outcomes[outcome.outcome_id] = outcome

    async def receipt_used(self, channel, reference, *, session):
        assert session is self.session
        return any(
            attempt.channel == channel
            and outcome.provider_reference == reference
            for attempt, _, outcome in self.accepted
        )

    async def accept(self, attempt, source, outcome, *, session):
        assert session is self.session
        self.accepted.append((attempt, source, outcome))


class Transactions:
    def __init__(self, repository):
        self.repository = repository
        self.commit_error: Exception | None = None

    @asynccontextmanager
    async def transaction(self):
        repo = self.repository
        assert repo.session is None
        before = (
            repo.current_job,
            dict(repo.attempts),
            dict(repo.outcomes),
            list(repo.accepted),
        )
        repo.session = object()
        try:
            yield repo.session
            if self.commit_error is not None:
                raise self.commit_error
        except Exception:
            (
                repo.current_job,
                repo.attempts,
                repo.outcomes,
                repo.accepted,
            ) = before
            raise
        finally:
            repo.session = None


class Bot:
    """One accepted synthetic transport; hook runs during unlocked I/O."""

    def __init__(self, repository):
        self.repository = repository
        self.calls: list[SelectionDeliveryAttempt] = []
        self.hook = None

    async def send(self, attempt):
        assert self.repository.session is None
        assert (
            self.repository.outcomes[
                uuid5(attempt.attempt_id, "started")
            ].status
            == "started"
        )
        self.calls.append(attempt)
        if self.hook is not None:
            await self.hook()
        return DeliveryReceipt("telegram", REFERENCE)


@pytest.fixture
def env():
    clock = Clock()
    job_id, interest_id, order_id, client_id = (uuid4() for _ in range(4))
    source = SelectionDeliverySource(
        job_id=job_id,
        interest_id=interest_id,
        order_id=order_id,
        client_id=client_id,
        creator_id=uuid4(),
        paid_item_id=uuid4(),
        assignment_id=uuid4(),
        assignment_version=1,
        manager_id=None,
        payment_id=uuid4(),
        capture_event_id=uuid4(),
        allocation_key="synthetic-selection-allocation",
        policy_version="synthetic-policy-v1",
        currency="RUB",
        instagram_user_id="123",
        instagram_url="https://instagram.com/creator/",
        confirmed_at=clock.now(),
        due_at=clock.now() + timedelta(days=3),
        contact=DeliveryContact(client_id, "telegram", "100", "ru", "active"),
        creator_contact={"username": "Creator", "telegram": "@creator"},
        source_hash="a" * 64,
    )
    job = SelectionDeliveryJob(
        job_id, interest_id, order_id, clock.now(), "ready", 0, None, None, None
    )
    repo = Repository(source, job)
    transactions = Transactions(repo)
    bot = Bot(repo)
    worker = PaidSelectionDelivery(repo, transactions, bot, clock)
    return SimpleNamespace(
        worker=worker,
        repo=repo,
        bot=bot,
        clock=clock,
        transactions=transactions,
    )


async def accepted_then_scope_changed(env):
    attempt = await env.worker.prepare(env.repo.current_job.job_id)
    assert attempt is not None

    async def changed():
        env.repo.source_error = ValueError(SCOPE_CHANGED)

    env.bot.hook = changed
    await env.worker.deliver(attempt)
    return attempt


@pytest.mark.asyncio
async def test_accepted_receipt_survives_finish_scope_change_without_accept(
    env,
):
    attempt = await accepted_then_scope_changed(env)
    outcome = env.repo.outcomes[uuid5(attempt.attempt_id, "transport")]
    assert outcome.job_id == attempt.job_id
    assert outcome.order_id == attempt.order_id
    assert outcome.attempt_id == attempt.attempt_id
    assert outcome.kind == "transport"
    assert outcome.status == "accepted"
    assert outcome.provider_reference == REFERENCE
    assert outcome.reason == SCOPE_CHANGED
    assert outcome.applied is False
    assert env.repo.current_job.state == "obsolete"
    assert env.repo.accepted == []
    assert env.bot.calls == [attempt]
    assert env.repo.source_requests == 3
    assert env.repo.attempts == {attempt.attempt_id: attempt}
    # A later scheduler pass cannot turn this receipt into a resend/application.
    env.repo.source_error = None
    await env.worker.run_once()
    assert env.bot.calls == [attempt]
    assert env.repo.accepted == []


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["prepare", "begin"])
async def test_scope_refresh_still_aborts_before_provider_io(env, phase):
    attempt = (
        await env.worker.prepare(env.repo.current_job.job_id)
        if phase == "begin"
        else None
    )
    initial_job = env.repo.current_job
    env.repo.source_error = ValueError(SCOPE_CHANGED)
    with pytest.raises(ValueError, match=f"^{SCOPE_CHANGED}$"):
        if phase == "prepare":
            await env.worker.prepare(initial_job.job_id)
        else:
            await env.worker.deliver(attempt)
    assert env.bot.calls == []
    assert env.repo.current_job == initial_job
    assert env.repo.outcomes == {}
    assert env.repo.accepted == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed_status,changed_reference",
    [("failed", REFERENCE), ("accepted", "synthetic-telegram:100:8")],
)
async def test_retained_receipt_replays_exactly_but_changed_result_conflicts(
    env, changed_status, changed_reference
):
    attempt = await accepted_then_scope_changed(env)
    original = dict(env.repo.outcomes)
    original_job = env.repo.current_job
    env.clock.at += timedelta(minutes=1)
    await env.worker._finish(attempt, "accepted", REFERENCE, None)
    assert env.repo.outcomes == original
    assert env.repo.current_job == original_job
    with pytest.raises(ValueError, match="^selection_outcome_conflict$"):
        await env.worker._finish(
            attempt, changed_status, changed_reference, None
        )
    assert env.repo.outcomes == original
    assert env.repo.current_job == original_job
    assert env.bot.calls == [attempt]
    assert env.repo.accepted == []


@pytest.mark.asyncio
async def test_unexpected_finish_source_error_propagates_without_false_receipt(
    env,
):
    attempt = await env.worker.prepare(env.repo.current_job.job_id)

    async def unavailable():
        env.repo.source_error = RuntimeError("synthetic_database_failure")

    env.bot.hook = unavailable
    with pytest.raises(RuntimeError, match="^synthetic_database_failure$"):
        await env.worker.deliver(attempt)
    assert env.bot.calls == [attempt]
    assert env.repo.current_job.state == "sending"
    assert uuid5(attempt.attempt_id, "transport") not in env.repo.outcomes
    assert env.repo.accepted == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    ["financial_principal_changed", SCOPE_CHANGED + "_extra"],
)
async def test_finish_only_handles_the_exact_refresh_error(
    env, monkeypatch, code
):
    attempt = await env.worker.prepare(env.repo.current_job.job_id)

    async def denied(job_id, session):
        raise ValueError(code)

    async def change_source_boundary():
        monkeypatch.setattr(env.worker, "_source", denied)

    env.bot.hook = change_source_boundary
    with pytest.raises(ValueError, match=f"^{code}$"):
        await env.worker.deliver(attempt)
    assert env.bot.calls == [attempt]
    assert env.repo.current_job.state == "sending"
    assert uuid5(attempt.attempt_id, "transport") not in env.repo.outcomes
    assert env.repo.accepted == []


@pytest.mark.asyncio
async def test_scope_retention_does_not_swallow_other_authority_denials(env):
    attempt = await env.worker.prepare(env.repo.current_job.job_id)

    async def denied():
        env.repo.source_error = ValueError(SCOPE_CHANGED)
        env.repo.job_error = ValueError("financial_principal_changed")

    env.bot.hook = denied
    with pytest.raises(ValueError, match="^financial_principal_changed$"):
        await env.worker.deliver(attempt)
    assert env.bot.calls == [attempt]
    assert env.repo.current_job.state == "sending"
    assert uuid5(attempt.attempt_id, "transport") not in env.repo.outcomes
    assert env.repo.accepted == []


@pytest.mark.asyncio
async def test_retention_commit_failure_is_atomic_and_not_swallowed(env):
    attempt = await env.worker.prepare(env.repo.current_job.job_id)

    async def failed_commit():
        env.repo.source_error = ValueError(SCOPE_CHANGED)
        env.transactions.commit_error = RuntimeError("synthetic_commit_failure")

    env.bot.hook = failed_commit
    with pytest.raises(RuntimeError, match="^synthetic_commit_failure$"):
        await env.worker.deliver(attempt)
    assert env.bot.calls == [attempt]
    assert env.repo.current_job.state == "sending"
    assert uuid5(attempt.attempt_id, "transport") not in env.repo.outcomes
    assert env.repo.accepted == []


@pytest.mark.asyncio
async def test_unchanged_scope_still_applies_the_actual_accepted_receipt(env):
    attempt = await env.worker.prepare(env.repo.current_job.job_id)
    await env.worker.deliver(attempt)
    outcome = env.repo.outcomes[uuid5(attempt.attempt_id, "transport")]
    assert outcome.status == "accepted"
    assert outcome.provider_reference == REFERENCE
    assert outcome.applied is True
    assert outcome.reason is None
    assert env.repo.current_job.state == "accepted"
    assert env.repo.accepted == [(attempt, env.repo.source, outcome)]
    assert env.bot.calls == [attempt]

"""Issued income can be reviewed after payment without erasing paid history."""

import importlib
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.application.services.test_lifecycle_ledger_extensions import setup
from tests.application.services.test_obligation_compensation import original
from ugc_bot.application.services.obligation_compensation_service import (
    ObligationCompensationService,
)
from ugc_bot.domain.corrections import correction_payload_hash


class Repository:
    def __init__(self, issued, ledger):
        self.issued, self.ledger = issued, ledger
        self.actor_id = uuid4()
        self.commands, self.cases, self.resolutions = {}, {}, {}
        self.admin = True

    async def load_scope(self, key, *, session):
        return SimpleNamespace(
            original=self.issued,
            capture=SimpleNamespace(
                client_id=self.issued.basis.referred_user_id
            ),
            user_ids=(self.issued.basis.recipient_id,),
            source_document={},
            source_hash=correction_payload_hash(
                tuple(self.ledger.movements.values())
            ),
        )

    async def lock_scope(self, scope, *, session):
        pass

    async def actor(self, identity, *, session):
        return SimpleNamespace(
            user_id=identity,
            admin=self.admin,
            status="active",
            telegram_id="current-admin",
            max_id=None,
        )

    async def command(self, actor, key, *, session):
        return self.commands.get(key)

    async def save_command(self, actor, key, digest, result, now, *, session):
        self.commands[key] = {"payload_hash": digest, "result": result}

    async def active_case(self, obligation_id, *, session):
        return next(
            (v for k, v in self.cases.items() if k not in self.resolutions),
            None,
        )

    async def case(self, identity, *, session):
        return self.cases.get(identity)

    async def append_case(self, fact, *, session):
        self.cases[fact["case_id"]] = fact

    async def resolution(self, identity, *, session):
        return self.resolutions.get(identity)

    async def append_resolution(self, fact, *, session):
        self.resolutions[fact["case_id"]] = fact


@pytest.mark.asyncio
@pytest.mark.parametrize("bucket", ("pending", "available", "paid"))
async def test_review_blocks_liquid_and_paid_cancellation_creates_explicit_debt(
    bucket,
):
    ports = importlib.import_module(
        "ugc_bot.application.financial_review_ports"
    )
    module = importlib.import_module(
        "ugc_bot.application.services.financial_review_service"
    )
    memory, ledger, *_ = setup()
    issued = await original(memory, ledger, bucket)
    repo = Repository(issued, memory)
    clock = SimpleNamespace(
        now=lambda: issued.basis.available_at + timedelta(days=1)
    )
    service = module.FinancialReviewService(
        repo, ledger, ObligationCompensationService(ledger), clock
    )
    async with memory.transaction() as session:
        scope = await repo.load_scope(
            issued.basis.business_key, session=session
        )
        command = ports.OpenFinancialReview(
            actor_id=repo.actor_id,
            operation_key="review-open",
            business_key=issued.basis.business_key,
            expected_source_hash=scope.source_hash,
            reason="Post-factum support evidence",
            evidence_reference="support:review",
            evidence_hash="a" * 64,
        )
        opened = await service.open(command, session=session)
        assert opened["state"] == "open"
        assert opened["buckets"]["paid"] == (5000 if bucket == "paid" else 0)
        assert opened["buckets"]["blocked"] == (0 if bucket == "paid" else 5000)
        resolution = ports.ResolveFinancialReview(
            actor_id=repo.actor_id,
            operation_key="review-resolve",
            case_id=__import__("uuid").UUID(opened["case_id"]),
            expected_version=1,
            expected_source_hash=opened["current_source_hash"],
            decision="cumulative_cancel",
            target_minor=2000,
            reason="Adjudicated partial liability cancellation",
            evidence_reference="support:decision",
            evidence_hash="b" * 64,
        )
        result = await service.resolve(resolution, session=session)
        assert result["cancelled_delta_minor"] == 2000
        assert result["buckets"]["debt"] == (2000 if bucket == "paid" else 0)
        assert result["buckets"]["paid"] == (5000 if bucket == "paid" else 0)
        assert await service.resolve(resolution, session=session) == result
    assert len(repo.cases) == len(repo.resolutions) == 1


async def service_scenario(bucket="pending"):
    ports = importlib.import_module(
        "ugc_bot.application.financial_review_ports"
    )
    module = importlib.import_module(
        "ugc_bot.application.services.financial_review_service"
    )
    memory, ledger, *_ = setup()
    issued = await original(memory, ledger, bucket)
    repo = Repository(issued, memory)
    clock = SimpleNamespace(
        now=lambda: issued.basis.available_at + timedelta(days=1)
    )
    app = module.FinancialReviewService(
        repo, ledger, ObligationCompensationService(ledger), clock
    )
    async with memory.transaction() as db:
        scope = await repo.load_scope(issued.basis.business_key, session=db)
    command = ports.OpenFinancialReview(
        actor_id=repo.actor_id,
        operation_key="open",
        business_key=issued.basis.business_key,
        expected_source_hash=scope.source_hash,
        reason="Actual reviewed economic disagreement",
        evidence_reference="support:claim",
        evidence_hash="a" * 64,
    )
    return app, memory, repo, issued, command, ports


@pytest.mark.asyncio
async def test_exact_receipt_needs_current_admin_and_second_case_is_refused():
    from dataclasses import replace

    app, memory, repo, issued, command, ports = await service_scenario()
    async with memory.transaction() as db:
        with pytest.raises(ValueError, match="financial_review_source_changed"):
            await app.open(
                replace(command, expected_source_hash="0" * 64), session=db
            )
        opened = await app.open(command, session=db)
        assert await app.open(command, session=db) == opened
        with pytest.raises(ValueError, match="financial_review_already_open"):
            await app.open(
                replace(
                    command,
                    operation_key="different",
                    expected_source_hash=opened["current_source_hash"],
                ),
                session=db,
            )
        with pytest.raises(ValueError, match="idempotency_payload_conflict"):
            await app.open(
                replace(command, reason="Changed replay"), session=db
            )
    repo.admin = False
    async with memory.transaction() as db:
        with pytest.raises(
            PermissionError, match="financial_review_active_admin_required"
        ):
            await app.open(command, session=db)
    assert len(repo.cases) == 1


@pytest.mark.asyncio
async def test_no_adjustment_restores_only_buckets_captured_by_this_case():
    from dataclasses import replace
    from uuid import UUID

    from ugc_bot.application.financial_ports import JournalMovement

    app, memory, repo, issued, command, ports = await service_scenario()
    async with memory.transaction() as db:
        await app.ledger.transfer(
            issued.basis.business_key,
            JournalMovement(
                obligation_id=issued.obligation_id,
                operation_key="other-work-case-block",
                event_id="other-work-dispute",
                movement_type="transfer",
                amount_minor=2000,
                currency="RUB",
                effective_at=app.clock.now(),
                recorded_at=app.clock.now(),
                actor_id=repo.actor_id,
                actor_kind="admin",
                reason="Separate preexisting work objection",
                bucket_from="pending",
                bucket_to="blocked",
                case_id=uuid4(),
            ),
            now=app.clock.now(),
            session=db,
        )
        scope = await repo.load_scope(issued.basis.business_key, session=db)
        opened = await app.open(
            replace(command, expected_source_hash=scope.source_hash), session=db
        )
        resolve = ports.ResolveFinancialReview(
            actor_id=repo.actor_id,
            operation_key="clear-this-case",
            case_id=UUID(opened["case_id"]),
            expected_version=1,
            expected_source_hash=opened["current_source_hash"],
            decision="no_adjustment",
            target_minor=None,
            reason="Original economic income confirmed",
            evidence_reference="support:decision",
            evidence_hash="b" * 64,
        )
        result = await app.resolve(resolve, session=db)
    assert result["buckets"]["pending"] == 3000
    assert result["buckets"]["blocked"] == 2000
    assert result["buckets"]["available"] == 0


@pytest.mark.asyncio
async def test_reserved_cancel_refuses_and_unadjusted_case_keeps_reservation():
    from dataclasses import replace
    from uuid import UUID

    app, memory, repo, _, command, ports = await service_scenario("reserved")
    async with memory.transaction() as db:
        opened = await app.open(command, session=db)
        resolve = ports.ResolveFinancialReview(
            actor_id=repo.actor_id,
            operation_key="cancel-reserved",
            case_id=UUID(opened["case_id"]),
            expected_version=1,
            expected_source_hash=opened["current_source_hash"],
            decision="cumulative_cancel",
            target_minor=1000,
            reason="Reviewed cancelled liability",
            evidence_reference="support:decision",
            evidence_hash="b" * 64,
        )
        with pytest.raises(
            ValueError, match="correction_reserved_review_required"
        ):
            await app.resolve(resolve, session=db)
        result = await app.resolve(
            replace(
                resolve,
                operation_key="no-adjustment",
                decision="no_adjustment",
                target_minor=None,
            ),
            session=db,
        )
        assert result["buckets"]["reserved"] == 5000
        assert result["buckets"]["paid"] == result["buckets"]["debt"] == 0


def test_available_restore_waits_for_authoritative_maturity():
    from tests.application.services.test_work_entitlement_service import START
    from ugc_bot.application.services.financial_review_service import (
        FinancialReviewService,
    )

    fact = dict(
        prior_cancelled_minor=0,
        blocked_buckets=dict(pending=1000, hold=2000, available=3000),
    )
    assert FinancialReviewService._restores(
        fact, 1500, START + timedelta(days=14), START
    ) == dict(pending=0, hold=4500, available=0)

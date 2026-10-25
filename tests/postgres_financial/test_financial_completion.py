"""Actual corrections and matured selection on PostgreSQL."""

import os
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.helpers.correction_runtime_pg import runtime
from tests.helpers.corrections import (
    assess_original,
    deliver_original_positions,
)
from tests.helpers.financial_environment import isolated_financial_database
from tests.postgres_financial.test_order_intake import intake_env
from ugc_bot.application.correction_ports import ApplySelectionRefund
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.application.services.refund_compensation_service import (
    SelectionRefundCompensationService,
)
from ugc_bot.application.services.selection_maturity_service import (
    SelectionMaturityService,
)
from ugc_bot.container.correction_factory import _original_client_assessment
from ugc_bot.domain.refund_rules import RefundRules
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import FinancialPolicyVersionModel
from ugc_bot.infrastructure.db.repositories.selection_maturity import (
    SqlAlchemySelectionMaturityRepository,
)

__all__ = ["intake_env"]


@pytest.fixture(scope="module")
def financial_pg_engine():
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Explicit isolated financial test PostgreSQL is required")
    with isolated_financial_database(
        url, target_revision="00e0_financial_completion"
    ) as engine:
        yield engine


@pytest_asyncio.fixture
async def completion(intake_env, request):
    env = intake_env
    version = "completion-" + uuid4().hex
    rules = RefundRules(
        3600, "item_delivered", "all_positions_resolved", (), "retain_earned"
    )
    with Session(env["pg"]) as db, db.begin():
        db.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=env["admin"].user_id,
                approved_at=env["clock"].at - timedelta(days=2),
                effective_from=env["clock"].at - timedelta(days=1),
                refund_window_seconds=3600,
                rules={
                    "terms_reference": "synthetic-approved-terms",
                    "allowed_clients": [str(env["user"].user_id)],
                    "refund_rules": rules.to_document(),
                },
            )
        )
    env["policy"] = version
    rt = await runtime(env, referred=getattr(request, "param", True))
    ledger = FinancialLedgerService(env["repos"]["financial_ledger_repo"])
    rt.service.compensation = SelectionRefundCompensationService(
        rt.repo,
        ledger,
        original_assessment=_original_client_assessment(
            ledger, env["clock"], env["container"].session_factory
        ),
    )
    yield rt, ledger


@pytest.mark.asyncio
@pytest.mark.parametrize("delayed", (False, True))
async def test_real_30_25_5_refund_compensation_then_selection_release(
    completion,
    delayed,
):
    rt, ledger = completion
    env = rt.env
    if not delayed:
        await assess_original(env, rt.facts)
    delivered = await deliver_original_positions(env, rt.facts, count=25)
    assert len(delivered) == 25
    request = await rt.execute(await rt.request())
    approved = await rt.execute(rt.review(request))
    observed = await rt.execute(rt.observation(approved))
    matched = await rt.execute(rt.match(observed, approved, observed))
    command = ApplySelectionRefund(
        **{
            name: getattr(rt.match(matched, approved, observed), name)
            for name in ApplySelectionRefund.__dataclass_fields__
            if name != "match_id"
        },
        match_id=UUID(matched["match_id"]),
    )
    applied = await rt.execute(command)
    assert applied["applied"] is True
    assert await rt.execute(command) == applied
    movements = Base.metadata.tables["financial_movements"]
    obligations = Base.metadata.tables["financial_obligations"]
    with Session(env["pg"]) as db:
        journal = (
            db.execute(
                select(movements)
                .join(
                    obligations, obligations.c.id == movements.c.obligation_id
                )
                .where(obligations.c.order_id == rt.facts["order"].order_id)
            )
            .mappings()
            .all()
        )
    reversals = [m for m in journal if m["movement_type"] == "reversal"]
    assert len(reversals) == 5
    # Frozen client rate is measured from genuine historical attribution.
    assert sum(m["amount_minor"] for m in reversals) == 25000
    maturity = SelectionMaturityService(
        SqlAlchemySelectionMaturityRepository(), ledger, env["clock"]
    )
    async with env["container"].transaction_manager.transaction() as db:
        closed = await maturity.refresh(rt.facts["order"].order_id, session=db)
    assert closed["state"] == "closed" and len(closed["items"]) == 25
    from ugc_bot.infrastructure.db.repositories.selection_view import (
        SqlAlchemySelectionViewRepository,
    )

    async with env["container"].transaction_manager.transaction() as db:
        view = await SqlAlchemySelectionViewRepository().view(
            rt.facts["order"].order_id,
            env["user"].user_id,
            session=db,
            principal=None,
        )
    assert (
        sum(p["delivery_state"] == "refunded" for p in view["positions"]) == 5
    )
    assert view["closure_policy"]["mode"] == "all_positions_resolved"
    assert view["closure_policy"]["closed_at"] is not None
    assert view["closure_policy"]["can_close"] is False
    env["clock"].at += timedelta(days=14)
    async with env["container"].transaction_manager.transaction() as db:
        await maturity.refresh(rt.facts["order"].order_id, session=db)
        wallet = await ledger.repository.read_projection(
            rt.facts["partner"], "RUB", session=db
        )
    assert wallet["available"] == 125000
    assert wallet["pending"] == wallet["hold"] == 0
    assert wallet["cancelled"] == 25000


@pytest.mark.asyncio
async def test_real_partial_accompaniment_refund_keeps_selection_base(
    intake_env,
    monkeypatch,
):
    from tests.helpers.corrections import captured_order
    from ugc_bot.application.accompaniment_refund_ports import (
        ApplyAccompanimentRefund,
        ObserveAccompanimentRefund,
    )
    from ugc_bot.application.collaboration_ports import CollaborationCommand
    from ugc_bot.application.services.accompaniment_refund_service import (
        AccompanimentRefundService,
    )
    from ugc_bot.application.services.collaboration_service import (
        CollaborationService,
    )
    from ugc_bot.application.services.correction_funding_guard import (
        LiveCorrectionFundingGuard,
    )
    from ugc_bot.application.services.obligation_compensation_service import (
        ObligationCompensationService,
    )
    from ugc_bot.infrastructure.db.repositories.accompaniment_refunds import (
        SqlAlchemyAccompanimentRefundRepository,
    )
    from ugc_bot.infrastructure.db.repositories.collaborations import (
        SqlAlchemyCollaborationRepository,
    )
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )
    from ugc_bot.infrastructure.db.repositories.physical_proofs import (
        SqlAlchemyPhysicalProofRepository,
    )

    env = intake_env
    version = "partial-" + uuid4().hex
    rules = RefundRules(
        3600,
        "item_delivered",
        "all_positions_resolved",
        (("assigned", 5000),),
        "retain_earned",
    )
    with Session(env["pg"]) as db, db.begin():
        db.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=env["admin"].user_id,
                approved_at=env["clock"].at - timedelta(days=2),
                effective_from=env["clock"].at - timedelta(days=1),
                refund_window_seconds=3600,
                rules={
                    "terms_reference": "synthetic-approved-terms",
                    "allowed_clients": [str(env["user"].user_id)],
                    "refund_rules": rules.to_document(),
                },
            )
        )
    env["policy"] = version
    facts = await captured_order(env, mode="with_manager")
    delivered = await deliver_original_positions(env, facts, count=1)
    item = delivered[0]
    assignments = Base.metadata.tables["item_assignments"]
    with Session(env["pg"]) as db:
        assignment = (
            db.execute(
                select(assignments).where(assignments.c.paid_item_id == item)
            )
            .mappings()
            .one()
        )
    tm = env["container"].transaction_manager
    lifecycle = CollaborationService(
        SqlAlchemyCollaborationRepository(), env["clock"]
    )
    async with tm.transaction() as db:
        work = await lifecycle.execute(
            CollaborationCommand(
                assignment_id=assignment["assignment_id"],
                action="assign",
                operation_key="terms",
                expected_version=0,
                actor_id=facts["client"],
                due_at=env["clock"].at + timedelta(days=3),
                terms_reference="real-private-brief",
            ),
            session=db,
        )
    ledger = FinancialLedgerService(env["repos"]["financial_ledger_repo"])
    refunds = AccompanimentRefundService(
        SqlAlchemyAccompanimentRefundRepository(),
        ledger,
        SqlAlchemyPhysicalProofRepository(
            "synthetic-bank", "synthetic-account", env["clock"]
        ),
        ObligationCompensationService(ledger),
        env["clock"],
        lifecycle=lifecycle,
    )
    observe = ObserveAccompanimentRefund(
        actor_id=env["admin"].user_id,
        operation_key="actual-report",
        paid_item_id=item,
        original_payment_reference=facts["payment"].external_id,
        amount_minor=60000,
        currency="RUB",
        bank_account_label="synthetic-account",
        bank_reference="real-outgoing-" + uuid4().hex,
        occurred_at=env["clock"].at,
        reason="Actual partial refund",
        evidence_reference="synthetic-bank-evidence",
        evidence_hash="a" * 64,
    )
    guard = LiveCorrectionFundingGuard(SqlAlchemyCorrectionRepository())
    async with tm.transaction() as db:
        observed = await refunds.observe(observe, session=db)
    async with tm.transaction() as db:
        with pytest.raises(ValueError, match="correction_unresolved"):
            await guard.require_forward_clear(item, session=db)
    apply = ApplyAccompanimentRefund(
        actor_id=env["admin"].user_id,
        operation_key="review-real-report",
        observation_id=UUID(observed["observation_id"]),
        paid_item_id=item,
        expected_work_version=work.version,
        reason="Approve exact original stage policy",
        evidence_reference="private-review",
        evidence_hash="b" * 64,
    )
    from sqlalchemy.exc import IntegrityError

    original_append = refunds.repository.append_application

    async def false_absence(fact, *, session):
        await original_append(
            dict(fact, assignment_id=None, stage=None, work_version=0),
            session=session,
        )

    monkeypatch.setattr(refunds.repository, "append_application", false_absence)
    with pytest.raises(
        IntegrityError, match="accompaniment_absence_source_changed"
    ):
        async with tm.transaction() as db:
            await refunds.apply(apply, session=db)
    monkeypatch.setattr(
        refunds.repository, "append_application", original_append
    )
    async with tm.transaction() as db:
        result = await refunds.apply(apply, session=db)
        assert await refunds.apply(apply, session=db) == result
        assert (
            result["customer_refund_minor"] == 60000
            and result["manager_adjustment_minor"] == 0
        )
    async with tm.transaction() as db:
        funding = await guard.load_item(item, session=db)
        assert {line.component: line.net_minor for line in funding} == {
            "selection": 50000,
            "accompaniment": 60000,
        }
        await guard.require_forward_clear(
            item, session=db, components=("selection",)
        )
    from ugc_bot.application.accompaniment_refund_ports import (
        ReviewAccompanimentManagement,
    )

    review = ReviewAccompanimentManagement(
        actor_id=env["admin"].user_id,
        operation_key="explicit-service-continuation",
        application_id=UUID(result["application_id"]),
        paid_item_id=item,
        expected_work_version=work.version,
        decision="continue",
        reason=(
            "Review confirms continuing management scope funded by remaining600"
        ),
        evidence_reference="private:scope-confirmation",
        evidence_hash="c" * 64,
    )
    async with tm.transaction() as db:
        reviewed = await refunds.review_management(review, session=db)
        assert reviewed["work_version"] == work.version + 1
        assert await refunds.review_management(review, session=db) == reviewed
    async with tm.transaction() as db:
        assert (
            await guard.management_refund_disposition(item, session=db)
            == "continue"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("completion", (False,), indirect=True)
async def test_covered_no_referrer_refund_uses_real_audit_and_no_zero_journal(
    completion,
):
    rt, _ = completion
    request = await rt.execute(await rt.request())
    approved = await rt.execute(rt.review(request))
    observed = await rt.execute(rt.observation(approved))
    matched = await rt.execute(rt.match(observed, approved, observed))
    command = ApplySelectionRefund(
        **{
            name: getattr(rt.match(matched, approved, observed), name)
            for name in ApplySelectionRefund.__dataclass_fields__
            if name != "match_id"
        },
        match_id=UUID(matched["match_id"]),
    )
    result = await rt.execute(command)
    assert result["applied"] is True
    assert await rt.execute(command) == result
    with Session(rt.env["pg"]) as db:
        obligations = Base.metadata.tables["financial_obligations"]
        assert not db.execute(
            select(obligations).where(
                obligations.c.order_id == rt.facts["order"].order_id
            )
        ).first()
        assessments = Base.metadata.tables[
            "financial_refund_liability_assessments"
        ]
        components = Base.metadata.tables[
            "financial_refund_component_applications"
        ]
        found = (
            db.execute(
                select(assessments)
                .join(
                    components,
                    components.c.component_application_id
                    == assessments.c.component_application_id,
                )
                .where(
                    components.c.application_id
                    == UUID(result["application_id"])
                )
            )
            .mappings()
            .all()
        )
    assert len(found) == 5
    assert all(
        a["status"] == "covered_absence"
        and a["potential_id"]
        and a["delta_minor"] == 0
        and a["movement_id"] is None
        for a in found
    )


@pytest.mark.asyncio
async def test_delayed_original_marker_requires_an_actual_refund_application(
    completion,
):
    from sqlalchemy import insert
    from sqlalchemy.exc import IntegrityError

    rt, ledger = completion
    request = await rt.execute(await rt.request())
    approved = await rt.execute(rt.review(request))
    observed = await rt.execute(rt.observation(approved))
    matched = await rt.execute(rt.match(observed, approved, observed))
    command = ApplySelectionRefund(
        **{
            name: getattr(rt.match(matched, approved, observed), name)
            for name in ApplySelectionRefund.__dataclass_fields__
            if name != "match_id"
        },
        match_id=UUID(matched["match_id"]),
    )
    tm, env = rt.env["container"].transaction_manager, rt.env
    with pytest.raises(
        IntegrityError, match="correction_original_assessment_source_mismatch"
    ):
        async with tm.transaction() as db:
            scope = await rt.repo.discover_scope(command, session=db)
            await rt.repo.lock_scope(scope, session=db)
            event = await rt.repo.original_capture_event(scope, session=db)
            await _original_client_assessment(
                ledger, env["clock"], env["container"].session_factory
            ).handle(event, session=db, recorded_at=env["clock"].at)
            command_id = uuid4()
            await db.execute(
                insert(
                    Base.metadata.tables["financial_correction_commands"]
                ).values(
                    command_id=command_id,
                    actor_id=env["admin"].user_id,
                    operation_key="forged-marker-without-application",
                    action="ApplySelectionRefund",
                    payload_hash="a" * 64,
                    result={"applied": True},
                    recorded_at=env["clock"].at,
                )
            )
            await rt.repo.record_original_assessment(
                scope, matched, command_id, env["clock"].at, session=db
            )
    with Session(env["pg"]) as db:
        table = Base.metadata.tables["financial_refund_original_assessments"]
        assert not db.execute(
            select(table).where(table.c.case_id == UUID(matched["case_id"]))
        ).first()


@pytest.mark.asyncio
async def test_prework_accompaniment_refund_requires_explicit_absence_review(
    intake_env,
):
    from dataclasses import replace

    from tests.helpers.corrections import captured_order
    from ugc_bot.application.accompaniment_refund_ports import (
        ApplyAccompanimentRefund,
        ObserveAccompanimentRefund,
    )
    from ugc_bot.application.services.accompaniment_refund_service import (
        AccompanimentRefundService,
    )
    from ugc_bot.application.services.obligation_compensation_service import (
        ObligationCompensationService,
    )
    from ugc_bot.infrastructure.db.repositories.accompaniment_refunds import (
        SqlAlchemyAccompanimentRefundRepository,
    )
    from ugc_bot.infrastructure.db.repositories.physical_proofs import (
        SqlAlchemyPhysicalProofRepository,
    )

    env = intake_env
    policy = "prework-" + uuid4().hex
    rules = RefundRules(
        3600, "item_delivered", "all_positions_resolved", (), "manual_review"
    )
    with Session(env["pg"]) as db, db.begin():
        db.add(
            FinancialPolicyVersionModel(
                version=policy,
                approved_by=env["admin"].user_id,
                approved_at=env["clock"].at - timedelta(days=2),
                effective_from=env["clock"].at - timedelta(days=1),
                refund_window_seconds=3600,
                rules=dict(
                    terms_reference="synthetic-approved-terms",
                    allowed_clients=[str(env["user"].user_id)],
                    refund_rules=rules.to_document(),
                ),
            )
        )
    env["policy"] = policy
    facts = await captured_order(env, mode="with_manager")
    item_id = facts["order"].items[0].paid_item_id
    ledger = FinancialLedgerService(env["repos"]["financial_ledger_repo"])
    service = AccompanimentRefundService(
        SqlAlchemyAccompanimentRefundRepository(),
        ledger,
        SqlAlchemyPhysicalProofRepository(
            "synthetic-bank", "synthetic-account", env["clock"]
        ),
        ObligationCompensationService(ledger),
        env["clock"],
    )
    tm = env["container"].transaction_manager
    observe = ObserveAccompanimentRefund(
        actor_id=env["admin"].user_id,
        operation_key="absence-bank:" + uuid4().hex,
        paid_item_id=item_id,
        original_payment_reference=facts["payment"].external_id,
        amount_minor=60000,
        currency="RUB",
        bank_account_label="synthetic-account",
        bank_reference="synthetic-absence-refund:" + uuid4().hex,
        occurred_at=env["clock"].at,
        reason="Actual partial bank refund before any work",
        evidence_reference="synthetic:actual-bank-review",
        evidence_hash="b" * 64,
    )
    async with tm.transaction() as db:
        scope = await service.repository.load_scope(item_id, session=db)
        assert scope.record is None and scope.work_version == 0
        observation = await service.observe(observe, session=db)
    command = ApplyAccompanimentRefund(
        actor_id=observe.actor_id,
        operation_key="absence-review:" + uuid4().hex,
        observation_id=UUID(observation["observation_id"]),
        paid_item_id=item_id,
        expected_work_version=0,
        reason="No creator or manager work exists; customer target reviewed",
        evidence_reference="synthetic:absence-review",
        evidence_hash="c" * 64,
    )
    with pytest.raises(
        ValueError, match="accompaniment_manual_review_required"
    ):
        async with tm.transaction() as db:
            await service.apply(command, session=db)
    command = replace(
        command,
        reviewed_customer_target_minor=60000,
        reviewed_manager_target_minor=0,
    )
    async with tm.transaction() as db:
        result = await service.apply(command, session=db)
    assert (
        result["customer_refund_minor"] == 60000
        and result["manager_adjustment_minor"] == 0
    )
    with Session(env["pg"]) as db:
        applications = Base.metadata.tables[
            "financial_accompaniment_refund_applications"
        ]
        row = (
            db.execute(
                select(applications).where(
                    applications.c.paid_item_id == item_id
                )
            )
            .mappings()
            .one()
        )
        assert (
            row["assignment_id"] is row["stage"] is None
            and row["work_version"] == 0
        )
        originals = Base.metadata.tables["financial_obligations"]
        assert not db.execute(
            select(originals).where(originals.c.paid_item_id == item_id)
        ).first()
    async with tm.transaction() as db:
        assert await service.apply(command, session=db) == result

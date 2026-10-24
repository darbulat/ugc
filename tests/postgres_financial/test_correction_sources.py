"""Actual 30-position captures bind correction sources."""

from dataclasses import replace

import pytest

from tests.helpers.corrections import captured_order, refund_command
from tests.postgres_financial.test_order_intake import intake_env as intake_env

__all__ = ["intake_env"]


@pytest.mark.asyncio
async def test_case_and_manual_observation_routes_use_only_retained_identity(
    intake_env,
):
    from uuid import uuid4

    from tests.helpers.correction_approval_pg import (
        genuine_approved_match as approved_match,
    )
    from ugc_bot.application.correction_ports import (
        MatchSelectionRefund,
        RecordManualRefundObservation,
        ReviewSelectionRefund,
    )
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    facts = await captured_order(env)
    repo = SqlAlchemyCorrectionRepository()
    async with env["container"].transaction_manager.transaction() as db:
        match = await approved_match(env, facts, repo, db)
    common = dict(
        actor_id=env["admin"].user_id,
        operation_key="fresh-review",
        reason="Exact retained scope review",
        expected_version=1,
        expected_source_hash=match["scope"].source_hash,
        evidence_reference="synthetic:review",
        evidence_hash="a" * 64,
        case_id=match["case_id"],
    )
    async with env["container"].transaction_manager.transaction() as db:
        reviewed = await repo.discover_scope(
            ReviewSelectionRefund(**common, decision="approve"), session=db
        )
        exact = await repo.discover_scope(
            MatchSelectionRefund(
                **common,
                intent_id=match["intent_id"],
                observation_id=match["observation_id"],
            ),
            session=db,
        )
        assert (
            reviewed.source_hash
            == exact.source_hash
            == match["scope"].source_hash
        )
        await repo.lock_scope(reviewed, session=db)
        missing = await repo.discover_scope(
            ReviewSelectionRefund(
                **(common | {"case_id": uuid4()}), decision="approve"
            ),
            session=db,
        )
        assert not missing.available and missing.selected_paid_item_ids == ()
    reported = dict(
        actor_id=env["admin"].user_id,
        operation_key="actual-report",
        reason="Synthetic unknown observation",
        case_id=None,
        known_order_id=None,
        known_capture_intent_id=match["scope"].intent_id,
        original_payment_reference="",
        bank_account_label="",
        bank_reference="synthetic:actual",
        amount_minor=None,
        currency=None,
        occurred_at=None,
        reported_component="unknown",
        evidence_reference="synthetic:proof",
        evidence_hash="a" * 64,
        expected_version=None,
    )
    async with env["container"].transaction_manager.transaction() as db:
        observation = await repo.discover_scope(
            RecordManualRefundObservation(**reported), session=db
        )
        assert (
            observation.order_id == facts["order"].order_id
            and not observation.available
        )
        blank = await repo.discover_scope(
            RecordManualRefundObservation(
                **(reported | {"known_capture_intent_id": uuid4()})
            ),
            session=db,
        )
        assert blank.order_id is None and blank.capture_id is None
        await repo.lock_scope(blank, session=db)


def test_missing_or_changed_due_evidence_and_work_grounds_refuse_positives():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from uuid import uuid4

    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    repo = SqlAlchemyCorrectionRepository()
    assert repo._due_hash({}, [], {}) is None
    item = dict(selection_due_at=datetime.now(timezone.utc), quote_payload={})
    assert (
        repo._due_hash(
            item,
            [dict(client_id=uuid4(), result={})],
            dict(advertiser_id=uuid4()),
        )
        is None
    )
    assert (
        repo._source_refusal([SimpleNamespace(due_evidence_hash=None)], [], ())
        == "correction_due_agreement_unavailable"
    )
    item_id = uuid4()
    for kind in ("creator_referral", "management"):
        assert (
            repo._source_refusal(
                [], [dict(kind=kind, paid_item_id=item_id)], (item_id,)
            )
            == "correction_creator_manager_ground_unsupported"
        )


@pytest.mark.asyncio
async def test_early_routing_survives_capture_without_fabricating_or_expanding(
    intake_env,
):
    from tests.postgres_financial.test_order_intake import command, service
    from ugc_bot.application.correction_ports import RequestSelectionRefund
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    requested = command(env)
    actual = await service(env).create(requested)
    cmd = RequestSelectionRefund(
        actor_id=env["user"].user_id,
        operation_key="early",
        reason="Synthetic early factual case",
        order_id=actual.order_id,
        paid_item_ids=(actual.items[0].paid_item_id,),
        expected_source_hash="a" * 64,
    )
    repo = SqlAlchemyCorrectionRepository()
    async with env["container"].transaction_manager.transaction() as db:
        early = await repo.discover_scope(cmd, session=db)
        assert early.capture_id is None and early.bundle is None
        assert early.selected_paid_item_ids == cmd.paid_item_ids
        assert not early.available
        await repo.lock_scope(early, session=db)
    await captured_order(env, existing=(requested, actual))
    async with env["container"].transaction_manager.transaction() as db:
        with pytest.raises(ValueError, match="scope_changed"):
            await repo.load_scope(early, session=db)
        current = await repo.discover_scope(cmd, session=db)
        assert (
            current.available
            and current.selected_paid_item_ids == cmd.paid_item_ids
        )
        assert len(current.bundle.components) == 1


@pytest.mark.asyncio
async def test_assignment_history_changes_source_and_never_becomes_unassigned(
    intake_env,
):
    from datetime import timedelta
    from uuid import uuid4

    from ugc_bot.infrastructure.db.models import ItemAssignmentModel
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    facts = await captured_order(env, mode="with_manager")
    repo = SqlAlchemyCorrectionRepository()
    cmd = refund_command(facts)
    async with env["container"].transaction_manager.transaction() as db:
        before = await repo.discover_scope(cmd, session=db)
        assert before.bundle.total_minor == 250_000
        db.add(
            ItemAssignmentModel(
                assignment_id=uuid4(),
                paid_item_id=cmd.paid_item_ids[0],
                version=1,
                creator_id=facts["stranger"],
                actor_id=env["admin"].user_id,
                valid_from=env["clock"].at - timedelta(days=2),
                valid_to=env["clock"].at - timedelta(days=1),
                reason="Synthetic closed historical assignment",
            )
        )
        await db.flush()
        after = await repo.discover_scope(cmd, session=db)
        assert before.source_hash != after.source_hash
        assert (
            after.bundle.positive_a1_refusal(env["clock"].at)
            == "selection_previously_assigned"
        )
        with pytest.raises(ValueError, match="scope_changed"):
            await repo.load_scope(before, session=db)


@pytest.mark.asyncio
async def test_projection_corruption_preserves_observation_and_fails_authority(
    intake_env,
):
    from uuid import uuid4

    from sqlalchemy import update

    from tests.helpers.correction_approval_pg import (
        genuine_approved_match as approved_match,
    )
    from tests.helpers.corrections import plain
    from ugc_bot.domain.corrections import CorrectionEvent
    from ugc_bot.infrastructure.db.correction_models import TABLE_MAP
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    facts = await captured_order(env)
    repo = SqlAlchemyCorrectionRepository()
    async with env["container"].transaction_manager.transaction() as db:
        assert (
            await repo.command(facts["client"], "missing", session=db) is None
        )
        assert await repo.state_authority(uuid4(), session=db) == (None, True)
        match = await approved_match(env, facts, repo, db)
        current, valid = await repo.state_authority(
            match["case_id"], session=db
        )
        assert valid
        next_state = replace(
            current,
            version=current.version + 1,
            observation_ids=(match["observation_id"],),
            blockers=("awaiting_original_assessment",),
        )
        event = CorrectionEvent(
            event_id=uuid4(),
            case_id=current.case_id,
            version=current.version + 1,
            command_id=match["command_id"],
            source_id=match["observation_id"],
            source_hash=current.source_hash,
            actor_id=env["admin"].user_id,
            reason="Retained actual synthetic observation",
            evidence_reference="synthetic:observation",
            evidence_hash="a" * 64,
            recorded_at=env["clock"].at,
            previous_state_hash=current.payload_hash,
            result_state=next_state,
            result_state_hash=next_state.payload_hash,
        )
        await repo.append_event(event, session=db)
        assert (await repo.state_authority(current.case_id, session=db))[1]
        projection = TABLE_MAP["states"]
        await db.execute(
            update(projection)
            .where(projection.c.case_id == current.case_id)
            .values(
                result_state=plain(
                    replace(next_state, review_status="rejected")
                )
            )
        )
        replayed, valid = await repo.state_authority(
            current.case_id, session=db
        )
        assert not valid and replayed == next_state
        funding = await repo.live_funding(
            match["scope"].selected_paid_item_ids[0], session=db
        )
        assert funding[0].net_minor is None and not funding[0].state_consistent
        assert match["observation_id"] in funding[0].unresolved_observation_ids
        with pytest.raises(ValueError, match="state_unavailable"):
            await repo.append_event(event, session=db)
        with pytest.raises(ValueError, match="fact_writer"):
            await repo.append_fact("states", {}, session=db)
        await db.execute(
            update(projection)
            .where(projection.c.case_id == current.case_id)
            .values(result_state={"corrupt": True})
        )
        assert await repo.state_authority(current.case_id, session=db) == (
            None,
            False,
        )


@pytest.mark.asyncio
async def test_inconsistent_actual_capture_payload_is_explicitly_unavailable(
    intake_env,
):
    from uuid import uuid4

    from sqlalchemy import select, update

    from ugc_bot.infrastructure.db.models import OutboxEventModel
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    facts = await captured_order(env)
    repo = SqlAlchemyCorrectionRepository()
    with pytest.raises(RuntimeError, match="rollback corrupted fixture"):
        async with env["container"].transaction_manager.transaction() as db:
            source = await db.scalar(
                select(OutboxEventModel).where(
                    OutboxEventModel.aggregate_id
                    == str(facts["order"].order_id),
                    OutboxEventModel.event_type
                    == "financial.client_snapshot_requested",
                )
            )
            await db.execute(
                update(OutboxEventModel)
                .where(OutboxEventModel.event_id == source.event_id)
                .values(payload=source.payload | {"payment_id": str(uuid4())})
            )
            scope = await repo.discover_scope(refund_command(facts), session=db)
            assert not scope.available and scope.capture_id is None
            assert (
                scope.unavailable_reason
                == "correction_gross_source_unavailable:ValueError"
            )
            raise RuntimeError("rollback corrupted fixture")


@pytest.mark.asyncio
async def test_observation_survives_savepoint_but_outer_failure_rolls_back(
    intake_env,
):
    from sqlalchemy import text

    from tests.helpers.correction_approval_pg import (
        genuine_approved_match as approved_match,
    )
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    facts = await captured_order(env)
    repo = SqlAlchemyCorrectionRepository()
    with pytest.raises(RuntimeError, match="outer"):
        async with env["container"].transaction_manager.transaction() as db:
            match = await approved_match(env, facts, repo, db)
            with pytest.raises(RuntimeError, match="economic"):
                async with repo.application_savepoint(session=db):
                    raise RuntimeError("economic refusal")
            count = await db.scalar(
                text(
                    (
                        "SELECT count(*) FROM financial_refund_observations "
                        "WHERE observation_id=:id"
                    )
                ),
                {"id": match["observation_id"]},
            )
            assert count == 1
            raise RuntimeError("outer rollback")
    async with env["container"].transaction_manager.transaction() as db:
        assert (
            await db.scalar(
                text(
                    (
                        "SELECT count(*) FROM financial_refund_observations "
                        "WHERE observation_id=:id"
                    )
                ),
                {"id": match["observation_id"]},
            )
            == 0
        )


@pytest.mark.asyncio
async def test_selected_digest_is_independent_of_the_current_actor(
    intake_env,
):
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    facts = await captured_order(env)
    repo = SqlAlchemyCorrectionRepository()
    command = refund_command(facts)
    async with env["container"].transaction_manager.transaction() as db:
        source = await repo.discover_scope(command, session=db)
        admin = await repo.discover_scope(
            replace(command, actor_id=env["admin"].user_id), session=db
        )
        other = await repo.discover_scope(
            replace(command, paid_item_ids=command.paid_item_ids[:1]),
            session=db,
        )
        assert source.available, source.unavailable_reason
        assert source.bundle.total_minor == 250_000
        assert len(source.bundle.components) == 5
        assert source.source_hash == admin.source_hash
        assert source.source_hash != other.source_hash
        await repo.lock_scope(source, session=db)
        assert await repo.load_scope(source, session=db) == source
        assert source.bundle.positive_a1_refusal(env["clock"].at) is None
        assert facts["partner"] in source.wallet_user_ids


@pytest.mark.asyncio
async def test_missing_foreign_and_routing_sources_never_expand_to_all_order(
    intake_env,
):
    from uuid import uuid4

    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    facts = await captured_order(env)
    repo = SqlAlchemyCorrectionRepository()
    command = refund_command(facts)
    async with env["container"].transaction_manager.transaction() as db:
        missing = await repo.discover_scope(
            replace(command, paid_item_ids=(uuid4(),)), session=db
        )
        assert not missing.available and missing.bundle is None
        assert missing.selected_paid_item_ids != ()
        absent = await repo.discover_scope(
            replace(command, order_id=uuid4()), session=db
        )
        assert not absent.available and absent.capture_id is None
        own = await repo.discover_scope(command, session=db)
        foreign_client = await repo.discover_scope(
            replace(command, actor_id=facts["stranger"]), session=db
        )
        assert foreign_client.client_id == facts["client"]
        assert not foreign_client.available
        with pytest.raises(ValueError, match="routing"):
            await repo.load_scope(
                replace(own, selected_paid_item_ids=()), session=db
            )


@pytest.mark.asyncio
async def test_unselected_observation_retries_committed_manager_change(
    intake_env,
):
    from sqlalchemy import insert

    from tests.helpers.corrections import manual_observation
    from ugc_bot.infrastructure.db.base import Base
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    facts = await captured_order(env)
    repo = SqlAlchemyCorrectionRepository()
    command = manual_observation(env, facts)
    async with env["container"].transaction_manager.transaction() as db:
        old = await repo.discover_scope(command, session=db)
    assert not old.available and old.selected_paid_item_ids == ()
    assert facts["stranger"] not in old.prospective_user_ids
    async with env["container"].transaction_manager.transaction() as db:
        await db.execute(
            insert(Base.metadata.tables["manager_orders"]).values(
                user_id=facts["stranger"],
                order_id=facts["order"].order_id,
                created_at=env["clock"].at,
            )
        )
    async with env["container"].transaction_manager.transaction() as db:
        current = await repo.discover_scope(command, session=db)
        assert facts["stranger"] in current.prospective_user_ids
        assert not current.available and current.selected_paid_item_ids == ()
        with pytest.raises(ValueError, match="scope_changed_retry_required"):
            await repo.lock_scope(old, session=db)


@pytest.mark.asyncio
async def test_unselected_observation_retries_real_capture_without_new_users(
    intake_env,
):
    from tests.helpers.corrections import manual_observation
    from tests.postgres_financial.test_order_intake import command, service
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    request = command(env)
    actual = await service(env).create(request)
    reported = manual_observation(env, {"order": actual})
    repo = SqlAlchemyCorrectionRepository()
    async with env["container"].transaction_manager.transaction() as db:
        old = await repo.discover_scope(reported, session=db)
    await captured_order(env, referred=False, existing=(request, actual))
    async with env["container"].transaction_manager.transaction() as db:
        current = await repo.discover_scope(reported, session=db)
        assert current.prospective_user_ids == old.prospective_user_ids
        assert current.wallet_user_ids == old.wallet_user_ids == ()
        assert not current.available and current.selected_paid_item_ids == ()
        with pytest.raises(ValueError, match="scope_changed_retry_required"):
            await repo.load_scope(old, session=db)
        assert await repo.load_scope(current, session=db) == current
        await repo.lock_scope(current, session=db)


@pytest.mark.asyncio
async def test_unselected_observation_retries_manager_added_after_first_barrier(
    intake_env,
):
    import asyncio

    from sqlalchemy import event, insert, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from tests.helpers.corrections import manual_observation
    from ugc_bot.infrastructure.db.base import Base
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )
    from ugc_bot.infrastructure.db.repositories.financial_items import (
        SqlAlchemyFinancialItemRepository,
    )
    from ugc_bot.infrastructure.db.session import SessionTransactionManager

    env = intake_env
    facts = await captured_order(env)
    repo = SqlAlchemyCorrectionRepository()
    command = manual_observation(env, facts)
    async with env["container"].transaction_manager.transaction() as db:
        old = await repo.discover_scope(command, session=db)
    engine = create_async_engine(env["pg"].url, pool_size=2, max_overflow=0)
    tm = SessionTransactionManager(
        async_sessionmaker(engine, expire_on_commit=False)
    )
    writer_holds_order = asyncio.Event()
    downstream_started = asyncio.Event()
    pids = set()
    late_user_locks = []

    def observe_sql(
        connection, cursor, statement, parameters, context, executemany
    ):
        if (
            "pg_advisory_xact_lock(hashtextextended" in statement
            and writer_holds_order.is_set()
        ):
            downstream_started.set()
        if (
            downstream_started.is_set()
            and "FROM users" in statement
            and "FOR " in statement
        ):
            late_user_locks.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", observe_sql)

    async def writer():
        async with tm.transaction() as db:
            pids.add(await db.scalar(text("SELECT pg_backend_pid()")))
            await SqlAlchemyFinancialItemRepository().lock_order(
                facts["order"].order_id, session=db
            )
            writer_holds_order.set()
            await asyncio.wait_for(downstream_started.wait(), timeout=5)
            await db.execute(
                insert(Base.metadata.tables["manager_orders"]).values(
                    user_id=facts["stranger"],
                    order_id=facts["order"].order_id,
                    created_at=env["clock"].at,
                )
            )

    async def locker():
        await asyncio.wait_for(writer_holds_order.wait(), timeout=5)
        async with tm.transaction() as db:
            pids.add(await db.scalar(text("SELECT pg_backend_pid()")))
            with pytest.raises(
                ValueError, match="scope_changed_retry_required"
            ):
                await repo.lock_scope(old, session=db)

    try:
        await asyncio.gather(writer(), locker())
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", observe_sql)
        await engine.dispose()
    assert len(pids) == 2
    assert not late_user_locks
    async with env["container"].transaction_manager.transaction() as db:
        current = await repo.discover_scope(command, session=db)
        assert facts["stranger"] in current.prospective_user_ids
        assert not current.available and current.selected_paid_item_ids == ()


@pytest.mark.asyncio
async def test_unselected_observation_retries_new_case_and_request_routing(
    intake_env,
):
    from uuid import uuid4

    from tests.helpers.corrections import manual_observation, plain
    from ugc_bot.application.correction_ports import correction_command_hash
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    facts = await captured_order(env)
    repo = SqlAlchemyCorrectionRepository()
    case_id = uuid4()
    report = replace(manual_observation(env, facts), case_id=case_id)
    async with env["container"].transaction_manager.transaction() as db:
        absent_case = await repo.discover_scope(report, session=db)
        await repo.save_command(
            report,
            correction_command_hash(report),
            {"synthetic": True},
            session=db,
        )
        command = await repo.command(
            report.actor_id, report.operation_key, session=db
        )
        await repo.append_fact(
            "cases",
            dict(
                case_id=case_id,
                command_id=command["command_id"],
                order_id=facts["order"].order_id,
                client_id=facts["client"],
                recorded_at=env["clock"].at,
            ),
            session=db,
        )
    async with env["container"].transaction_manager.transaction() as db:
        with pytest.raises(ValueError, match="scope_changed_retry_required"):
            await repo.load_scope(absent_case, session=db)
        known_case = await repo.discover_scope(report, session=db)
        assert (
            known_case.selected_paid_item_ids == () and not known_case.available
        )
        assert (
            known_case.prospective_user_ids == absent_case.prospective_user_ids
        )
        assert await repo.load_scope(known_case, session=db) == known_case
        request = refund_command(facts)
        source = await repo.discover_scope(request, session=db)
        await repo.save_command(
            request,
            correction_command_hash(request),
            {"synthetic": True},
            session=db,
        )
        command = await repo.command(
            request.actor_id, request.operation_key, session=db
        )
        await repo.append_fact(
            "requests",
            dict(
                request_id=uuid4(),
                case_id=case_id,
                command_id=command["command_id"],
                order_id=source.order_id,
                client_id=source.client_id,
                paid_item_ids=[str(i) for i in source.selected_paid_item_ids],
                source_hash=source.source_hash,
                bundle=plain(source.bundle)["components"],
                recorded_at=env["clock"].at,
            ),
            session=db,
        )
    async with env["container"].transaction_manager.transaction() as db:
        with pytest.raises(ValueError, match="scope_changed_retry_required"):
            await repo.lock_scope(known_case, session=db)
        assert (
            known_case.selected_paid_item_ids == ()
            and known_case.bundle is None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("known_client", [False, True])
@pytest.mark.parametrize("captured", [False, True])
async def test_case_only_report_reloads_nullable_facts_without_inference(
    intake_env, known_client, captured
):
    from tests.helpers.corrections import retain_case_only_report, rows
    from tests.postgres_financial.test_order_intake import command, service
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    if captured:
        facts = await captured_order(env)
    else:
        actual = await service(env).create(command(env))
        facts = {"order": actual, "client": env["user"].user_id}
    repo = SqlAlchemyCorrectionRepository()
    report = await retain_case_only_report(
        env, facts, repo, known_client=known_client
    )
    async with env["container"].transaction_manager.transaction() as db:
        scope = await repo.discover_scope(report, session=db)
        assert not scope.available and scope.selected_paid_item_ids == ()
        assert scope.order_id is scope.client_id is scope.intent_id is None
        assert scope.capture_id is scope.payment_id is scope.bundle is None
        assert scope.wallet_user_ids == () and scope.source_hash is not None
        assert set(scope.prospective_user_ids) == (
            {report.actor_id, facts["client"]}
            if known_client
            else {report.actor_id}
        )
        assert await repo.load_scope(scope, session=db) == scope
        await repo.lock_scope(scope, session=db)
        assert await repo.load_scope(scope, session=db) == scope
    stored = rows(env, "financial_correction_cases", case_id=report.case_id)[0]
    assert stored["client_id"] == (facts["client"] if known_client else None)
    assert stored["order_id"] == (
        facts["order"].order_id if known_client else None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("known_client", [False, True])
@pytest.mark.parametrize("captured", [False, True])
async def test_case_only_report_retries_new_request_without_route_adoption(
    intake_env, known_client, captured
):
    from uuid import uuid4

    from tests.helpers.corrections import (
        manual_observation,
        plain,
        retain_case_only_report,
        rows,
    )
    from tests.postgres_financial.test_order_intake import command, service
    from ugc_bot.application.correction_ports import correction_command_hash
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    if captured:
        facts = await captured_order(env)
    else:
        actual = await service(env).create(command(env))
        facts = {"order": actual, "client": env["user"].user_id}
    repo = SqlAlchemyCorrectionRepository()
    report = await retain_case_only_report(
        env, facts, repo, known_client=known_client
    )
    async with env["container"].transaction_manager.transaction() as db:
        old = await repo.discover_scope(report, session=db)
        assert old.order_id is None and old.selected_paid_item_ids == ()
        assert not old.available
    async with env["container"].transaction_manager.transaction() as db:
        request = refund_command(facts)
        source = await repo.discover_scope(request, session=db)
        if captured:
            assert source.available and source.bundle is not None
            source_hash, bundle = (
                source.source_hash,
                plain(source.bundle)["components"],
            )
        else:
            assert (
                not source.available
                and source.capture_id is source.bundle is None
            )
            unresolved = await repo.discover_scope(
                manual_observation(env, facts), session=db
            )
            assert (
                not unresolved.available and unresolved.source_hash is not None
            )
            source_hash, bundle = unresolved.source_hash, None
        request = replace(request, expected_source_hash=source_hash)
        await repo.save_command(
            request,
            correction_command_hash(request),
            {"synthetic": True},
            session=db,
        )
        receipt = await repo.command(
            request.actor_id, request.operation_key, session=db
        )
        await repo.append_fact(
            "requests",
            dict(
                request_id=uuid4(),
                case_id=report.case_id,
                command_id=receipt["command_id"],
                order_id=request.order_id,
                client_id=request.actor_id,
                paid_item_ids=[str(i) for i in request.paid_item_ids],
                source_hash=source_hash,
                bundle=bundle,
                recorded_at=env["clock"].at,
            ),
            session=db,
        )
    async with env["container"].transaction_manager.transaction() as db:
        with pytest.raises(ValueError, match="scope_changed_retry_required"):
            await repo.load_scope(old, session=db)
        with pytest.raises(ValueError, match="scope_changed_retry_required"):
            await repo.lock_scope(old, session=db)
        assert (
            old.order_id
            is old.client_id
            is old.capture_id
            is old.bundle
            is None
        )
        assert old.selected_paid_item_ids == () and not old.available
        fresh = await repo.discover_scope(report, session=db)
        assert fresh.order_id == facts["order"].order_id
        assert fresh.client_id == facts["client"]
        assert fresh.selected_paid_item_ids == tuple(
            sorted(request.paid_item_ids)
        )
        assert fresh.available is captured
        if not captured:
            assert fresh.capture_id is fresh.payment_id is fresh.bundle is None
    if not known_client:
        assert (
            rows(env, "financial_correction_cases", case_id=report.case_id)[0][
                "client_id"
            ]
            is None
        )
    assert (
        rows(env, "financial_correction_requests", case_id=report.case_id)[0][
            "bundle"
        ]
        == bundle
    )

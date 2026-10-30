"""Actual PostgreSQL approval and retained-awaiting-match provenance."""

import pytest
from sqlalchemy.exc import DBAPIError

from tests.helpers.correction_runtime_pg import runtime
from tests.helpers.corrections import approved_match
from tests.postgres_financial.test_order_intake import intake_env as intake_env

__all__ = ["intake_env"]


@pytest.mark.asyncio
async def test_retained_awaiting_match_requires_real_review_without_application(
    intake_env,
):
    """A missing match guard admits synthetic Request-as-Review provenance."""
    rt = await runtime(intake_env)
    with pytest.raises(DBAPIError, match="correction_match_authority_invalid"):
        async with rt.env["container"].transaction_manager.transaction() as db:
            await approved_match(rt.env, rt.facts, rt.repo, db)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_genuine_captured_review_links_retained_match(
    intake_env, platform
):
    from uuid import UUID

    from tests.helpers.correction_approval_pg import (
        approval_runtime,
        create_match,
    )

    rt = await approval_runtime(intake_env)
    requested, approved, observed, matched = await create_match(
        rt, platform=platform
    )
    approval = rt.approval_rows(
        "approvals", approval_id=UUID(approved["approval_id"])
    )[0]
    assert approval["capture_id"] != rt.facts["invoice_id"]
    assert approval["request_id"] == UUID(requested["request_id"])
    assert matched["approval_id"] == approved["approval_id"]
    assert matched["application_status"] == "awaiting_assessment"
    assert matched["applied"] is False
    assert rt.approval_rows(
        "match_approvals", match_id=UUID(matched["match_id"])
    ) == [
        {
            "match_id": UUID(matched["match_id"]),
            "approval_id": UUID(approved["approval_id"]),
        }
    ]
    assert not rt.rows("applications", intent_id=UUID(approved["intent_id"]))
    assert rt.claims(approved["intent_id"])[0]["observation_id"] == UUID(
        observed["observation_id"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("nullable", [False, True])
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_genuine_early_invoice_keeps_original_intent_and_owner(
    intake_env,
    nullable,
    platform,
):
    from uuid import UUID

    from tests.helpers.correction_approval_pg import (
        approval_runtime,
        capture_pending,
    )

    rt = await approval_runtime(intake_env, early=True)
    early = await rt.execute(
        rt.observation(
            original_payment_reference="provider-"
            + str(rt.facts["order"].order_id),
            known_order_id=None if nullable else rt.facts["order"].order_id,
            known_capture_intent_id=None
            if nullable
            else rt.facts["invoice_id"],
        )
    )
    case_id, intent_id = UUID(early["case_id"]), UUID(early["intent_id"])
    retained = {
        kind: rt.rows(kind, case_id=case_id)
        for kind in ("cases", "intents", "observations")
    }
    claims = rt.claims(early["intent_id"])
    assert retained["intents"][0]["request_id"] is None
    assert retained["intents"][0]["capture_id"] is None
    if nullable:
        assert retained["cases"][0]["client_id"] is None
        assert retained["cases"][0]["order_id"] is None
    await capture_pending(rt)
    requested = await rt.execute(await rt.request(existing_case_id=case_id))
    approved = await rt.execute(
        rt.review(requested),
        principal=rt.principal(rt.env["admin"].user_id, platform),
    )
    matched = await rt.execute(rt.match(approved, approved, early))
    assert matched["application_status"] == "awaiting_assessment"
    assert approved["intent_id"] == early["intent_id"]
    assert {
        kind: rt.rows(kind, case_id=case_id) for kind in retained
    } == retained
    assert rt.claims(early["intent_id"]) == claims
    assert (
        rt.approval_rows("approvals", intent_id=intent_id)[0]["capture_id"]
        is not None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("referred", [True, False])
async def test_genuine_new_approval_preserves_original_application_guards(
    intake_env, referred
):
    from tests.helpers.correction_approval_pg import genuine_approved_match
    from tests.helpers.corrections import (
        append_application,
        assess_original,
        captured_order,
        rows,
    )
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = intake_env
    facts = await captured_order(env, referred=referred)
    from ugc_bot.infrastructure.db.repositories.financial_capture import (
        intent_id,
    )

    facts["invoice_id"] = intent_id(facts["order"].order_id)
    await assess_original(env, facts)
    repo = SqlAlchemyCorrectionRepository()
    async with env["container"].transaction_manager.transaction() as db:
        match = await genuine_approved_match(env, facts, repo, db)
        async with repo.application_savepoint(session=db):
            await append_application(env, facts, repo, match, db)
    assert (
        len(
            rows(
                env, "financial_refund_applications", match_id=match["match_id"]
            )
        )
        == 1
    )
    async with env["container"].transaction_manager.transaction() as db:
        funding = await repo.live_funding(
            match["scope"].selected_paid_item_ids[0], session=db
        )
    assert funding[0].net_minor == 0
    assert funding[0].state_consistent


@pytest.mark.asyncio
@pytest.mark.parametrize("old_match", [False, True])
@pytest.mark.parametrize("legacy_fault", [False, True])
async def test_archived_writer_upgrade_preserves_history_without_backfill(
    old_match,
    legacy_fault,
):
    import os
    from dataclasses import replace
    from uuid import UUID

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import insert, text

    from tests.helpers.correction_approval_pg import (
        ApprovalRuntime,
        archived_command,
        installed_approval_guard,
    )
    from tests.helpers.correction_legacy_writer import (
        archived_correction_writer,
        install_archived_correction_schema,
    )
    from tests.helpers.financial_environment import (
        isolated_financial_database,
        upgrade_financial_schema,
    )
    from ugc_bot.application.services.correction_service import (
        CorrectionService,
    )
    from ugc_bot.infrastructure.db.correction_approval_models import TABLE_MAP
    from ugc_bot.infrastructure.db.migrations.versions import (
        financial_refund_approvals_a1 as migration,
    )
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="campaign_drafts_v1",
    ) as engine:
        install_archived_correction_schema(engine)
        with engine.connect() as db:
            constraint = db.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid='financial_correction_requests'::regclass "
                    "AND conname='ck_correction_request_items'"
                )
            )
            guard = db.scalar(
                text(
                    "SELECT prosrc FROM pg_proc WHERE "
                    "oid='correction_check_application()'::regprocedure"
                )
            )
            assert "30" in constraint and "200" not in constraint
            assert "covered_zero" not in guard
        async for env in intake_env.__wrapped__(engine):
            rt = ApprovalRuntime.from_runtime(await runtime(env))
            with archived_correction_writer() as writer:
                rt.repo = writer.repository.SqlAlchemyCorrectionRepository()
                rt.service = writer.service.CorrectionService(
                    rt.repo, rt.proofs, env["clock"]
                )
                from tests.helpers.corrections import refund_command

                request = archived_command(writer, refund_command(rt.facts))
                async with env[
                    "container"
                ].transaction_manager.transaction() as db:
                    scope = await rt.repo.discover_scope(request, session=db)
                requested = await rt.execute(
                    replace(request, expected_source_hash=scope.source_hash)
                )
                review = rt.review(requested)
                approved = await rt.execute(archived_command(writer, review))
                observed = await rt.execute(
                    archived_command(writer, rt.observation(approved))
                )
                report = observed
                if old_match:
                    observed = await rt.execute(
                        archived_command(
                            writer, rt.match(observed, approved, observed)
                        )
                    )
                case_id = UUID(approved["case_id"])
                if legacy_fault:
                    # Declared damaged history, separate from genuine controls.
                    genuine = rt.rows("intents", case_id=case_id)
                    with engine.begin() as db:
                        enabled = text(
                            "SELECT tgenabled FROM pg_trigger WHERE "
                            "tgrelid='financial_refund_intents'::regclass "
                            "AND tgname='correction_fact_immutable'"
                        )
                        assert db.scalar(enabled) == "O"
                        db.execute(
                            text(
                                "ALTER TABLE financial_refund_intents "
                                "DISABLE TRIGGER correction_fact_immutable"
                            )
                        )
                        db.execute(
                            text(
                                "UPDATE financial_refund_intents "
                                "SET request_id=NULL WHERE intent_id=:id"
                            ),
                            {"id": UUID(approved["intent_id"])},
                        )
                        db.execute(
                            text(
                                "ALTER TABLE financial_refund_intents "
                                "ENABLE TRIGGER correction_fact_immutable"
                            )
                        )
                        assert db.scalar(enabled) == "O"
                    assert rt.rows("intents", case_id=case_id) == [
                        genuine[0] | {"request_id": None}
                    ]
                historical = {
                    kind: rt.rows(kind, case_id=case_id)
                    for kind in (
                        "cases",
                        "requests",
                        "intents",
                        "observations",
                        "matches",
                        "events",
                    )
                }
                commands = {
                    row["command_id"]: rt.rows(
                        "commands", command_id=row["command_id"]
                    )
                    for values in historical.values()
                    for row in values
                }
                claims = rt.claims(approved["intent_id"])
            old_guard = installed_approval_guard(engine)
            upgrade_financial_schema(
                engine, target_revision="financial_refund_approvals_a1"
            )
            with (
                engine.begin() as db,
                Operations.context(MigrationContext.configure(db)),
            ):
                migration.downgrade()
            assert installed_approval_guard(engine) == old_guard
            with (
                engine.begin() as db,
                Operations.context(MigrationContext.configure(db)),
            ):
                migration.upgrade()
            assert rt.approval_rows("approvals", case_id=case_id) == []
            assert rt.approval_rows("match_approvals") == []
            assert {
                kind: rt.rows(kind, case_id=case_id) for kind in historical
            } == historical
            rt.repo = SqlAlchemyCorrectionRepository()
            rt.service = CorrectionService(rt.repo, rt.proofs, env["clock"])
            if legacy_fault:
                with pytest.raises(ValueError, match="correction_"):
                    await rt.execute(rt.match(observed, approved, report))
                assert {
                    kind: rt.rows(kind, case_id=case_id) for kind in historical
                } == historical
                assert rt.claims(approved["intent_id"]) == claims
                if old_match:
                    with (
                        pytest.raises(
                            DBAPIError,
                            match="correction_match_authority_invalid",
                        ),
                        engine.begin() as db,
                    ):
                        db.execute(
                            text("SELECT * FROM correction_match_capsule(:id)"),
                            {"id": UUID(observed["match_id"])},
                        )
                continue
            fresh = await rt.execute(rt.match(observed, approved, report))
            assert "approval_id" not in fresh
            assert fresh["application_status"] == "awaiting_assessment"
            assert rt.approval_rows("match_approvals") == []
            assert rt.approval_rows("approvals", case_id=case_id) == []
            for kind, values in historical.items():
                now = rt.rows(kind, case_id=case_id)
                assert all(row in now for row in values)
            for command_id, values in commands.items():
                assert rt.rows("commands", command_id=command_id) == values
            assert rt.claims(approved["intent_id"]) == claims
            # A later link cannot relabel an immutable legacy match receipt.
            replacement = await rt.execute(rt.review(fresh))
            with pytest.raises(
                DBAPIError, match="correction_match_authority_invalid"
            ):
                async with env[
                    "container"
                ].transaction_manager.transaction() as db:
                    await db.execute(
                        insert(TABLE_MAP["match_approvals"]).values(
                            match_id=UUID(fresh["match_id"]),
                            approval_id=UUID(replacement["approval_id"]),
                        )
                    )
            assert rt.approval_rows("match_approvals") == []


def repayment_guard_signature(engine):
    from sqlalchemy import text

    with engine.connect() as db:
        return dict(
            functions=db.execute(
                text(
                    "SELECT proname,prosrc FROM pg_proc "
                    "WHERE pronamespace=current_schema()::regnamespace "
                    "AND strpos(proname,'repayment_')=1 ORDER BY proname"
                )
            ).all(),
            triggers=db.execute(
                text(
                    "SELECT c.relname,t.tgname,t.tgdeferrable,"
                    "t.tginitdeferred,t.tgtype FROM pg_trigger t "
                    "JOIN pg_class c ON c.oid=t.tgrelid "
                    "WHERE c.relnamespace=current_schema()::regnamespace "
                    "AND NOT t.tgisinternal "
                    "AND strpos(t.tgname,'repayment_')=1 "
                    "ORDER BY c.relname,t.tgname"
                )
            ).all(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("construction", ["full", "old_then_companion"])
async def test_metadata_final_guard_matches_migration_and_repeated_creation(
    construction,
):
    import os

    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from tests.helpers.correction_approval_pg import installed_approval_guard
    from tests.helpers.financial_environment import isolated_financial_database
    from ugc_bot.infrastructure.db.base import Base
    from ugc_bot.infrastructure.db.correction_approval_models import (
        TABLES as NEW,
    )
    from ugc_bot.infrastructure.db.correction_models import TABLES as OLD

    url = os.environ["FINANCIAL_TEST_DATABASE_URL"]
    with isolated_financial_database(url) as migrated:
        expected = installed_approval_guard(migrated)
        repayment_expected = repayment_guard_signature(migrated)
        assert repayment_expected["functions"]
        assert len(repayment_expected["triggers"]) == 6
    with isolated_financial_database(
        url, target_revision="financial_refund_approvals_a1"
    ) as companion:
        historical_boundary = installed_approval_guard(companion)
    with isolated_financial_database(
        url, target_revision="campaign_drafts_v1"
    ) as engine:
        if construction == "full":
            Base.metadata.create_all(engine)
        else:
            Base.metadata.create_all(engine, tables=OLD)
            with engine.connect() as db:
                assert "correction_match_capsule" not in db.scalar(
                    text(
                        "SELECT prosrc FROM pg_proc WHERE "
                        "oid='correction_check_application()'::regprocedure"
                    )
                )
            Base.metadata.create_all(engine, tables=NEW)
        first = installed_approval_guard(engine)
        assert first == (
            expected if construction == "full" else historical_boundary
        )
        Base.metadata.create_all(engine)
        assert installed_approval_guard(engine) == expected
        assert repayment_guard_signature(engine) == repayment_expected
        Base.metadata.create_all(engine)
        assert installed_approval_guard(engine) == expected
        assert repayment_guard_signature(engine) == repayment_expected
        async for env in intake_env.__wrapped__(engine):
            rt = await runtime(env)
            with pytest.raises(
                DBAPIError, match="correction_match_authority_invalid"
            ):
                async with env[
                    "container"
                ].transaction_manager.transaction() as db:
                    await approved_match(env, rt.facts, rt.repo, db)
        with Session(engine) as db, db.begin():
            for table in NEW:
                for statement in (
                    f"UPDATE {table.name} SET "
                    f"{list(table.c)[0].name}={list(table.c)[0].name}",
                    f"DELETE FROM {table.name}",
                    f"TRUNCATE {table.name} CASCADE",
                ):
                    with (
                        pytest.raises(
                            DBAPIError, match="correction_fact_immutable"
                        ),
                        db.begin_nested(),
                    ):
                        db.execute(text(statement))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tamper",
    [
        "nil",
        "capture_is_invoice",
        "source_hash",
        "amount",
        "currency",
        "empty_bundle",
        "duplicate_bundle",
        "partial_component",
        "due_hash",
        "capsule_invoice",
        "capsule_payment",
        "capsule_time",
        "capsule_quote",
        "capsule_terms",
        "capsule_grounds",
        "capsule_selected",
    ],
)
async def test_actual_approval_rejects_forged_seals_and_partial_bundles(
    intake_env, tamper
):
    from uuid import UUID

    from tests.helpers.correction_approval_pg import (
        alter_fact,
        approval_runtime,
    )

    rt = await approval_runtime(intake_env)
    requested = await rt.execute(await rt.request())
    before = rt.rows("events", case_id=UUID(requested["case_id"]))

    def mutate(value):
        attacks = {
            "nil": (("approval_id",), UUID(int=0)),
            "capture_is_invoice": (("capture_id",), rt.facts["invoice_id"]),
            "source_hash": (("source_hash",), "f" * 64),
            "amount": (("amount_minor",), 249999),
            "currency": (("currency",), "USD"),
            "empty_bundle": (("bundle",), []),
            "duplicate_bundle": (("bundle", 1), value["bundle"][0]),
            "partial_component": (("bundle", 0, "gross_minor"), 49999),
            "due_hash": (("bundle", 0, "due_evidence_hash"), "f" * 64),
            "capsule_invoice": (
                ("source_capsule", "invoice", "payload", "account"),
                "foreign-bank",
            ),
            "capsule_payment": (
                ("source_capsule", "payment", "external_id"),
                "foreign-reference",
            ),
            "capsule_time": (
                ("source_capsule", "captured_at"),
                "2020-01-01T00:00:00+00:00",
            ),
            "capsule_quote": (("source_capsule", "quote_key"), "foreign-quote"),
            "capsule_terms": (
                ("source_capsule", "terms_reference"),
                "foreign-terms",
            ),
            "capsule_grounds": (
                ("source_capsule", "ground_ids"),
                [str(UUID(int=1))],
            ),
            "capsule_selected": (
                ("source_capsule", "selected_paid_item_ids"),
                [],
            ),
        }
        path, replacement = attacks[tamper]
        target = value
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = replacement
        return value

    with alter_fact(rt, "approvals", mutate), pytest.raises(DBAPIError):
        await rt.execute(rt.review(requested))
    assert (
        rt.approval_rows("approvals", case_id=UUID(requested["case_id"])) == []
    )
    assert rt.rows("events", case_id=UUID(requested["case_id"])) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tamper",
    [
        "missing_link",
        "wrong_approval",
        "nil_link",
        "wrong_order",
        "wrong_review",
        "source",
        "amount",
    ],
)
async def test_actual_awaiting_match_rejects_missing_or_inconsistent_binding(
    intake_env, tamper
):
    from uuid import UUID

    from tests.helpers.correction_approval_pg import (
        alter_fact,
        approval_runtime,
    )

    rt = await approval_runtime(intake_env)
    approved = await rt.approved()
    observed = await rt.execute(rt.observation(approved))
    case_id = UUID(approved["case_id"])
    claims = rt.claims(approved["intent_id"])
    before = rt.rows("events", case_id=case_id)
    old_links = rt.approval_rows("match_approvals")
    kind = (
        "match_approvals"
        if tamper in ("missing_link", "wrong_approval", "nil_link")
        else "matches"
    )

    def mutate(value):
        if tamper == "missing_link":
            return None
        if tamper in ("wrong_approval", "nil_link"):
            value["approval_id"] = UUID(
                int=1 if tamper == "wrong_approval" else 0
            )
        elif tamper == "wrong_order":
            value["order_id"] = UUID(int=1)
        elif tamper == "wrong_review":
            value["review_version"] = 1
        elif tamper == "source":
            value["source_hash"] = "f" * 64
        else:
            value["amount_minor"] = 50000
        return value

    with alter_fact(rt, kind, mutate), pytest.raises(DBAPIError):
        await rt.execute(rt.match(observed, approved, observed))
    assert rt.rows("matches", case_id=case_id) == []
    assert rt.approval_rows("match_approvals") == old_links
    assert rt.rows("events", case_id=case_id) == before
    assert rt.claims(approved["intent_id"]) == claims


@pytest.mark.asyncio
async def test_repeated_matches_preserve_original_owner_and_review_history(
    intake_env,
):
    from uuid import UUID

    from tests.helpers.correction_approval_pg import (
        approval_runtime,
        create_match,
    )

    rt = await approval_runtime(intake_env)
    _, approved, observed, first = await create_match(rt)
    owner = rt.claims(approved["intent_id"])
    report = rt.rows(
        "observations", observation_id=UUID(observed["observation_id"])
    )[0]
    repeated_report = await rt.execute(
        rt.observation(first, bank_reference=report["bank_reference"])
    )
    repeated = await rt.execute(
        rt.match(repeated_report, approved, repeated_report)
    )
    assert repeated["approval_id"] == first["approval_id"]
    assert rt.claims(approved["intent_id"]) == owner
    old_links = rt.approval_rows("match_approvals")
    rejected = await rt.execute(rt.review(repeated, decision="reject"))
    with pytest.raises(ValueError, match="correction_approved_review_required"):
        await rt.execute(rt.match(rejected, approved, repeated_report))
    fresh = await rt.execute(rt.review(rejected))
    last = await rt.execute(rt.match(fresh, fresh, repeated_report))
    assert last["approval_id"] != first["approval_id"]
    assert all(row in rt.approval_rows("match_approvals") for row in old_links)
    assert (
        len(
            rt.approval_rows("approvals", intent_id=UUID(approved["intent_id"]))
        )
        == 2
    )
    assert rt.claims(approved["intent_id"]) == owner


@pytest.mark.asyncio
@pytest.mark.parametrize("with_match", [False, True])
async def test_populated_approval_downgrade_preserves_guard_and_tables(
    intake_env, with_match
):
    from uuid import UUID

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    from tests.helpers.correction_approval_pg import (
        approval_runtime,
        create_match,
        installed_approval_guard,
    )
    from ugc_bot.infrastructure.db.migrations.versions import (
        financial_refund_approvals_a1 as migration,
    )

    rt = await approval_runtime(intake_env)
    if with_match:
        _, approved, _, _ = await create_match(rt)
    else:
        approved = await rt.approved()
    before_guard = installed_approval_guard(rt.env["pg"])
    before_tables = inspect(rt.env["pg"]).get_table_names()
    before_approval = rt.approval_rows(
        "approvals", intent_id=UUID(approved["intent_id"])
    )
    before_links = rt.approval_rows("match_approvals")
    with (
        rt.env["pg"].begin() as db,
        Operations.context(MigrationContext.configure(db)),
    ):
        with pytest.raises(
            RuntimeError,
            match="Cannot discard immutable refund approval history",
        ):
            migration.downgrade()
        assert inspect(db).get_table_names() == before_tables
    assert installed_approval_guard(rt.env["pg"]) == before_guard
    assert (
        rt.approval_rows("approvals", intent_id=UUID(approved["intent_id"]))
        == before_approval
    )
    assert rt.approval_rows("match_approvals") == before_links


def test_incomplete_physical_metadata_refuses_approval_writes_until_completed():
    import os

    from sqlalchemy import text

    from tests.helpers.financial_environment import isolated_financial_database
    from ugc_bot.infrastructure.db.base import Base
    from ugc_bot.infrastructure.db.correction_approval_models import (
        TABLES as NEW,
    )
    from ugc_bot.infrastructure.db.correction_models import TABLES as OLD

    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="campaign_drafts_v1",
    ) as engine:
        missing = [
            table
            for table in OLD
            if table.name == "financial_refund_liability_assessments"
        ]
        initial = [table for table in OLD if table not in missing]
        Base.metadata.create_all(engine, tables=[*initial, *NEW])
        with engine.begin() as db:
            for table in NEW:
                with (
                    pytest.raises(
                        DBAPIError,
                        match="correction_approval_schema_unavailable",
                    ),
                    db.begin_nested(),
                ):
                    db.execute(text(f"INSERT INTO {table.name} DEFAULT VALUES"))
                with (
                    pytest.raises(
                        DBAPIError, match="correction_fact_immutable"
                    ),
                    db.begin_nested(),
                ):
                    db.execute(text(f"DELETE FROM {table.name}"))
        Base.metadata.create_all(engine, tables=missing)
        with engine.connect() as db:
            assert "correction_match_capsule" in db.scalar(
                text(
                    "SELECT prosrc FROM pg_proc WHERE "
                    "oid='correction_check_application()'::regprocedure"
                )
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate", ["command", "intent_review"])
async def test_approval_identity_uniques_preserve_the_original_review(
    intake_env, duplicate
):
    from uuid import UUID, uuid4

    from sqlalchemy import insert

    from tests.helpers.correction_approval_pg import approval_runtime
    from ugc_bot.infrastructure.db.correction_approval_models import TABLE_MAP

    rt = await approval_runtime(intake_env)
    approved = await rt.approved()
    original = rt.approval_rows(
        "approvals", approval_id=UUID(approved["approval_id"])
    )[0]
    copy = original | {"approval_id": uuid4()}
    if duplicate == "intent_review":
        copy["command_id"] = uuid4()
    with rt.env["pg"].begin() as db:
        with pytest.raises(DBAPIError) as caught, db.begin_nested():
            db.execute(insert(TABLE_MAP["approvals"]).values(**copy))
        assert caught.value.orig.sqlstate == "23505"
    assert rt.approval_rows(
        "approvals", approval_id=original["approval_id"]
    ) == [original]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["review", "match"])
@pytest.mark.parametrize("field", ["result_state_hash", "previous_state_hash"])
async def test_new_authority_refuses_corrupt_original_event_state_hash(
    intake_env,
    stage,
    field,
):
    from tests.helpers.correction_approval_pg import (
        approval_runtime,
        corrupt_event_hash,
    )

    rt = await approval_runtime(intake_env)
    requested = await rt.execute(await rt.request())
    if stage == "review":
        command = rt.review(requested)
        error = "correction_review_authority_invalid"
    else:
        approved = await rt.execute(rt.review(requested))
        observed = await rt.execute(rt.observation(approved))
        command = rt.match(observed, approved, observed)
        error = "correction_match_authority_invalid"
    with corrupt_event_hash(rt, field), pytest.raises(DBAPIError, match=error):
        await rt.execute(command)


@pytest.mark.asyncio
@pytest.mark.parametrize("valid_key", [True, False])
async def test_retained_match_checks_original_physical_key_digest(
    intake_env, valid_key
):
    from uuid import UUID, uuid4

    from sqlalchemy import insert

    from tests.helpers.correction_approval_pg import (
        alter_fact,
        approval_runtime,
    )
    from ugc_bot.application.physical_proof_ports import PhysicalProofOwner
    from ugc_bot.infrastructure.db.repositories.physical_proofs import PROOFS

    rt = await approval_runtime(intake_env)
    approved = await rt.approved()
    good = await rt.execute(rt.observation(approved))
    # Genuine second report while configured recognition is unavailable. Its
    # immutable report and original command are real; no old row is changed.
    rt.service.physical_proofs = type(rt.proofs)("", "", rt.env["clock"])
    try:
        report = await rt.execute(rt.observation(good))
    finally:
        rt.service.physical_proofs = rt.proofs
    original = rt.rows(
        "observations", observation_id=UUID(report["observation_id"])
    )[0]
    identity = rt.proofs.resolve_manual_identity(
        original["bank_account_label"],
        original["bank_reference"],
        direction="outgoing",
    )
    owner = PhysicalProofOwner(
        producer="refund",
        intent_id=UUID(approved["intent_id"]),
        observation_id=original["observation_id"],
        command_id=original["command_id"],
    )
    async with rt.env["container"].transaction_manager.transaction() as db:
        if valid_key:
            assert await rt.proofs.claim(identity, owner, session=db) == owner
        else:
            # Explicit malformed fresh SQL fixture: only key_hash differs from
            # the ordinary common-claim producer's identity/owner shape.
            await db.execute(
                insert(PROOFS).values(
                    claim_id=uuid4(),
                    source=identity.source,
                    account=identity.account,
                    direction=identity.direction,
                    reference=identity.reference,
                    key_hash="f" * 64,
                    producer="refund",
                    intent_id=owner.intent_id,
                    observation_id=owner.observation_id,
                    command_id=owner.command_id,
                    recorded_at=rt.env["clock"].at,
                )
            )
    command = rt.match(report, approved, good)
    # Preserve real service validation/provenance; select the second genuine
    # report in the pending INSERT so the retained SQL guard sees the key.
    with alter_fact(
        rt,
        "matches",
        lambda value: value | {"observation_id": original["observation_id"]},
    ):
        if valid_key:
            matched = await rt.execute(command)
            assert matched["application_status"] == "awaiting_assessment"
        else:
            with pytest.raises(
                DBAPIError, match="correction_match_proof_invalid"
            ):
                await rt.execute(command)


@pytest.mark.asyncio
async def test_application_capsule_rechecks_later_current_event_prefix(
    intake_env,
):
    from uuid import UUID

    from sqlalchemy import text

    from tests.helpers.correction_approval_pg import (
        approval_runtime,
        corrupt_event_hash,
        create_match,
    )

    rt = await approval_runtime(intake_env)
    _, _, _, matched = await create_match(rt)
    # A newly retained report can carry broken evidence; it must remain visible
    # as unavailable and cannot authenticate a fresh financial application.
    with corrupt_event_hash(rt, "previous_state_hash"):
        await rt.execute(rt.observation(matched))
    with rt.env["pg"].connect() as db:
        assert (
            db.execute(
                text("SELECT * FROM correction_match_capsule(:id,false)"),
                {"id": UUID(matched["match_id"])},
            ).first()
            is not None
        )
    with (
        pytest.raises(DBAPIError, match="correction_match_authority_invalid"),
        rt.env["pg"].connect() as db,
    ):
        db.execute(
            text("SELECT * FROM correction_match_capsule(:id)"),
            {"id": UUID(matched["match_id"])},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 30])
async def test_actual_full_selection_bundle_edges_with_all_original_grounds(
    intake_env, count
):
    from tests.helpers.correction_approval_pg import (
        approval_runtime,
        genuine_approved_match,
    )
    from tests.helpers.corrections import assess_original

    rt = await approval_runtime(intake_env)
    await assess_original(rt.env, rt.facts)
    selected = tuple(
        item.paid_item_id for item in rt.facts["order"].items[:count]
    )
    async with rt.env["container"].transaction_manager.transaction() as db:
        matched = await genuine_approved_match(
            rt.env, rt.facts, rt.repo, db, selected=selected
        )
    approval = rt.approval_rows("approvals", intent_id=matched["intent_id"])[0]
    assert approval["amount_minor"] == {1: 50000, 30: 1500000}[count]
    assert len(approval["bundle"]) == count
    assert len(approval["source_capsule"]["ground_ids"]) == 30
    assert approval["source_capsule"]["ground_ids"] == sorted(
        approval["source_capsule"]["ground_ids"]
    )
    assert (
        len(rt.approval_rows("match_approvals", match_id=matched["match_id"]))
        == 1
    )
    assert rt.rows("applications", intent_id=matched["intent_id"]) == []

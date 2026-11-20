"""Exercise the exact indexed SQL scripts on current migrated PostgreSQL."""

import copy
import json
import os
from time import monotonic
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from scripts.residual_purge_catalog import (
    UnsafePurge,
    primary_keys,
    rows,
    triggers,
)
from scripts.residual_purge_recovery_check import (
    verify_documents_in_test_database,
)
from scripts.residual_purge_snapshot import capture_snapshot
from scripts.residual_purge_sql import (
    delete_statements,
    lock_plan,
    render_psql,
    restore_statements,
)
from tests.helpers.financial_environment import isolated_financial_database
from tests.helpers.residual_purge_seed import (
    add_working_snapshot,
    database_digest,
    put,
    seed_residuals,
)


def capture(case, **options):
    with case["engine"].connect() as db:
        db.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        )
        db.execute(text("SET LOCAL timezone='UTC'"))
        primary = primary_keys(db)
        keys = {}
        for target in case["plan"]["delete_tables"]:
            table = target["table"]
            found = rows(
                db,
                f'SELECT to_jsonb(t)::text AS document FROM "{table}" t '
                "WHERE md5(to_jsonb(t)::text)=ANY(CAST(:ids AS text[]))",
                {"ids": target["row_fingerprints"]},
            )
            keys[table] = [
                {k: str(json.loads(r["document"])[k]) for k in primary[table]}
                for r in found
            ]
        return capture_snapshot(
            db, case["plan"], keys, rehearsal=True, **options
        )


@pytest.fixture
def release_case(request):
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        if request.config.getoption("--require-financial-postgres"):
            pytest.fail("FINANCIAL_TEST_DATABASE_URL is required")
        pytest.skip("An explicit isolated test database is required")
    with isolated_financial_database(
        url, target_revision="0146_invite_partners"
    ) as engine:
        case = seed_residuals(engine)
        yield case


def execute(case, statements, *, hook=None):
    started = monotonic()
    with case["engine"].begin() as db:
        for number, statement in enumerate(statements):
            if hook:
                hook(number, statement, db)
            db.exec_driver_sql(
                statement, execution_options={"no_parameters": True}
            )
    return monotonic() - started


def test_indexed_delete_and_restore_preserve_all_unrelated_data(release_case):
    case = release_case
    snapshot = capture(case)
    before = database_digest(case["engine"], exclude_operations=True)
    assert snapshot["schema_heads"] == ["0146_invite_partners"]
    assert "users" not in lock_plan(snapshot) and "orders" not in lock_plan(
        snapshot
    )
    assert execute(case, delete_statements(snapshot)) < 3
    assert execute(case, restore_statements(snapshot)) < 3
    assert database_digest(case["engine"], exclude_operations=True) == before
    script = render_psql(delete_statements(snapshot))
    assert script.startswith("\\set ON_ERROR_STOP on\nBEGIN;")
    assert script.endswith("COMMIT;\n")
    assert "session_replication_role" not in script
    assert "DISABLE TRIGGER ALL" not in script
    assert "WHERE md5(to_jsonb" not in script


def test_unrelated_users_orders_and_new_finance_work_during_and_after_cleanup(
    release_case,
):
    case = release_case
    snapshot = capture(case)
    changed = False

    def write_unrelated(_number, statement, db):
        nonlocal changed
        if changed or "DISABLE TRIGGER" not in statement:
            return
        changed = True
        modes = db.scalars(
            text(
                "SELECT mode FROM pg_locks WHERE pid=pg_backend_pid() "
                "AND relation IN ('users'::regclass,'orders'::regclass)"
            )
        ).all()
        assert "ShareRowExclusiveLock" not in modes
        with case["engine"].begin() as other:
            other.execute(text("SET LOCAL statement_timeout='300ms'"))
            user, order = uuid4(), uuid4()
            put(
                other,
                "users",
                user_id=user,
                messenger_type="telegram",
                username="unrelated concurrent registration",
                status="active",
            )
            put(
                other,
                "orders",
                order_id=order,
                advertiser_id=user,
                product_link="https://example.test",
                offer_text="unrelated",
                price=1,
                bloggers_needed=10,
                status="new",
            )
            other.execute(
                text(
                    "UPDATE users SET username='concurrent update' "
                    "WHERE user_id=CAST(:id AS uuid)"
                ),
                {"id": case["money"]["partner"]},
            )

    execute(case, delete_statements(snapshot), hook=write_unrelated)
    assert changed
    with case["engine"].begin() as db:
        add_working_snapshot(db, case["money"])
    execute(case, restore_statements(snapshot))
    with case["engine"].connect() as db:
        assert db.scalar(text("SELECT count(*) FROM rate_snapshots")) == 2
        assert (
            db.scalar(
                text(
                    "SELECT username FROM users WHERE user_id=CAST(:id AS uuid)"
                ),
                {"id": case["money"]["partner"]},
            )
            == "concurrent update"
        )


@pytest.mark.parametrize("busy", ["history", "table", "root_row"])
def test_busy_locks_abort_without_partial_changes(release_case, busy):
    case = release_case
    snapshot = capture(case)
    before = database_digest(case["engine"])
    with case["engine"].begin() as other:
        if busy == "history":
            other.execute(
                text(
                    "SELECT pg_advisory_xact_lock_shared(2119754201,170434819)"
                )
            )
        elif busy == "table":
            other.execute(
                text(
                    (
                        "LOCK TABLE campaign_foundation_commands "
                        "IN ROW EXCLUSIVE MODE"
                    )
                )
            )
        else:
            other.execute(
                text(
                    (
                        "SELECT 1 FROM users WHERE user_id="
                        "CAST(:id AS uuid) FOR UPDATE"
                    )
                ),
                {"id": case["plan"]["user_ids"][0]},
            )
        started = monotonic()
        with pytest.raises(DBAPIError):
            execute(case, delete_statements(snapshot))
        assert monotonic() - started < 1
    assert database_digest(case["engine"]) == before


@pytest.mark.parametrize("failure", ["after_delete", "budget", "disconnect"])
def test_errors_roll_back_data_and_guard_ddl(release_case, failure):
    case = release_case
    snapshot = capture(case)
    before = database_digest(case["engine"])
    injected = False

    def fail(_number, statement, db):
        nonlocal injected
        if injected or "DELETE FROM" not in statement:
            return
        injected = True
        if failure == "after_delete":
            raise RuntimeError("injected")
        if failure == "budget":
            db.execute(
                text(
                    "SELECT set_config('ugc.purge_started_at',"
                    "(clock_timestamp()-interval '4 seconds')::text,true)"
                )
            )
        else:
            pid = db.scalar(text("SELECT pg_backend_pid()"))
            with case["engine"].begin() as killer:
                killer.execute(
                    text("SELECT pg_terminate_backend(:pid)"), {"pid": pid}
                )

    with pytest.raises((RuntimeError, DBAPIError)):
        execute(case, delete_statements(snapshot), hook=fail)
    assert injected
    assert database_digest(case["engine"]) == before
    with case["engine"].connect() as db:
        assert triggers(db, snapshot["rows"]) == [
            g
            for g in snapshot["triggers"]
            if g["table_name"] in snapshot["rows"]
        ]


@pytest.mark.parametrize("drift", ["foreign_key", "column", "guard", "cluster"])
def test_schema_and_destination_drift_abort_before_deletion(
    release_case, drift
):
    case = release_case
    snapshot = capture(case)
    with case["engine"].begin() as db:
        if drift == "foreign_key":
            db.execute(
                text(
                    (
                        "CREATE TABLE extra_reference(owner "
                        "uuid REFERENCES users(user_id) "
                        "ON DELETE SET NULL)"
                    )
                )
            )
        elif drift == "column":
            db.execute(text("ALTER TABLE users ADD COLUMN unexpected text"))
        elif drift == "guard":
            db.execute(
                text(
                    (
                        "ALTER TABLE creator_identity_observations "
                        "DISABLE TRIGGER creator_identity_immutable"
                    )
                )
            )
        else:
            snapshot["identity"]["system_identifier"] = "wrong-system"
    before = database_digest(case["engine"])
    with pytest.raises(DBAPIError):
        execute(case, delete_statements(snapshot))
    assert database_digest(case["engine"]) == before


def test_shared_history_blocks_production_script_but_allows_encrypted_backup(
    release_case,
):
    case = release_case
    with case["engine"].begin() as db:
        put(
            db,
            "creator_identity_observations",
            creator_user_id=uuid4(),
            instagram_user_id="synthetic-" + case["plan"]["user_ids"][0],
            active=True,
            source="instagram_webhook",
            business_key="outside-history",
        )
    with pytest.raises(UnsafePurge, match="shared_instagram_identity"):
        capture(case)
    backup = capture(case, backup_only=True)
    assert "shared_instagram_identity" in backup["blockers"]
    for compiler in (delete_statements, restore_statements):
        with pytest.raises(
            UnsafePurge, match="preparation_blockers_unresolved"
        ):
            compiler(backup)


def test_capture_refuses_writable_transaction(release_case):
    with (
        release_case["engine"].begin() as db,
        pytest.raises(UnsafePurge, match="read_only_required"),
    ):
        capture_snapshot(db, {}, {})


def test_compiler_rejects_tampered_primary_key(release_case):
    snapshot = capture(release_case)
    tampered = copy.deepcopy(snapshot)
    tampered["rows"]["users"][0]["key"]["user_id"] = str(uuid4())
    with pytest.raises(UnsafePurge, match="snapshot_primary_key_changed"):
        delete_statements(tampered)


@pytest.mark.parametrize("lease", ["expired", "live", "missing_result"])
def test_terminal_leases_need_expiry_and_acceptance_proof(release_case, lease):
    case = release_case
    with case["engine"].begin() as db:
        direction = "-" if lease != "live" else "+"
        db.execute(
            text(
                "UPDATE accompaniment_lead_deliveries "
                "SET lease_token=gen_random_uuid(),"
                f"lease_until=clock_timestamp(){direction}interval '1 minute'"
            )
        )
        if lease == "missing_result":
            db.execute(
                text(
                    "UPDATE accompaniment_lead_deliveries "
                    "SET current_attempt_id=gen_random_uuid()"
                )
            )
        fingerprints = sorted(
            db.scalars(
                text(
                    "SELECT md5(to_jsonb(t)::text) "
                    "FROM accompaniment_lead_deliveries t"
                )
            ).all()
        )
        for target in case["plan"]["delete_tables"]:
            if target["table"] == "accompaniment_lead_deliveries":
                target["row_fingerprints"] = fingerprints
    if lease == "expired":
        snapshot = capture(case)
        before = database_digest(case["engine"], exclude_operations=True)
        execute(case, delete_statements(snapshot))
        execute(case, restore_statements(snapshot))
        assert (
            database_digest(case["engine"], exclude_operations=True) == before
        )
    else:
        with pytest.raises(UnsafePurge, match="lead_delivery_not_idle"):
            capture(case)


def test_portable_recovery_verifies_all_original_rows(release_case):
    case = release_case
    snapshot = capture(case)
    before = database_digest(case["engine"], exclude_operations=True)
    execute(case, delete_statements(snapshot))
    result = verify_documents_in_test_database(case["engine"], snapshot)
    assert result["verified_original_rows"] == 63
    assert result["guards_restored"] and result["foreign_keys_enabled"]
    assert database_digest(case["engine"], exclude_operations=True) == before


@pytest.mark.parametrize("test_owner", [True, False])
def test_opaque_provider_payload_has_separate_checked_ownership(
    release_case, test_owner
):
    case = release_case
    owner = (
        case["plan"]["user_ids"][0] if test_owner else case["money"]["partner"]
    )
    with case["engine"].begin() as db:
        put(
            db,
            "instagram_stats",
            user_id=owner,
            fetched_at=case["now"],
            raw_response={"external_biography": case["plan"]["user_ids"][0]},
        )
    if test_owner:
        with pytest.raises(
            UnsafePurge, match="outside_logical_reference:instagram_stats"
        ):
            capture(case)
    else:
        snapshot = capture(case)
        before = database_digest(case["engine"], exclude_operations=True)
        execute(case, delete_statements(snapshot))
        execute(case, restore_statements(snapshot))
        assert (
            database_digest(case["engine"], exclude_operations=True) == before
        )


def test_identity_history_added_after_capture_blocks_the_sql(release_case):
    case = release_case
    with case["engine"].begin() as db:
        # A platform ID is independent of the application's UUID namespace.
        db.execute(
            text(
                "ALTER TABLE creator_identity_observations "
                "DISABLE TRIGGER creator_identity_immutable"
            )
        )
        db.execute(
            text(
                "UPDATE creator_identity_observations SET "
                "instagram_user_id='123456789' WHERE "
                "source<>'canonical_profile_cutover'"
            )
        )
        db.execute(
            text(
                "ALTER TABLE creator_identity_observations "
                "ENABLE TRIGGER creator_identity_immutable"
            )
        )
        hashes = sorted(
            db.scalars(
                text(
                    "SELECT md5(to_jsonb(t)::text) "
                    "FROM creator_identity_observations t "
                    "WHERE source<>'canonical_profile_cutover'"
                )
            ).all()
        )
        # Keep the selected cutover record and replace only observed facts.
        original = next(
            t
            for t in case["plan"]["delete_tables"]
            if t["table"] == "creator_identity_observations"
        )
        cutover = db.scalar(
            text(
                "SELECT md5(to_jsonb(t)::text) FROM "
                "creator_identity_observations t WHERE "
                "source='canonical_profile_cutover' AND "
                "creator_user_id=CAST(:id AS uuid)"
            ),
            {"id": case["plan"]["user_ids"][0]},
        )
        original["row_fingerprints"] = sorted([*hashes, cutover])
    snapshot = capture(case)
    with case["engine"].begin() as db:
        put(
            db,
            "creator_identity_observations",
            creator_user_id=uuid4(),
            instagram_user_id="123456789",
            active=True,
            source="instagram_webhook",
            business_key="late-shared-proof",
        )
    before = database_digest(case["engine"])
    with pytest.raises(DBAPIError, match="outside_identity_history_changed"):
        execute(case, delete_statements(snapshot))
    assert database_digest(case["engine"]) == before

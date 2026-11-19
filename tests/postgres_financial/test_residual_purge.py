"""Deletion/restore rehearsals on actual PostgreSQL migrations, no live data."""

import json
import os
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from scripts.rehearse_test_residual_purge import main
from scripts.residual_purge import (
    TARGET_ORDERS,
    TARGET_USERS,
    delete_rehearsal,
    inspect_rehearsal,
    restore_rehearsal,
)
from scripts.residual_purge_backup import read_encrypted
from scripts.residual_purge_catalog import UnsafePurge, digest, triggers
from tests.helpers.financial_environment import isolated_financial_database
from tests.helpers.residual_purge_seed import (
    add_working_snapshot,
    database_digest,
    put,
    seed_residuals,
)
from tests.postgres_financial.test_identity_history_postgres import count_at


@pytest.fixture
def case(request, tmp_path):
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        if request.config.getoption("--require-financial-postgres"):
            pytest.fail("FINANCIAL_TEST_DATABASE_URL is required")
        pytest.skip("Explicit local financial test PostgreSQL is required")
    with isolated_financial_database(
        url, target_revision="0145_instagram_profiles"
    ) as engine:
        data = seed_residuals(engine)
        private = tmp_path / "recovery"
        private.mkdir(mode=0o700)
        key = private / "key"
        key.write_bytes(Fernet.generate_key())
        key.chmod(0o600)
        yield data | {"backup": private / "rows.enc", "key": key}


def delete(case, *, fault=None):
    return delete_rehearsal(
        case["engine"], case["plan"], case["backup"], case["key"], fault=fault
    )


def restore(case, *, fault=None):
    return restore_rehearsal(
        case["engine"], case["plan"], case["backup"], case["key"], fault=fault
    )


def guard_state(case):
    with case["engine"].connect() as db:
        return triggers(
            db,
            [r["table"] for r in case["plan"]["delete_tables"]]
            + ["creator_identity_coverage"],
        )


def test_complete_61_row_delete_and_exact_selective_restore(case):
    before = database_digest(case["engine"], exclude_operations=True)
    guards = guard_state(case)
    read = inspect_rehearsal(case["engine"], case["plan"])
    assert (
        read["read_only"] == "on"
        and read["rows"] == 61
        and read["tables"] == 23
    )
    assert database_digest(case["engine"], exclude_operations=True) == before
    result = delete(case)
    assert result["deleted_rows"] == 61 and result["updated_rows"] == 2
    assert result["guards_restored"] and result["backup_verified"]
    assert not result["production_writes_enabled"]
    assert guard_state(case) == guards
    assert case["backup"].stat().st_mode & 0o077 == 0
    ciphertext = case["backup"].read_bytes()
    assert all(target.encode() not in ciphertext for target in TARGET_USERS)
    backup = read_encrypted(case["backup"], case["key"])
    assert sum(len(r) for r in backup["rows"].values()) == 61
    assert restore(case)["restored_rows"] == 61
    assert database_digest(case["engine"], exclude_operations=True) == before
    assert guard_state(case) == guards
    with case["engine"].connect() as db:
        assert (
            db.scalar(
                text(
                    "SELECT count(*) FROM audit_log "
                    "WHERE entity_type='test_residual_cleanup'"
                )
            )
            == 2
        )


@pytest.mark.asyncio
async def test_financial_history_and_new_snapshot_work_after_delete(case):
    money = case["money"]
    partner = UUID(money["partner"])
    at = case["now"] + timedelta(minutes=5)
    before = await count_at(case["engine"], partner, at)
    assert before.verified_count == 1
    initial = database_digest(case["engine"])
    delete(case)
    current = await count_at(case["engine"], partner, at)
    for field in (
        "verified_count",
        "covered_from",
        "identity_watermark",
        "binding_watermark",
        "coverage_version",
    ):
        assert getattr(current, field) == getattr(before, field)
    after = database_digest(case["engine"])
    for table in (
        "payments",
        "order_items",
        "rate_snapshots",
        "financial_obligations",
        "financial_movements",
        "financial_wallets",
    ):
        assert after[table] == initial[table]
    with case["engine"].begin() as db:
        add_working_snapshot(db, money, at=at + timedelta(minutes=1))
    assert (await count_at(case["engine"], partner, at)).verified_count == 1


@pytest.mark.parametrize("stage", ["deleted:users", "updated", "before_commit"])
def test_delete_failure_rolls_back_data_and_trigger_ddl(case, stage):
    before, guards = database_digest(case["engine"]), guard_state(case)

    def fail(current, _db):
        if current == stage:
            raise RuntimeError("injected_delete_failure")

    with pytest.raises(RuntimeError, match="injected_delete_failure"):
        delete(case, fault=fail)
    assert database_digest(case["engine"]) == before
    assert guard_state(case) == guards


@pytest.mark.parametrize("stage", ["restored:users", "before_commit"])
def test_restore_failure_rolls_back_restored_rows_and_guards(case, stage):
    delete(case)
    before, guards = database_digest(case["engine"]), guard_state(case)

    def fail(current, _db):
        if current == stage:
            raise RuntimeError("injected_restore_failure")

    with pytest.raises(RuntimeError, match="injected_restore_failure"):
        restore(case, fault=fail)
    assert database_digest(case["engine"]) == before
    assert guard_state(case) == guards


@pytest.mark.parametrize(
    "drift",
    [
        "root",
        "notice",
        "lease",
        "payment",
        "json",
        "text",
        "cascade",
        "null_fk",
        "identity",
        "binding",
        "head",
        "guard",
    ],
)
def test_preflight_rejects_changed_scope_without_partial_deletion(case, drift):
    engine = case["engine"]
    with engine.begin() as db:
        if drift == "root":
            db.execute(
                text(
                    """
UPDATE users SET username='changed' WHERE user_id=CAST(:id
AS uuid)"""
                ),
                {"id": TARGET_USERS[0]},
            )
        elif drift == "notice":
            db.execute(
                text(
                    """UPDATE order_notice_deliveries SET state='sending' WHERE
order_id=CAST(:id AS uuid)"""
                ),
                {"id": TARGET_ORDERS[0]},
            )
        elif drift == "lease":
            db.execute(
                text(
                    """UPDATE financial_checkouts SET lease_until=now()+interval
'1 minute'"""
                )
            )
        elif drift == "payment":
            put(
                db,
                "payments",
                payment_id=uuid4(),
                order_id=TARGET_ORDERS[0],
                provider="synthetic",
                status="pending",
                amount=500,
                currency="RUB",
                external_id=str(uuid4()),
            )
        elif drift in {"json", "text"}:
            db.execute(
                text(
                    """CREATE TABLE unexpected_reference(id integer PRIMARY KEY,
payload jsonb, note text)"""
                )
            )
            db.execute(
                text(
                    """
INSERT INTO unexpected_reference VALUES(1,jsonb_build_object('user',
CAST(:id
AS text)),NULL)
"""
                    if drift == "json"
                    else """
INSERT INTO unexpected_reference VALUES(1,NULL,CAST(:id
AS text))"""
                ),
                {"id": TARGET_USERS[0]},
            )
        elif drift in {"cascade", "null_fk"}:
            action = "CASCADE" if drift == "cascade" else "SET NULL"
            db.execute(
                text(
                    f"""
CREATE TABLE unexpected_reference(id integer PRIMARY KEY,user_id
uuid REFERENCES users(user_id) ON DELETE {action})"""
                )
            )
            db.execute(
                text(
                    """INSERT INTO unexpected_reference VALUES(1,CAST(:id AS
uuid))"""
                ),
                {"id": TARGET_USERS[0]},
            )
        elif drift == "identity":
            put(
                db,
                "creator_identity_observations",
                creator_user_id=case["money"]["creator"],
                instagram_user_id="synthetic-" + TARGET_USERS[0],
                active=True,
                source="instagram_webhook",
                business_key="shared-synthetic",
            )
        elif drift == "binding":
            put(
                db,
                "creator_direct_binding_observations",
                referrer_user_id=case["money"]["partner"],
                referred_user_id=TARGET_USERS[0],
                active=True,
                created_at=case["now"],
                registered_at=case["now"],
                source="direct_binding_observed",
                business_key="outside-synthetic",
            )
        elif drift == "head":
            db.execute(
                text("UPDATE alembic_version SET version_num='unexpected'")
            )
        elif drift == "guard":
            db.execute(
                text(
                    """ALTER TABLE creator_identity_observations DISABLE TRIGGER
creator_identity_immutable"""
                )
            )
    before, guards = database_digest(engine), guard_state(case)
    with pytest.raises(UnsafePurge):
        delete(case)
    assert database_digest(engine) == before
    assert guard_state(case) == guards
    assert not case["backup"].exists()


@pytest.mark.parametrize("lock", ["table", "history_reader", "history_writer"])
def test_busy_locks_abort_without_waiting_or_deletion(case, lock):
    before = database_digest(case["engine"])
    with case["engine"].begin() as other:
        if lock == "table":
            other.execute(text("LOCK TABLE users IN ROW EXCLUSIVE MODE"))
        else:
            shared = "_shared" if lock == "history_reader" else ""
            other.execute(
                text(
                    f"SELECT pg_advisory_xact_lock{shared}"
                    "(2119754201,170434819)"
                )
            )
        with pytest.raises((UnsafePurge, DBAPIError)):
            delete(case)
    assert database_digest(case["engine"]) == before


@pytest.mark.parametrize(
    "problem",
    ["tampered", "wrong_key", "working_data_changed", "already_restored"],
)
def test_restore_refuses_unsafe_or_conflicting_backup(case, problem):
    delete(case)
    if problem == "tampered":
        case["backup"].write_bytes(case["backup"].read_bytes()[:-5] + b"abcde")
    elif problem == "wrong_key":
        case["key"].write_bytes(Fernet.generate_key())
    elif problem == "working_data_changed":
        with case["engine"].begin() as db:
            db.execute(
                text(
                    """
UPDATE users SET username='new working data' WHERE user_id=CAST(:id
AS uuid)"""
                ),
                {"id": case["money"]["partner"]},
            )
    elif problem == "already_restored":
        restore(case)
    before, guards = database_digest(case["engine"]), guard_state(case)
    with pytest.raises((ValueError, DBAPIError)):
        restore(case)
    assert database_digest(case["engine"]) == before
    assert guard_state(case) == guards


def test_original_immutability_and_insert_proofs_work_after_restore(case):
    delete(case)
    restore(case)
    with case["engine"].begin() as db:
        for guard in case["plan"]["delete_guards"]:
            with pytest.raises(DBAPIError), db.begin_nested():
                db.execute(text('DELETE FROM "' + guard["table_name"] + '"'))
        for statement in (
            "UPDATE creator_identity_coverage SET profile_seed_count=0",
            "TRUNCATE creator_identity_observations",
            "TRUNCATE creator_direct_binding_observations",
            "TRUNCATE creator_identity_coverage",
            "DELETE FROM rate_snapshots",
        ):
            with pytest.raises(DBAPIError), db.begin_nested():
                db.execute(text(statement))
        with (
            pytest.raises(DBAPIError, match="intake_source_mismatch"),
            db.begin_nested(),
        ):
            put(
                db,
                "order_intake_receipts",
                request_id=uuid4(),
                order_id=case["plan"]["audit_redaction"]["business_order_id"],
                client_id=case["money"]["partner"],
                operation_key="invalid-new",
                payload_hash="a" * 64,
                requested_at=case["now"],
                result={},
            )


def test_failed_backup_prevents_any_deletion(case):
    case["key"].chmod(0o644)
    before, guards = database_digest(case["engine"]), guard_state(case)
    with pytest.raises(UnsafePurge, match="private_file_permissions"):
        delete(case)
    assert database_digest(case["engine"]) == before
    assert guard_state(case) == guards


def test_cli_inspect_delete_restore_roundtrip(case, monkeypatch, capsys):
    engine = case["engine"]
    before = database_digest(engine, exclude_operations=True)
    manifest = case["key"].parent / "synthetic-manifest.json"
    manifest.write_text(json.dumps(case["plan"]))
    manifest.chmod(0o600)
    with engine.connect() as db:
        schema = db.scalar(text("SELECT current_schema()"))
    monkeypatch.setenv(
        "PURGE_REHEARSAL_DATABASE_URL",
        engine.url.set(query={}).render_as_string(hide_password=False),
    )
    common = ["--schema", schema, "--manifest", str(manifest)]
    assert main(common) == 0
    assert json.loads(capsys.readouterr().out)["read_only"] == "on"
    assert database_digest(engine, exclude_operations=True) == before
    mutations = [
        *common,
        "--manifest-sha256",
        digest(case["plan"]),
        "--backup",
        str(case["backup"]),
        "--key-file",
        str(case["key"]),
    ]
    assert main([*mutations, "--action", "delete"]) == 0
    assert json.loads(capsys.readouterr().out)["deleted_rows"] == 61
    assert main([*mutations, "--action", "restore"]) == 0
    assert json.loads(capsys.readouterr().out)["restored_rows"] == 61
    assert database_digest(engine, exclude_operations=True) == before


def test_lost_connection_rolls_back_trigger_ddl_and_deletes(case):
    before, guards = database_digest(case["engine"]), guard_state(case)

    def disconnect(stage, db):
        if stage == "deleted:users":
            pid = db.scalar(text("SELECT pg_backend_pid()"))
            with case["engine"].begin() as killer:
                assert killer.scalar(
                    text("SELECT pg_terminate_backend(:pid)"), {"pid": pid}
                )

    with pytest.raises(DBAPIError):
        delete(case, fault=disconnect)
    assert database_digest(case["engine"]) == before
    assert guard_state(case) == guards


def test_backup_cannot_be_restored_into_another_database_schema(case):
    delete(case)
    url = os.environ["FINANCIAL_TEST_DATABASE_URL"]
    with isolated_financial_database(
        url, target_revision="0145_instagram_profiles"
    ) as other:
        before = database_digest(other)
        with pytest.raises(UnsafePurge, match="backup_database_mismatch"):
            restore_rehearsal(other, case["plan"], case["backup"], case["key"])
        assert database_digest(other) == before


def test_hidden_reference_to_child_receipt_also_aborts(case):
    with case["engine"].begin() as db:
        request = db.scalar(text("SELECT request_id FROM checkout_requests"))
        db.execute(
            text(
                "CREATE TABLE extra_reference(id integer PRIMARY KEY,"
                " payload jsonb NOT NULL)"
            )
        )
        db.execute(
            text(
                "INSERT INTO extra_reference VALUES(1,"
                "jsonb_build_object('receipt',CAST(:id AS text)))"
            ),
            {"id": str(request)},
        )
    before = database_digest(case["engine"])
    with pytest.raises(UnsafePurge, match="outside_logical_reference"):
        delete(case)
    assert database_digest(case["engine"]) == before

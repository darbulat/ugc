"""Rehearse the approved 61-row cleanup on an isolated local PostgreSQL.

This review version deliberately has NO production-write entry point. The
same transactional delete/restore logic is exercised against real migrations,
but both public APIs reject remote URLs and the public schema before writes.
No import of application config and no implicit DATABASE_URL fallback.
"""

import hashlib
import json
import re
from contextlib import contextmanager
from pathlib import Path
from time import monotonic
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from scripts.residual_purge_backup import read_encrypted, write_encrypted
from scripts.residual_purge_catalog import (
    check_incoming_references,
    check_logical_references,
    deletion_order,
    digest,
    primary_keys,
    quote,
    require,
    retained_fingerprints,
    row_documents,
    rows,
    schema_signature,
    triggers,
)
from ugc_bot.infrastructure.db.identity_history_schema import (
    BINDING_HASH,
    PROFILE_HASH,
)

MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "test-residual-purge-20261120.json"
)
APPROVED_SCOPE_SHA256 = (
    "635049a70db7f34ece9fee6e567de30af907350209a7446e39aa5c1eb608b29a"
)
TARGET_USERS = (
    "445d5faa-097b-4ec6-a4d7-60118eb08d49",
    "85569c5b-7a46-4e61-ace4-1c6571c1d7ed",
    "de09d5f2-d387-47e4-9910-e4d5475f07eb",
)
TARGET_ORDERS = (
    "d6b8cdea-d5f8-5f2a-945b-5b1c1fdf980c",
    "f654742d-9b6d-5ac1-a751-3eec6eb4ad3e",
)
AUDIT_ID = "6f684fca-e0b8-4e5d-9dd3-61aca50f2d79"
BUSINESS_ORDER = "55428791-9ff3-5486-8575-e154e0428be2"
INSERT_GUARDS = {
    ("order_intake_receipts", "intake_receipt_source"),
    ("accompaniment_leads", "accompaniment_lead_source"),
    ("accompaniment_lead_outbox", "accompaniment_queue_proof"),
    ("accompaniment_lead_deliveries", "accompaniment_delivery_proof"),
    ("accompaniment_lead_attempts", "accompaniment_attempt_proof"),
    ("accompaniment_lead_outcomes", "accompaniment_outcome_proof"),
}


def load_plan():
    plan = json.loads(MANIFEST_PATH.read_text())
    require(
        digest(plan) == APPROVED_SCOPE_SHA256, "approved_scope_file_changed"
    )
    return plan


def validate_plan(plan):
    approved = load_plan()
    require(tuple(plan["user_ids"]) == TARGET_USERS, "wrong_target_users")
    require(tuple(plan["order_ids"]) == TARGET_ORDERS, "wrong_target_orders")
    require(
        plan["schema_heads"] == ["0145_instagram_profiles"], "wrong_schema_head"
    )
    expected = {r["table"]: r["rows"] for r in approved["delete_tables"]}
    actual = {r["table"]: r["rows"] for r in plan["delete_tables"]}
    require(actual == expected and plan["delete_rows"] == 61, "wrong_scope")
    require(len(actual) == len(plan["delete_tables"]), "duplicate_table")
    for row in plan["delete_tables"]:
        hashes = row["row_fingerprints"]
        require(
            len(hashes) == row["rows"] == len(set(hashes)), "wrong_hash_count"
        )
        require(
            all(re.fullmatch("[a-f0-9]{32}", h) for h in hashes), "bad_hash"
        )
    require(
        plan["protected_accounts"] == approved["protected_accounts"],
        "wrong_protected_accounts",
    )
    require(
        plan["delete_guards"] == approved["delete_guards"],
        "wrong_delete_guards",
    )
    require(
        plan["coverage_guard"] == approved["coverage_guard"],
        "wrong_coverage_guard",
    )
    audit = plan["audit_redaction"]
    require(
        audit["audit_id"] == AUDIT_ID
        and audit["business_order_id"] == BUSINESS_ORDER,
        "wrong_audit_target",
    )
    require(
        audit["expected_old_value"] == TARGET_USERS[0]
        and audit["replacement"] is None
        and audit["field"] == "old_values.advertiser_id",
        "wrong_redaction",
    )
    coverage = plan["coverage_update"]
    require(
        coverage["key"] == "v1"
        and coverage["after_profile_seed_count"]
        == coverage["before"]["profile_seed_count"] - 1,
        "wrong_seed_delta",
    )


def require_rehearsal_url(value):
    """Validate before engine creation, including routing overrides."""
    try:
        url = make_url(value)
        safe = (
            url.drivername in {"postgresql", "postgresql+psycopg"}
            and url.host in {"127.0.0.1", "localhost", "::1", "db_test"}
            and re.fullmatch(r"[a-z][a-z0-9_]*_test", url.database or "")
            and not url.query
        )
    except (ArgumentError, ValueError, TypeError):
        safe = False
    require(safe, "local_test_database_required_production_writes_disabled")
    return url.set(drivername="postgresql+psycopg")


@contextmanager
def sandbox_transaction(engine, *, readonly=False):
    url = engine.url
    base = require_rehearsal_url(
        url.set(query={}).render_as_string(hide_password=False)
    )
    options = url.query.get("options", "")
    match = re.fullmatch(
        r"-csearch_path=(financial_test_[a-f0-9]{32}),public", options
    )
    require(set(url.query) == {"options"} and match, "isolated_schema_required")
    require(base.database == url.database, "database_route_mismatch")
    with engine.begin() as db:
        if readonly:
            db.execute(
                text(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
            )
        db.execute(text("SET LOCAL statement_timeout='3s'"))
        db.execute(text("SET LOCAL lock_timeout='100ms'"))
        db.execute(text("SET LOCAL idle_in_transaction_session_timeout='10s'"))
        db.execute(text("SET LOCAL timezone='UTC'"))
        require(
            db.scalar(text("SELECT current_schema()")) == match[1],
            "wrong_schema",
        )
        require(
            db.scalar(text("SELECT current_database()")) == url.database,
            "wrong_database",
        )
        yield db


def _selected(plan):
    return {r["table"]: r["row_fingerprints"] for r in plan["delete_tables"]}


def _tables(plan):
    return sorted([*_selected(plan), "creator_identity_coverage", "audit_log"])


def _document(db, table, where, params=None):
    return db.scalar(
        text(f"SELECT to_jsonb(t)::text FROM {quote(table)} t WHERE {where}"),
        params or {},
    )


def _fingerprint(db, document, table):
    return db.scalar(
        text(
            f"""
SELECT md5(to_jsonb(t)::text) FROM jsonb_populate_record(NULL::{quote(table)},

CAST(:doc AS jsonb)) t
"""
        ),
        {"doc": document},
    )


def check_coverage(db):
    actual = rows(
        db,
        f"""

        SELECT
        (SELECT count(*) FROM creator_identity_observations
          WHERE source='canonical_profile_cutover')
AS profile_seed_count,
        (SELECT {PROFILE_HASH} FROM creator_identity_observations
          WHERE source='canonical_profile_cutover')
AS profile_seed_hash,
        (SELECT count(*) FROM creator_direct_binding_observations
          WHERE source='direct_binding_cutover')
AS binding_seed_count,
        (SELECT {BINDING_HASH} FROM creator_direct_binding_observations
          WHERE source='direct_binding_cutover')
AS binding_seed_hash

""",
    )[0]
    coverage = rows(
        db, "SELECT * FROM creator_identity_coverage WHERE coverage_key='v1'"
    )[0]
    require(
        all(coverage[k] == value for k, value in actual.items()),
        "coverage_integrity_failed",
    )
    return coverage


def _guard_pairs(plan):
    pairs = {
        (r["table_name"], r["trigger_name"]) for r in plan["delete_guards"]
    }
    return pairs | {
        ("creator_identity_coverage", plan["coverage_guard"]["tgname"])
    }


def _check_guards(db, plan):
    schema = db.scalar(text("SELECT current_schema()"))
    actual = triggers(db, _tables(plan))
    by_pair = {(r["table_name"], r["trigger_name"]): r for r in actual}
    expected = [
        *plan["delete_guards"],
        dict(
            plan["coverage_guard"],
            table_name="creator_identity_coverage",
            trigger_name=plan["coverage_guard"]["tgname"],
        ),
    ]
    for guard in expected:
        found = by_pair.get((guard["table_name"], guard["trigger_name"]))
        require(
            found is not None
            and found["tgenabled"] == guard["tgenabled"] == "O",
            "guard_missing_or_disabled",
        )
        require(
            found["definition"].replace(schema + ".", "public.")
            == guard["definition"],
            "guard_definition_changed",
        )
    for guard in actual:
        pair = (guard["table_name"], guard["trigger_name"])
        if guard["tgtype"] & 8:
            require(pair in _guard_pairs(plan), "unexpected_delete_trigger")
        if guard["tgtype"] & 4:
            require(pair in INSERT_GUARDS, "unexpected_insert_trigger")
        require(guard["tgenabled"] == "O", "disabled_target_trigger")
    return actual


def _check_roots(db, plan):
    users = rows(
        db,
        """SELECT * FROM users
        WHERE user_id=ANY(CAST(:ids AS uuid[]))""",
        {"ids": list(TARGET_USERS)},
    )
    require(
        len(users) == 3
        and all(
            u["status"] == "deleted"
            and not u["admin"]
            and not any(
                u[k]
                for k in ("telegram_id", "telegram", "max_id", "max_chat_id")
            )
            for u in users
        ),
        "root_user_state_changed",
    )
    orders = rows(
        db,
        "SELECT * FROM orders WHERE order_id=ANY(CAST(:ids AS uuid[]))",
        {"ids": list(TARGET_ORDERS)},
    )
    require(
        len(orders) == 2
        and all(
            o["status"] == "deleted"
            and o["dispatch_stopped"]
            and str(o["advertiser_id"]) == TARGET_USERS[0]
            for o in orders
        ),
        "root_order_state_changed",
    )
    for protected in plan["protected_accounts"]:
        found = rows(
            db,
            """SELECT telegram,status,admin FROM users WHERE user_id=CAST(:id
AS uuid)""",
            {"id": protected["user_id"]},
        )
        require(
            found
            == [{k: protected[k] for k in ("telegram", "status", "admin")}],
            "protected_account_changed",
        )


def _check_idle(db):
    require(
        not db.scalar(
            text("""
SELECT EXISTS(SELECT 1 FROM accompaniment_lead_deliveries d
        WHERE order_id=ANY(CAST(:ids AS uuid[])) AND
        (state<>'accepted' OR lease_until>clock_timestamp()
         OR NOT EXISTS(SELECT 1 FROM accompaniment_lead_outcomes o
             WHERE o.attempt_id=d.current_attempt_id
               AND o.status='accepted' AND o.applied)))
"""),
            {"ids": list(TARGET_ORDERS)},
        ),
        "lead_delivery_not_idle",
    )
    require(
        not db.scalar(
            text("""
SELECT EXISTS(SELECT 1 FROM accompaniment_lead_outbox
        WHERE order_id=ANY(CAST(:ids AS uuid[]))
AND expanded_at IS NULL)
"""),
            {"ids": list(TARGET_ORDERS)},
        ),
        "lead_outbox_not_idle",
    )
    require(
        not db.scalar(
            text("""SELECT EXISTS(SELECT 1 FROM order_notice_deliveries
        WHERE order_id=ANY(CAST(:ids AS uuid[])) AND
        (state<>'sent' OR lease_until>clock_timestamp()))"""),
            {"ids": list(TARGET_ORDERS)},
        ),
        "order_notice_not_idle",
    )
    require(
        not db.scalar(
            text("""SELECT EXISTS(SELECT 1 FROM financial_checkouts
        WHERE order_id=ANY(CAST(:ids AS uuid[])) AND
        (authorization_id IS NOT NULL OR lease_until IS NOT NULL))"""),
            {"ids": list(TARGET_ORDERS)},
        ),
        "checkout_not_idle",
    )


def _check_shared_identities(db, *, actor_ids=TARGET_USERS):
    params = {"ids": list(actor_ids)}
    own = """SELECT instagram_user_id FROM creator_identity_observations
WHERE creator_user_id=ANY(CAST(:ids AS uuid[])) AND instagram_user_id
IS NOT NULL"""
    for statement in (
        f"""
SELECT 1 FROM creator_identity_observations WHERE
NOT(creator_user_id=ANY(CAST(:ids
AS uuid[]))) AND instagram_user_id IN ({own})
""",
        f"""SELECT 1 FROM blogger_profiles WHERE NOT(user_id=ANY(CAST(:ids
AS uuid[]))) AND confirmed AND instagram_user_id IN ({own})""",
        f"""
SELECT 1 FROM creator_social_accounts WHERE NOT(user_id=ANY(CAST(:ids
AS uuid[]))) AND platform='instagram' AND verified
AND
external_id IN ({own})
""",
    ):
        require(
            not db.scalar(text("SELECT EXISTS(" + statement + ")"), params),
            "shared_instagram_identity",
        )
    require(
        not db.scalar(
            text("""SELECT EXISTS(
        SELECT 1 FROM creator_direct_binding_observations
        WHERE (referrer_user_id=ANY(CAST(:ids AS uuid[]))
            OR referred_user_id=ANY(CAST(:ids AS uuid[])))
          AND NOT(referrer_user_id=ANY(CAST(:ids AS uuid[]))
            AND referred_user_id=ANY(CAST(:ids AS uuid[]))))"""),
            params,
        ),
        "history_link_to_working_partner",
    )


def _identity(db):
    return rows(
        db,
        """
SELECT current_database() AS database,
        (SELECT oid::text FROM pg_database WHERE
datname=current_database()) AS database_oid,
        current_schema() AS schema,
        (SELECT oid::text FROM pg_namespace WHERE
nspname=current_schema()) AS schema_oid
""",
    )[0]


def _ops_ids(plan, identity):
    return [
        str(
            uuid5(
                NAMESPACE_URL,
                "residual-purge:" + digest(plan) + digest(identity) + action,
            )
        )
        for action in ("delete", "restore")
    ]


def _exclusions(plan, coverage_document):
    return dict(
        _selected(plan),
        creator_identity_coverage=[
            # to_jsonb text is already in PostgreSQL's canonical form.
            hashlib.md5(coverage_document.encode()).hexdigest()
        ],
    )


def _reference_ids(db, captured, plan):
    """Check logical references to deleted jobs and receipts as well."""
    keys = primary_keys(db)
    protected = {u["user_id"] for u in plan["protected_accounts"]}
    identifiers = {*TARGET_USERS, *TARGET_ORDERS}
    for table, documents in captured.items():
        for row in documents:
            document = json.loads(row["document"])
            for key in keys[table]:
                value = document[key]
                if not isinstance(value, str) or value in protected:
                    continue
                try:
                    identifiers.add(str(UUID(value)))
                except ValueError:
                    continue
    return sorted(identifiers)


def preflight(db, plan):
    validate_plan(plan)
    require(
        [
            r["version_num"]
            for r in rows(db, "SELECT version_num FROM alembic_version")
        ]
        == plan["schema_heads"],
        "schema_head_changed",
    )
    _check_roots(db, plan)
    _check_idle(db)
    _check_shared_identities(db)
    captured = {}
    for table, hashes in _selected(plan).items():
        captured[table] = row_documents(db, table, hashes)
        require(
            [r["fingerprint"] for r in captured[table]] == sorted(hashes),
            "row_fingerprint_changed:" + table,
        )
    guard_state = _check_guards(db, plan)
    coverage = check_coverage(db)
    expected = plan["coverage_update"]
    require(
        all(
            coverage[k] == v
            for k, v in expected["before"].items()
            if k != "row_fingerprint"
        ),
        "coverage_baseline_changed",
    )
    coverage_doc = _document(
        db, "creator_identity_coverage", "coverage_key='v1'"
    )
    require(
        _fingerprint(db, coverage_doc, "creator_identity_coverage")
        == expected["before"]["row_fingerprint"],
        "coverage_row_changed",
    )
    projected_hash = db.scalar(
        text(
            f"""
SELECT {PROFILE_HASH} FROM creator_identity_observations
WHERE source='canonical_profile_cutover' AND NOT(creator_user_id=ANY(CAST(:ids
AS uuid[])))
"""
        ),
        {"ids": list(TARGET_USERS)},
    )
    seed_count = db.scalar(
        text(
            """SELECT count(*) FROM creator_identity_observations WHERE
source='canonical_profile_cutover' AND creator_user_id=ANY(CAST(:ids
AS uuid[]))"""
        ),
        {"ids": list(TARGET_USERS)},
    )
    require(
        seed_count == 1
        and projected_hash == expected["after_profile_seed_hash"],
        "coverage_projection_changed",
    )
    audit_doc = _document(
        db, "audit_log", "id=CAST(:id AS uuid)", {"id": AUDIT_ID}
    )
    require(
        audit_doc is not None
        and _fingerprint(db, audit_doc, "audit_log")
        == plan["audit_redaction"]["before_row_fingerprint"],
        "audit_row_changed",
    )
    audit = json.loads(audit_doc)
    require(
        audit["entity_id"] == BUSINESS_ORDER
        and audit["old_values"]["advertiser_id"] == TARGET_USERS[0],
        "wrong_audit_reference",
    )
    check_incoming_references(db, _selected(plan))
    reference_ids = _reference_ids(db, captured, plan)
    check_logical_references(db, _selected(plan), reference_ids, AUDIT_ID)
    identity = _identity(db)
    ops_ids = _ops_ids(plan, identity)
    require(
        not db.scalar(
            text(
                """SELECT EXISTS(SELECT 1 FROM audit_log WHERE id=ANY(CAST(:ids
AS uuid[])))"""
            ),
            {"ids": ops_ids},
        ),
        "operation_already_recorded",
    )
    return {
        "version": 1,
        "plan": plan,
        "plan_sha256": digest(plan),
        "identity": identity,
        "rows": captured,
        "reference_ids": reference_ids,
        "coverage": coverage_doc,
        "audit": audit_doc,
        "triggers": guard_state,
        "schema_signature": schema_signature(db, _tables(plan)),
        "delete_order": deletion_order(db, captured),
        "ops_ids": ops_ids,
        "retained": retained_fingerprints(
            db, _exclusions(plan, coverage_doc), audit_ids=[AUDIT_ID, *ops_ids]
        ),
    }


def inspect_rehearsal(engine, plan):
    with sandbox_transaction(engine, readonly=True) as db:
        snapshot = preflight(db, plan)
        return {
            "read_only": db.scalar(text("SHOW transaction_read_only")),
            "rows": sum(len(r) for r in snapshot["rows"].values()),
            "tables": len(snapshot["rows"]),
            "plan_sha256": digest(plan),
        }


def _lock(db):
    """Fail fast; lock the isolated rehearsal schema only, never public."""
    for row in rows(
        db,
        """SELECT table_name FROM information_schema.tables WHERE
table_schema=current_schema() AND table_type='BASE TABLE'
ORDER BY table_name""",
    ):
        db.execute(
            text(
                f"""LOCK TABLE {quote(row["table_name"])} IN SHARE ROW EXCLUSIVE
MODE NOWAIT"""
            )
        )
    require(
        db.scalar(
            text("SELECT pg_try_advisory_xact_lock(2119754201,170434819)")
        ),
        "history_barrier_busy",
    )


def _toggle(db, guards, *, disabled):
    for guard in guards:
        action = "DISABLE" if disabled else "ENABLE"
        require(guard["tgenabled"] == "O", "unsupported_original_trigger_state")
        db.execute(
            text(
                f"""ALTER TABLE {quote(guard["table_name"])} {action} TRIGGER
{quote(guard["trigger_name"])}"""
            )
        )


def _operation_audit(db, snapshot, action):
    idx = 0 if action == "delete" else 1
    db.execute(
        text("""
INSERT INTO audit_log
        (id,entity_type,entity_id,action,old_values,
new_values)
        VALUES(CAST(:id AS uuid),'test_residual_cleanup',
CAST(:id AS uuid),
               'create',NULL,CAST(:details AS jsonb))
"""),
        {
            "id": snapshot["ops_ids"][idx],
            "details": json.dumps(
                {
                    "action": action,
                    "plan_sha256": snapshot["plan_sha256"],
                    "deleted_rows": 61,
                    "updated_rows": 2,
                }
            ),
        },
    )


def _redacted_audit(snapshot):
    result = json.loads(snapshot["audit"])
    result["old_values"]["advertiser_id"] = None
    return result


def _after_coverage(snapshot):
    result = json.loads(snapshot["coverage"])
    change = snapshot["plan"]["coverage_update"]
    result.update(
        profile_seed_count=change["after_profile_seed_count"],
        profile_seed_hash=change["after_profile_seed_hash"],
    )
    return result


def _postcheck(db, snapshot, *, restored=False):
    plan = snapshot["plan"]
    require(
        schema_signature(db, _tables(plan)) == snapshot["schema_signature"],
        "schema_or_guards_changed",
    )
    _check_guards(db, plan)
    check_coverage(db)
    coverage_doc = _document(
        db, "creator_identity_coverage", "coverage_key='v1'"
    )
    expected_coverage = (
        json.loads(snapshot["coverage"])
        if restored
        else _after_coverage(snapshot)
    )
    require(
        json.loads(coverage_doc) == expected_coverage,
        "coverage_unexpected_update",
    )
    audit_doc = _document(
        db, "audit_log", "id=CAST(:id AS uuid)", {"id": AUDIT_ID}
    )
    expected_audit = (
        json.loads(snapshot["audit"]) if restored else _redacted_audit(snapshot)
    )
    require(json.loads(audit_doc) == expected_audit, "audit_unexpected_update")
    for table, hashes in _selected(plan).items():
        found = row_documents(db, table, hashes)
        require(
            found == (snapshot["rows"][table] if restored else []),
            "unexpected_target_rows:" + table,
        )
    require(
        retained_fingerprints(
            db,
            _exclusions(plan, coverage_doc),
            audit_ids=[AUDIT_ID, *snapshot["ops_ids"]],
        )
        == snapshot["retained"],
        "unrelated_data_changed",
    )
    check_logical_references(
        db,
        _selected(plan) if restored else {},
        snapshot["reference_ids"],
        AUDIT_ID,
        redacted=not restored,
    )


def delete_rehearsal(engine, plan, backup_path, key_path, *, fault=None):
    """Back up, delete, update two rows and restore guards atomically."""
    started = monotonic()
    with sandbox_transaction(engine) as db:
        _lock(db)
        snapshot = preflight(db, plan)
        write_encrypted(backup_path, key_path, snapshot)
        require(monotonic() - started < 15, "transaction_budget_exceeded")
        guards = [
            g
            for g in snapshot["triggers"]
            if (g["table_name"], g["trigger_name"]) in _guard_pairs(plan)
        ]
        _toggle(db, guards, disabled=True)
        for table in snapshot["delete_order"]:
            result = db.execute(
                text(
                    f"""
DELETE FROM {quote(table)} t WHERE md5(to_jsonb(t)::text)=ANY(CAST(:hashes
AS text[]))
"""
                ),
                {"hashes": _selected(plan)[table]},
            )
            require(
                result.rowcount == len(snapshot["rows"][table]),
                "delete_count_changed",
            )
            if fault:
                fault("deleted:" + table, db)
        change = plan["coverage_update"]
        result = db.execute(
            text(
                """
UPDATE creator_identity_coverage SET profile_seed_count=:n,
profile_seed_hash=:hash
WHERE coverage_key='v1'
"""
            ),
            {
                "n": change["after_profile_seed_count"],
                "hash": change["after_profile_seed_hash"],
            },
        )
        require(result.rowcount == 1, "coverage_update_count")
        result = db.execute(
            text(
                """
UPDATE audit_log SET old_values=jsonb_set(old_values,
'{advertiser_id}','null'::jsonb,false)
WHERE id=CAST(:id AS uuid)
"""
            ),
            {"id": AUDIT_ID},
        )
        require(result.rowcount == 1, "audit_update_count")
        if fault:
            fault("updated", db)
        _toggle(db, guards, disabled=False)
        _operation_audit(db, snapshot, "delete")
        _postcheck(db, snapshot)
        require(monotonic() - started < 15, "transaction_budget_exceeded")
        if fault:
            fault("before_commit", db)
    return {
        "deleted_rows": 61,
        "updated_rows": 2,
        "guards_restored": True,
        "backup_verified": True,
        "production_writes_enabled": False,
    }


def _restore_rows(db, snapshot, *, fault=None):
    for table in reversed(snapshot["delete_order"]):
        columns = [
            r["attname"]
            for r in rows(
                db,
                """
SELECT attname FROM pg_attribute
            WHERE attrelid=CAST(:table AS regclass)
AND attnum>0
              AND NOT attisdropped AND attgenerated=''
ORDER BY attnum
""",
                {"table": table},
            )
        ]
        names = ",".join(quote(c) for c in columns)
        for row in snapshot["rows"][table]:
            db.execute(
                text(
                    f"""
INSERT INTO {quote(table)} ({names}) OVERRIDING
SYSTEM
VALUE SELECT {names} FROM jsonb_populate_record(NULL::{quote(table)},
CAST(:document
AS jsonb))
"""
                ),
                {"document": row.get("restore_document", row["document"])},
            )
        if fault:
            fault("restored:" + table, db)


def restore_rehearsal(engine, plan, backup_path, key_path, *, fault=None):
    """Refuse schema, key, baseline or working-data drift on restore."""
    snapshot = read_encrypted(backup_path, key_path)
    validate_plan(plan)
    require(
        snapshot["plan"] == plan and snapshot["plan_sha256"] == digest(plan),
        "backup_plan_mismatch",
    )
    started = monotonic()
    with sandbox_transaction(engine) as db:
        _lock(db)
        require(
            _identity(db) == snapshot["identity"], "backup_database_mismatch"
        )
        _postcheck(db, snapshot)
        require(monotonic() - started < 15, "transaction_budget_exceeded")
        guards = [
            g
            for g in snapshot["triggers"]
            if (g["table_name"], g["trigger_name"]) in INSERT_GUARDS
            or g["table_name"] == "creator_identity_coverage"
            and g["trigger_name"] == "creator_coverage_immutable"
        ]
        _toggle(db, guards, disabled=True)
        _restore_rows(db, snapshot, fault=fault)
        old = json.loads(snapshot["coverage"])
        db.execute(
            text(
                """
UPDATE creator_identity_coverage SET profile_seed_count=:count,
profile_seed_hash=:hash
WHERE coverage_key='v1'
"""
            ),
            {
                "count": old["profile_seed_count"],
                "hash": old["profile_seed_hash"],
            },
        )
        db.execute(
            text(
                """UPDATE audit_log SET old_values=CAST(:old AS jsonb) WHERE
id=CAST(:id AS uuid)"""
            ),
            {
                "old": json.dumps(json.loads(snapshot["audit"])["old_values"]),
                "id": AUDIT_ID,
            },
        )
        _toggle(db, guards, disabled=False)
        _operation_audit(db, snapshot, "restore")
        _postcheck(db, snapshot, restored=True)
        require(monotonic() - started < 15, "transaction_budget_exceeded")
        if fault:
            fault("before_commit", db)
    return {
        "restored_rows": 61,
        "restored_updates": 2,
        "guards_restored": True,
        "production_writes_enabled": False,
    }

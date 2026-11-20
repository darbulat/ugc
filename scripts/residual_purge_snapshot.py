"""Read-only selective backup capture, with indexed target row selection."""

import json
from time import monotonic

from sqlalchemy import text

from scripts.residual_purge import (
    APPROVED_SCOPE_SHA256,
    AUDIT_ID,
    _check_guards,
    _check_idle,
    _check_roots,
    _check_shared_identities,
    _reference_ids,
    check_coverage,
)
from scripts.residual_purge_catalog import (
    UnsafePurge,
    deletion_order,
    foreign_keys,
    primary_keys,
    quote,
    reference_columns,
    require,
    rows,
    triggers,
)
from scripts.residual_purge_sql import (
    CONSTRAINT_HASH_SQL,
    SCHEMA_HASH_SQL,
    literal,
    lock_plan,
    predicate,
    qualified,
    validate_snapshot,
)

# The producer stores this external response without an internal-ID envelope.
# Ownership is checked through the separate UUID/FK column, not the opaque blob.
OPAQUE_PROVIDER_COLUMNS = {("instagram_stats", "raw_response")}


def _all_logical_references(db, snapshot, *, backup_only=False):
    grouped = {}
    for column in snapshot["reference_columns"]:
        if (
            column["table_name"],
            column["column_name"],
        ) in OPAQUE_PROVIDER_COLUMNS:
            continue
        grouped.setdefault(column["table_name"], []).append(
            column["column_name"]
        )
    patterns = (
        "ARRAY["
        + ",".join(
            literal("%" + uid + "%") for uid in snapshot["reference_ids"]
        )
        + "]"
    )
    for table, columns in grouped.items():
        db.info["purge_phase"] = "logical_scan:" + table
        match = " OR ".join(
            f"lower(t.{quote(c)}::text) LIKE ANY({patterns})" for c in columns
        )
        allowed = "false"
        if table in snapshot["rows"]:
            allowed = predicate(
                snapshot, table, [r["key"] for r in snapshot["rows"][table]]
            )
        if table == "audit_log":
            allowed = "t.id=" + literal(AUDIT_ID)
        exists = db.scalar(
            text(
                f"SELECT EXISTS(SELECT 1 FROM {qualified(snapshot, table)} t "
                f"WHERE ({match}) AND NOT ({allowed}))"
            )
        )
        if exists and backup_only:
            snapshot["blockers"].append("outside_logical_reference:" + table)
        else:
            require(not exists, "outside_logical_reference:" + table)


def capture_snapshot(db, scope, keys, *, rehearsal=False, backup_only=False):
    """Capture in READ ONLY; encrypt raw documents before writing to disk."""
    started = monotonic()
    require(
        db.scalar(text("SHOW transaction_read_only")) == "on",
        "read_only_required",
    )
    require(db.scalar(text("SHOW timezone")) == "UTC", "utc_required")
    identity = rows(
        db,
        """SELECT current_database() AS database,current_schema() AS schema,
        (SELECT system_identifier::text FROM pg_control_system())
        AS system_identifier""",
    )[0]
    snapshot = {
        "version": 2,
        "scope_sha256": APPROVED_SCOPE_SHA256,
        "schema_heads": [
            r["version_num"]
            for r in rows(db, "SELECT version_num FROM alembic_version")
        ],
        "identity": identity,
        "read_only": "on",
        "primary_keys": primary_keys(db),
        "foreign_keys": foreign_keys(db),
        "reference_columns": reference_columns(db),
        "rows": {},
        "blockers": [],
        "purpose": "encrypted_backup_only"
        if backup_only
        else "execution_preparation",
        "opaque_provider_columns_not_scanned": [
            list(pair) for pair in sorted(OPAQUE_PROVIDER_COLUMNS)
        ],
    }
    if rehearsal:
        require(
            identity["schema"].startswith("financial_test_")
            and identity["database"].endswith("_test"),
            "rehearsal_target_required",
        )
        snapshot["rehearsal_hashes"] = {
            r["table"]: sorted(r["row_fingerprints"])
            for r in scope["delete_tables"]
        }
    db.info["purge_phase"] = "root_state_checks"
    _check_roots(db, scope)
    _check_idle(db)
    try:
        _check_shared_identities(db)
    except UnsafePurge as exc:
        if not backup_only:
            raise
        snapshot["blockers"].append(str(exc))
    _check_guards(db, scope)
    check_coverage(db)
    for target in scope["delete_tables"]:
        table = target["table"]
        db.info["purge_phase"] = "indexed_capture:" + table
        where = predicate(snapshot, table, keys[table])
        selected = rows(
            db,
            f"SELECT to_jsonb(t)::text AS document,"
            f"md5(to_jsonb(t)::text) AS "
            f"fingerprint FROM {qualified(snapshot, table)} "
            f"t "
            f"WHERE {where}",
        )
        documents = []
        for row in selected:
            document = json.loads(row["document"])
            key = {k: str(document[k]) for k in snapshot["primary_keys"][table]}
            documents.append(dict(row, key=key))
        snapshot["rows"][table] = sorted(
            documents, key=lambda r: r["fingerprint"]
        )
    db.info["purge_phase"] = "coverage_capture"
    snapshot["coverage"] = db.scalar(
        text(
            (
                "SELECT to_jsonb(c)::text FROM "
                "creator_identity_coverage c WHERE "
                "coverage_key='v1'"
            )
        )
    )
    snapshot["audit"] = db.scalar(
        text(
            (
                "SELECT to_jsonb(t)::text FROM "
                "audit_log t WHERE id=CAST(:id "
                "AS uuid)"
            )
        ),
        {"id": AUDIT_ID},
    )
    change = scope["coverage_update"]
    snapshot["coverage_after"] = {
        "profile_seed_count": change["after_profile_seed_count"],
        "profile_seed_hash": change["after_profile_seed_hash"],
    }
    current = json.loads(snapshot["coverage"])
    require(
        snapshot["coverage_after"]["profile_seed_count"]
        == current["profile_seed_count"] - 1,
        "coverage_seed_count_changed",
    )
    targets = set(snapshot["rows"]) | {"creator_identity_coverage", "audit_log"}
    snapshot["triggers"] = triggers(db, targets)
    snapshot["constraint_hash"] = db.scalar(text(CONSTRAINT_HASH_SQL))
    snapshot["column_hash"] = db.scalar(text(SCHEMA_HASH_SQL))
    snapshot["delete_order"] = deletion_order(db, snapshot["rows"])
    snapshot["reference_ids"] = _reference_ids(db, snapshot["rows"], scope)
    validate_snapshot(snapshot, permit_backup_only=backup_only)
    _all_logical_references(db, snapshot, backup_only=backup_only)
    locks = lock_plan(snapshot)
    snapshot["lock_observation"] = rows(
        db,
        """
        SELECT c.relname AS table_name,l.mode,l.granted,count(*) AS sessions
        FROM pg_locks l JOIN pg_class c ON c.oid=l.relation
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=current_schema() AND l.pid<>pg_backend_pid()
          AND c.relname=ANY(CAST(:tables AS text[]))
        GROUP BY c.relname,l.mode,l.granted ORDER BY c.relname,l.mode
    """,
        {"tables": [*locks, "users", "orders"]},
    )
    snapshot["captured_at"] = str(db.scalar(text("SELECT clock_timestamp()")))
    snapshot["read_seconds"] = round(monotonic() - started, 3)
    return snapshot

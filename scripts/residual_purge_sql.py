"""Compile reviewed, bounded cleanup SQL; never connect or execute production.

Preparation consumes an authenticated selective snapshot. Execution is an
explicit later operation after owner approval, backup verification and merge.
The compiler deliberately emits no restoration payload into public artifacts.
"""

import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from scripts.residual_purge import (
    AUDIT_ID,
    INSERT_GUARDS,
    load_plan,
)
from scripts.residual_purge_catalog import digest, quote, require
from scripts.residual_purge_scope import (
    allowed_audit_ids,
    approved_scope,
    reset_audit_document,
    validate_reset_audits,
)
from scripts.residual_purge_spatial import (
    spatial_document,
    validate_spatial_documents,
)
from ugc_bot.infrastructure.db.identity_history_schema import (
    BINDING_HASH,
    PROFILE_HASH,
)

LOGICAL_ROLES = {
    "order_id",
    "user_id",
    "advertiser_id",
    "owner_id",
    "client_id",
    "creator_id",
    "actor_id",
    "recipient_id",
    "entity_id",
}
CONSTRAINT_HASH_SQL = """
SELECT md5(COALESCE(string_agg(
    c.relname || ':' || k.conname || ':' || pg_get_constraintdef(k.oid)
    || ':' || k.convalidated::text, chr(10) ORDER BY c.relname,k.conname
),'')) FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema()
"""
SCHEMA_HASH_SQL = """
SELECT md5(COALESCE(string_agg(
 c.relname || ':' || a.attname || ':' || format_type(a.atttypid,a.atttypmod)
 || ':' || a.attnotnull::text || ':' || a.attidentity::text
 || ':' || a.attgenerated::text
 || ':' || COALESCE(pg_get_expr(d.adbin,d.adrelid),''),
 chr(10) ORDER BY c.relname,a.attnum),''))
FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
JOIN pg_namespace n ON n.oid=c.relnamespace
LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
WHERE n.nspname=current_schema() AND c.relkind IN ('r','p')
 AND a.attnum>0 AND NOT a.attisdropped
"""


def literal(value):
    """SQL standard strings; scripts explicitly enable conforming strings."""
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def qualified(snapshot, table):
    return quote(snapshot["identity"]["schema"]) + "." + quote(table)


def predicate(snapshot, table, keys, alias="t"):
    names = snapshot["primary_keys"][table]
    require(bool(keys), "empty_key_scope")
    require(all(set(k) == set(names) for k in keys), "wrong_primary_key_shape")
    return (
        "("
        + " OR ".join(
            "("
            + " AND ".join(
                f"{alias}.{quote(name)}={literal(key[name])}" for name in names
            )
            + ")"
            for key in keys
        )
        + ")"
    )


def assertion(condition, code):
    require("$purge$" not in condition, "unsafe_statement_delimiter")
    return (
        "DO $purge$ BEGIN IF NOT COALESCE((" + condition + "),false) "
        "THEN RAISE EXCEPTION " + literal(code) + "; END IF; END $purge$;"
    )


def deadline():
    return assertion(
        "clock_timestamp()-current_setting('ugc.purge_started_at')::timestamptz"
        " < interval '3 seconds'",
        "purge_lock_budget_exceeded",
    )


def lock_plan(snapshot):
    """Guard tables and unfenced user/order anchors, never the whole schema."""
    tables = set(snapshot["rows"]) - {"users", "orders"}
    result = {t: "SHARE ROW EXCLUSIVE" for t in tables}
    result.update(
        creator_identity_coverage="SHARE ROW EXCLUSIVE",
        audit_log="SHARE ROW EXCLUSIVE",
        outbox_events="SHARE",
        creator_social_accounts="SHARE",
    )
    fenced = {
        (fk["child"], child)
        for fk in snapshot["foreign_keys"]
        if fk["parent"] in {"users", "orders"}
        for child in fk["child_cols"]
    }
    for col in snapshot["reference_columns"]:
        name, table = col["column_name"], col["table_name"]
        role = name in LOGICAL_ROLES or name.endswith("_user_id")
        if (
            role
            and (table, name) not in fenced
            and table not in {"users", "orders"}
        ):
            result.setdefault(table, "SHARE")
    require(
        "users" not in result and "orders" not in result,
        "root_table_write_lock_forbidden",
    )
    return dict(sorted(result.items()))


def validate_snapshot(snapshot, *, permit_backup_only=False):
    approved = approved_scope(snapshot)
    heads = (
        approved["schema_heads"]
        if "extension_sha256" in approved
        else ["0146_invite_partners"]
    )
    require(snapshot["schema_heads"] == heads, "wrong_head")
    actual = {
        t: sorted(r["fingerprint"] for r in values)
        for t, values in snapshot["rows"].items()
    }
    expected = {
        r["table"]: sorted(r["row_fingerprints"])
        for r in approved["delete_tables"]
    }
    # Synthetic snapshots explicitly supply the matching approved shape.
    hashes = snapshot.get("rehearsal_hashes", expected)
    require(actual == hashes, "snapshot_fingerprint_scope_changed")
    require(
        {t: len(v) for t, v in snapshot["rows"].items()}
        == {r["table"]: r["rows"] for r in approved["delete_tables"]},
        "snapshot_count_scope_changed",
    )
    schema = snapshot["identity"]["schema"]
    if "rehearsal_hashes" in snapshot:
        require(
            schema.startswith("financial_test_") and len(schema) == 47,
            "rehearsal_only_hash_override",
        )
    else:
        require(
            snapshot["identity"]["database"] == "ugc" and schema == "public",
            "wrong_production_identity",
        )
    require(snapshot["read_only"] == "on", "snapshot_not_read_only")
    require(
        not snapshot.get("blockers")
        or permit_backup_only
        and snapshot.get("purpose") == "encrypted_backup_only",
        "preparation_blockers_unresolved",
    )
    for table, values in snapshot["rows"].items():
        for row in values:
            predicate(snapshot, table, [row["key"]])
            document = json.loads(row["document"])
            require(
                all(
                    str(document[k]) == value for k, value in row["key"].items()
                ),
                "snapshot_primary_key_changed",
            )
            require(
                hashlib.md5(row["document"].encode()).hexdigest()
                == row["fingerprint"],
                "snapshot_document_changed",
            )
    require(
        set(snapshot["delete_order"]) == set(actual)
        and len(snapshot["delete_order"]) == len(actual),
        "wrong_delete_order",
    )
    validate_reset_audits(snapshot, approved)
    validate_spatial_documents(snapshot)


def _guard_check(snapshot):
    tables = sorted(
        {g["table_name"] for g in snapshot["triggers"]}
        | set(snapshot["rows"])
        | {"audit_log", "creator_identity_coverage"}
    )
    clauses = [
        assertion(
            "SELECT count(*)="
            + str(len(snapshot["triggers"]))
            + " FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
            "JOIN pg_namespace n ON n.oid="
            "c.relnamespace WHERE NOT t.tgisinternal "
            "AND n.nspname=current_schema() AND c.relname IN ("
            + ",".join(literal(t) for t in tables)
            + ")",
            "trigger_set_changed",
        )
    ]
    clauses.append(
        assertion(
            "("
            + CONSTRAINT_HASH_SQL
            + ")="
            + literal(snapshot["constraint_hash"]),
            "constraint_set_changed",
        )
    )
    clauses.append(
        assertion(
            "(" + SCHEMA_HASH_SQL + ")=" + literal(snapshot["column_hash"]),
            "column_set_changed",
        )
    )
    for guard in snapshot["triggers"]:
        clauses.append(
            assertion(
                "SELECT count(*)=1 FROM pg_trigger WHERE NOT tgisinternal "
                "AND tgrelid="
                + literal(qualified(snapshot, guard["table_name"]))
                + "::regclass AND tgname="
                + literal(guard["trigger_name"])
                + " AND tgenabled="
                + literal(guard["tgenabled"])
                + " AND md5(pg_get_triggerdef(oid))="
                + literal(hashlib.md5(guard["definition"].encode()).hexdigest())
                + " AND md5(pg_get_functiondef(tgfoid))="
                + literal(
                    hashlib.md5(
                        guard["function_definition"].encode()
                    ).hexdigest()
                ),
                "guard_changed:" + guard["trigger_name"],
            )
        )
    return clauses


def _begin(snapshot):
    schema = snapshot["identity"]["schema"]
    identity = snapshot["identity"]
    result = [
        "SET LOCAL standard_conforming_strings=on;",
        "SET LOCAL log_statement='none';",
        "SET LOCAL log_min_error_statement='panic';",
        "SET LOCAL log_error_verbosity='terse';",
        "SET LOCAL log_parameter_max_length_on_error=0;",
        "SET LOCAL timezone='UTC';",
        "SET LOCAL statement_timeout='750ms';",
        "SET LOCAL lock_timeout='100ms';",
        "SET LOCAL idle_in_transaction_session_timeout='2s';",
        "SET LOCAL search_path=" + quote(schema) + ",public;",
        assertion(
            "current_database()="
            + literal(identity["database"])
            + " AND current_schema()="
            + literal(schema)
            + " AND (SELECT system_identifier::text FROM pg_control_system())="
            + literal(identity["system_identifier"]),
            "wrong_database_identity",
        ),
        assertion(
            "COALESCE(current_setting('pgaudit.log',true),'none') "
            "IN ('none','')",
            "independent_statement_auditing_requires_review",
        ),
        assertion(
            "SELECT array_agg(version_num ORDER BY version_num)::text[]="
            + "ARRAY["
            + ",".join(literal(h) for h in snapshot["schema_heads"])
            + "]::text[] FROM alembic_version",
            "schema_head_changed",
        ),
        (
            "SELECT set_config('ugc.purge_started_at',"
            "clock_timestamp()::text,true);"
        ),
        assertion(
            "pg_try_advisory_xact_lock(2119754201,170434819)",
            "history_barrier_busy",
        ),
    ]
    for table, mode in lock_plan(snapshot).items():
        result.append(
            f"LOCK TABLE {qualified(snapshot, table)} IN {mode} MODE NOWAIT;"
        )
    # Prevent new FK/DDL races while ordinary root-table writes still proceed.
    for table in ("users", "orders"):
        result.append(
            f"LOCK TABLE {qualified(snapshot, table)} "
            "IN SHARE UPDATE EXCLUSIVE MODE NOWAIT;"
        )
    result.extend(_guard_check(snapshot))
    return result


def _exact_rows(snapshot, *, present):
    result = []
    for table, values in snapshot["rows"].items():
        for row in values:
            where = predicate(snapshot, table, [row["key"]])
            name = qualified(snapshot, table)
            if present:
                result.append(
                    f"DO $purge$ BEGIN PERFORM 1 FROM {name} t "
                    f"WHERE {where} FOR UPDATE NOWAIT; END $purge$;"
                )
                expression = "to_jsonb(t)::text"
                fingerprint = row["fingerprint"]
                if snapshot.get("spatial_proof") and table == "orders":
                    expression = spatial_document(json.loads(row["document"]))
                    fingerprint = row["restore_fingerprint"]
                condition = (
                    f"SELECT md5({expression})="
                    f"{literal(fingerprint)} "
                    f"FROM {name} t WHERE {where}"
                )
            else:
                condition = f"NOT EXISTS(SELECT 1 FROM {name} t WHERE {where})"
            result.append(assertion(condition, "target_row_changed:" + table))
    return result


def _incoming(snapshot):
    result = []
    for fk in snapshot["foreign_keys"]:
        parent, child = fk["parent"], fk["child"]
        if parent not in snapshot["rows"]:
            continue
        clauses = []
        for row in snapshot["rows"][parent]:
            document = json.loads(row["document"])
            clauses.append(
                "("
                + " AND ".join(
                    f"c.{quote(c)}={literal(document[p])}"
                    for c, p in zip(
                        fk["child_cols"], fk["parent_cols"], strict=True
                    )
                )
                + ")"
            )
        allowed = "false"
        if child in snapshot["rows"]:
            allowed = predicate(
                snapshot,
                child,
                [r["key"] for r in snapshot["rows"][child]],
                "c",
            )
        condition = (
            f"NOT EXISTS(SELECT 1 FROM {qualified(snapshot, child)} c WHERE ("
        )
        condition += " OR ".join(clauses) + f") AND NOT {allowed})"
        result.append(
            assertion(condition, "outside_foreign_key_reference:" + child)
        )
    return result


def _logical(snapshot, *, restoring=False):
    grouped = {}
    locked = lock_plan(snapshot)
    for col in snapshot["reference_columns"]:
        if col["table_name"] in locked:
            grouped.setdefault(col["table_name"], []).append(col["column_name"])
    patterns = (
        "ARRAY["
        + ",".join(
            literal("%" + uid + "%") for uid in snapshot["reference_ids"]
        )
        + "]"
    )
    result = []
    for table, columns in sorted(grouped.items()):
        match = " OR ".join(
            f"lower(t.{quote(c)}::text) LIKE ANY({patterns})" for c in columns
        )
        allowed = "false"
        if table in snapshot["rows"]:
            allowed = predicate(
                snapshot, table, [r["key"] for r in snapshot["rows"][table]]
            )
        if table == "audit_log":
            allowed = (
                "t.id IN ("
                + ",".join(literal(uid) for uid in allowed_audit_ids(snapshot))
                + ")"
            )
        condition = (
            f"NOT EXISTS(SELECT 1 FROM {qualified(snapshot, table)} t WHERE ("
        )
        condition += match + f") AND NOT ({allowed}))"
        result.append(
            assertion(condition, "outside_logical_reference:" + table)
        )
    return result


def _external_identities(snapshot):
    """Recheck confirmations and history added after the backup was captured."""
    history = "creator_identity_observations"
    selected = predicate(
        snapshot, history, [r["key"] for r in snapshot["rows"][history]], "h"
    )
    own_ids = (
        f"SELECT h.instagram_user_id FROM {qualified(snapshot, history)} "
        f"h WHERE {selected}"
    )
    actors = sorted(
        {
            json.loads(r["document"])["creator_user_id"]
            for r in snapshot["rows"][history]
        }
    )
    actor_list = "(" + ",".join(literal(uid) for uid in actors) + ")"
    clauses = [
        assertion(
            f"NOT EXISTS(SELECT 1 FROM {qualified(snapshot, history)} h "
            f"WHERE (h.creator_user_id IN {actor_list} OR "
            f"h.instagram_user_id IN ({own_ids})) AND NOT {selected})",
            "outside_identity_history_changed",
        )
    ]
    for table, field, proof in (
        ("blogger_profiles", "instagram_user_id", "confirmed"),
        ("creator_social_accounts", "external_id", "verified"),
    ):
        platform = (
            " AND platform='instagram'"
            if table == "creator_social_accounts"
            else ""
        )
        clauses.append(
            assertion(
                f"NOT EXISTS(SELECT 1 FROM {qualified(snapshot, table)} "
                f"WHERE {proof}{platform} AND user_id NOT IN {actor_list} "
                f"AND {quote(field)} IN ({own_ids}))",
                "outside_confirmed_identity_changed",
            )
        )
    return clauses


def _retired_actors(snapshot):
    actors = approved_scope(snapshot).get("retired_actor_ids", [])
    if not actors:
        return []
    require(
        set(actors) <= set(snapshot["reference_ids"]),
        "retired_reference_ids_missing",
    )
    ids = "(" + ",".join(literal(uid) for uid in actors) + ")"
    return [
        assertion(
            f"NOT EXISTS(SELECT 1 FROM users WHERE user_id IN {ids})",
            "retired_actor_reappeared",
        ),
        assertion(
            "NOT EXISTS(SELECT 1 FROM creator_direct_binding_observations "
            f"WHERE referrer_user_id IN {ids} OR referred_user_id IN {ids})",
            "retired_actor_binding_exists",
        ),
    ]


def _reset_audit_checks(snapshot, *, redacted):
    return [
        assertion(
            "SELECT to_jsonb(t)="
            + literal(
                json.dumps(
                    reset_audit_document(row["document"], redact=redacted),
                    sort_keys=True,
                )
            )
            + "::jsonb FROM audit_log t WHERE id="
            + literal(row["audit_id"]),
            "reset_audit_row_changed",
        )
        for row in snapshot.get("reset_audits", [])
    ]


def _reset_audit_updates(snapshot, *, redact):
    result = []
    for row in snapshot.get("reset_audits", []):
        document = reset_audit_document(row["document"], redact=redact)
        # Set only the two agreed JSON paths; preserve all other audit fields.
        account = literal(json.dumps(document["old_values"]["account"]))
        reason = literal(json.dumps(document["new_values"]["reason"]))
        result.append(
            "UPDATE audit_log SET old_values=jsonb_set(old_values,'{account}',"
            + account
            + "::jsonb,false),new_values=jsonb_set(new_values,'{reason}',"
            + reason
            + "::jsonb,false) WHERE id="
            + literal(row["audit_id"])
            + ";"
        )
    return result


def _coverage(snapshot, *, restored=False):
    before = json.loads(snapshot["coverage"])
    expected = dict(before)
    if not restored:
        expected.update(snapshot["coverage_after"])
    # Compare the entire metadata row, including preserved binding fields.
    row = literal(json.dumps(expected, sort_keys=True))
    return [
        assertion(
            (
                f"SELECT to_jsonb(c)={row}::jsonb "
                f"FROM creator_identity_coverage "
                f"c WHERE coverage_key='v1'"
            ),
            "coverage_row_changed",
        ),
        assertion(
            "SELECT c.profile_seed_count="
            "(SELECT count(*) FROM creator_identity_observations "
            "WHERE source='canonical_profile_cutover') "
            "AND c.profile_seed_hash=(SELECT "
            + PROFILE_HASH
            + " FROM creator_identity_observations "
            "WHERE source='canonical_profile_cutover') "
            "AND c.binding_seed_count=(SELECT "
            "count(*) FROM creator_direct_binding_observations "
            "WHERE source='direct_binding_cutover') "
            "AND c.binding_seed_hash=(SELECT "
            + BINDING_HASH
            + " FROM creator_direct_binding_observations "
            "WHERE source='direct_binding_cutover') "
            "FROM creator_identity_coverage c WHERE coverage_key='v1'",
            "coverage_integrity_failed",
        ),
    ]


def _update_guards(snapshot, *, restore=False, enable=False):
    pairs = {
        (g["table_name"], g["trigger_name"])
        for g in load_plan()["delete_guards"]
    }
    if restore:
        pairs = INSERT_GUARDS
    pairs = pairs | {
        ("creator_identity_coverage", "creator_coverage_immutable")
    }
    action = "ENABLE" if enable else "DISABLE"
    return [
        (
            f"ALTER TABLE {qualified(snapshot, table)} "
            f"{action} TRIGGER {quote(name)};"
        )
        for table, name in sorted(pairs)
    ]


def _audit(snapshot, *, restore=False):
    document = json.loads(snapshot["audit"])
    if not restore:
        document["old_values"]["advertiser_id"] = None
    return assertion(
        "SELECT to_jsonb(t)="
        + literal(json.dumps(document, sort_keys=True))
        + "::jsonb FROM audit_log t WHERE id="
        + literal(AUDIT_ID),
        "audit_row_changed",
    )


def _operational_audit(snapshot, action):
    identifier = str(
        uuid5(NAMESPACE_URL, "cleanup-sql:" + digest(snapshot) + action)
    )
    details = literal(
        json.dumps(
            {
                "action": action,
                "scope_sha256": snapshot["scope_sha256"],
                "snapshot_sha256": digest(snapshot),
                "rows": sum(len(v) for v in snapshot["rows"].values()),
            }
        )
    )
    return (
        (
            "INSERT INTO audit_log(id,entity_type,"
            "entity_id,action,new_values) "
            "VALUES("
        )
        + literal(identifier)
        + ",'test_residual_cleanup',"
        + literal(identifier)
        + ",'create',"
        + details
        + "::jsonb);"
    )


def delete_statements(snapshot):
    validate_snapshot(snapshot)
    result = _begin(snapshot) + _exact_rows(snapshot, present=True)
    result += _coverage(snapshot, restored=True) + [
        _audit(snapshot, restore=True)
    ]
    result += _incoming(snapshot) + _logical(snapshot)
    result += _external_identities(snapshot) + _retired_actors(snapshot)
    result += _reset_audit_checks(snapshot, redacted=False) + [deadline()]
    result += _update_guards(snapshot)
    for table in snapshot["delete_order"]:
        values = snapshot["rows"][table]
        where = predicate(snapshot, table, [r["key"] for r in values])
        # Affected-count assertions do not depend on psql's output parsing.
        statement = f"DELETE FROM {qualified(snapshot, table)} t WHERE {where}"
        require("$purge$" not in statement, "unsafe_statement_delimiter")
        result.append(
            "DO $purge$ DECLARE affected integer; BEGIN "
            + statement
            + "; GET DIAGNOSTICS affected=ROW_COUNT; IF affected<>"
            + str(len(values))
            + " THEN RAISE EXCEPTION "
            + literal("delete_count_changed:" + table)
            + "; END IF; END $purge$;"
        )
        result.append(deadline())
    change = snapshot["coverage_after"]
    result += [
        "UPDATE creator_identity_coverage SET profile_seed_count="
        + str(int(change["profile_seed_count"]))
        + ",profile_seed_hash="
        + literal(change["profile_seed_hash"])
        + " WHERE coverage_key='v1';",
        "UPDATE audit_log SET old_values="
        "jsonb_set(old_values,'{advertiser_id}',"
        "'null'::jsonb,false) WHERE id=" + literal(AUDIT_ID) + ";",
    ]
    result += _update_guards(snapshot, enable=True)
    result += _reset_audit_updates(snapshot, redact=True)
    result += _exact_rows(snapshot, present=False) + _coverage(snapshot)
    result += [_audit(snapshot)] + _guard_check(snapshot) + _logical(snapshot)
    result += _reset_audit_checks(snapshot, redacted=True) + _retired_actors(
        snapshot
    )
    result += [_operational_audit(snapshot, "delete"), deadline()]
    return result


def restore_statements(snapshot):
    validate_snapshot(snapshot)
    result = _begin(snapshot) + _exact_rows(snapshot, present=False)
    result += _coverage(snapshot) + [_audit(snapshot), deadline()]
    result += _reset_audit_checks(snapshot, redacted=True) + _retired_actors(
        snapshot
    )
    for table in (
        "creator_identity_observations",
        "creator_direct_binding_observations",
    ):
        high = max(
            int(row["key"]["observation_sequence"])
            for row in snapshot["rows"][table]
        )
        result.append(
            assertion(
                "pg_sequence_last_value(pg_get_serial_sequence("
                + literal(qualified(snapshot, table))
                + ",'observation_sequence')::regclass)>="
                + str(high),
                "history_sequence_was_rewound",
            )
        )
    result += _update_guards(snapshot, restore=True)
    for table in reversed(snapshot["delete_order"]):
        for row in snapshot["rows"][table]:
            document = literal(row.get("restore_document", row["document"]))
            result.append(
                f"INSERT INTO {qualified(snapshot, table)} "
                f"OVERRIDING SYSTEM VALUE "
                f"SELECT * FROM jsonb_populate_record("
                f"NULL::{qualified(snapshot, table)},"
                f"{document}::jsonb);"
            )
        result.append(deadline())
    change = json.loads(snapshot["coverage"])
    result += [
        "UPDATE creator_identity_coverage SET profile_seed_count="
        + str(int(change["profile_seed_count"]))
        + ",profile_seed_hash="
        + literal(change["profile_seed_hash"])
        + " WHERE coverage_key='v1';",
        "UPDATE audit_log SET old_values="
        + literal(json.dumps(json.loads(snapshot["audit"])["old_values"]))
        + "::jsonb WHERE id="
        + literal(AUDIT_ID)
        + ";",
    ]
    result += _update_guards(snapshot, restore=True, enable=True)
    result += _reset_audit_updates(snapshot, redact=False)
    result += _exact_rows(snapshot, present=True) + _coverage(
        snapshot, restored=True
    )
    result += [_audit(snapshot, restore=True)] + _guard_check(snapshot)
    result += _external_identities(snapshot)
    result += _reset_audit_checks(snapshot, redacted=False) + _retired_actors(
        snapshot
    )
    result += [_operational_audit(snapshot, "restore"), deadline()]
    return result


def render_psql(statements):
    """The caller must verify encrypted backup + recovery receipt first."""
    return (
        "\\set ON_ERROR_STOP on\n\\set VERBOSITY terse\n"
        "\\set ECHO none\nBEGIN;\n" + "\n".join(statements) + "\nCOMMIT;\n"
    )

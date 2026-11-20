"""Verify real selective backup documents in an isolated test schema only.

This checks serialization, FK dependencies, original IDs and guard restoration.
It does not reconstruct the thousands of unaffected production history seeds;
the complete baseline behavior is exercised separately with synthetic facts.
"""

import hashlib

from sqlalchemy import text

from scripts.residual_purge import (
    AUDIT_ID,
    INSERT_GUARDS,
    _check_guards,
    _restore_rows,
    load_plan,
    sandbox_transaction,
)
from scripts.residual_purge_catalog import quote, require, triggers


def verify_documents_in_test_database(engine, snapshot):
    """The caller supplies empty target keys and synthetic external parents."""
    with sandbox_transaction(engine) as db:
        # Test restores must not leak a failing raw document into DB logs.
        for setting in (
            "SET LOCAL log_statement='none'",
            "SET LOCAL log_min_error_statement='panic'",
            "SET LOCAL log_error_verbosity='terse'",
            "SET LOCAL log_parameter_max_length_on_error=0",
        ):
            db.execute(text(setting))
        guard_before = triggers(
            db, [*snapshot["rows"], "creator_identity_coverage"]
        )
        _check_guards(db, load_plan())
        for table, values in snapshot["rows"].items():
            names = snapshot["primary_keys"][table]
            for row in values:
                where = " AND ".join(
                    f"{quote(n)}=:p{i}" for i, n in enumerate(names)
                )
                params = {f"p{i}": row["key"][n] for i, n in enumerate(names)}
                require(
                    not db.scalar(
                        text(
                            (
                                f"SELECT EXISTS(SELECT 1 FROM {quote(table)} "
                                f"WHERE {where})"
                            )
                        ),
                        params,
                    ),
                    "test_target_not_empty",
                )
        for table, trigger in sorted(INSERT_GUARDS):
            db.execute(
                text(
                    (
                        f"ALTER TABLE {quote(table)} DISABLE "
                        f"TRIGGER {quote(trigger)}"
                    )
                )
            )
        db.execute(
            text(
                (
                    "ALTER TABLE creator_identity_coverage "
                    "DISABLE TRIGGER creator_coverage_immutable"
                )
            )
        )
        _restore_rows(db, snapshot)
        # Whole rows are restored only in this empty test destination.
        # Production rollback changes just the two approved fields.
        db.execute(text("DELETE FROM creator_identity_coverage"))
        db.execute(
            text(
                "INSERT INTO creator_identity_coverage SELECT * FROM "
                "jsonb_populate_record(NULL::creator_identity_coverage,"
                "CAST(:doc AS jsonb))"
            ),
            {"doc": snapshot["coverage"]},
        )
        db.execute(
            text(("DELETE FROM audit_log WHERE id=CAST(:id AS uuid)")),
            {"id": AUDIT_ID},
        )
        db.execute(
            text(
                "INSERT INTO audit_log SELECT * FROM "
                "jsonb_populate_record(NULL::audit_log,CAST(:doc AS jsonb))"
            ),
            {"doc": snapshot["audit"]},
        )
        for table, trigger in sorted(INSERT_GUARDS):
            db.execute(
                text(
                    (
                        f"ALTER TABLE {quote(table)} ENABLE "
                        f"TRIGGER {quote(trigger)}"
                    )
                )
            )
        db.execute(
            text(
                (
                    "ALTER TABLE creator_identity_coverage "
                    "ENABLE TRIGGER creator_coverage_immutable"
                )
            )
        )
        verified = 0
        for table, values in snapshot["rows"].items():
            for row in values:
                names = snapshot["primary_keys"][table]
                where = " AND ".join(
                    f"{quote(n)}=:p{i}" for i, n in enumerate(names)
                )
                params = {f"p{i}": row["key"][n] for i, n in enumerate(names)}
                found = db.scalar(
                    text(
                        (
                            f"SELECT md5(to_jsonb(t)::text) "
                            f"FROM {quote(table)} t WHERE {where}"
                        )
                    ),
                    params,
                )
                require(
                    found == row["fingerprint"], "restored_document_differs"
                )
                verified += 1
        for table, doc in (
            ("creator_identity_coverage", snapshot["coverage"]),
            ("audit_log", snapshot["audit"]),
        ):
            where = (
                "coverage_key='v1'"
                if table == "creator_identity_coverage"
                else "id=CAST(:id AS uuid)"
            )
            found = db.scalar(
                text(
                    (
                        f"SELECT md5(to_jsonb(t)::text) "
                        f"FROM {quote(table)} t WHERE {where}"
                    )
                ),
                {"id": AUDIT_ID},
            )
            require(
                found == hashlib.md5(doc.encode()).hexdigest(),
                "restored_update_row_differs",
            )
            verified += 1
        require(
            triggers(db, [*snapshot["rows"], "creator_identity_coverage"])
            == guard_before,
            "recovery_guards_changed",
        )
        require(
            db.scalar(text("SHOW session_replication_role")) == "origin",
            "foreign_keys_bypassed",
        )
        _check_guards(db, load_plan())
    return {
        "verified_original_rows": verified,
        "foreign_keys_enabled": True,
        "guards_restored": True,
        "destination": "isolated_test_schema",
        "full_production_baseline_reconstructed": False,
        "production_database_changed": False,
    }

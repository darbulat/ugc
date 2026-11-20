"""The agreed 69-delete/4-update extension, including rollback and recovery."""

import copy
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from scripts.residual_purge_catalog import UnsafePurge, rows
from scripts.residual_purge_recovery_check import (
    verify_documents_in_test_database,
)
from scripts.residual_purge_scope import load_extended_plan, load_extension
from scripts.residual_purge_sql import delete_statements, restore_statements
from tests.helpers.financial_environment import isolated_financial_database
from tests.helpers.residual_purge_seed import (
    database_digest,
    put,
    seed_residuals,
)
from tests.postgres_financial.test_residual_purge_sql import capture, execute


@pytest.fixture
def release_case(request):
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        if request.config.getoption("--require-financial-postgres"):
            pytest.fail("FINANCIAL_TEST_DATABASE_URL is required")
        pytest.skip("An explicit isolated test database is required")
    with isolated_financial_database(
        url, target_revision="0147_instagram_discovery"
    ) as engine:
        yield seed_residuals(engine)


def extend_case(case):
    extension = load_extension()
    agreed = load_extended_plan()
    for name in (
        "extension_sha256",
        "schema_heads",
        "retired_actor_ids",
        "reset_audit_redactions",
        "reset_reason",
        "delete_rows",
    ):
        case["plan"][name] = copy.deepcopy(agreed[name])
    with case["engine"].begin() as db:
        for index, target in enumerate(extension["history_rows"]):
            put(
                db,
                "creator_identity_observations",
                creator_user_id=target["actor_id"],
                instagram_user_id=(
                    "synthetic-" + case["plan"]["user_ids"][0]
                    if index % 2
                    else None
                ),
                active=bool(index % 2),
                observed_at=case["now"],
                source="instagram_webhook"
                if index % 2
                else "canonical_profile_observed",
                business_key="synthetic-retired-" + str(index),
            )
        history = next(
            t
            for t in case["plan"]["delete_tables"]
            if t["table"] == "creator_identity_observations"
        )
        extra = db.scalars(
            text(
                "SELECT md5(to_jsonb(t)::text) "
                "FROM creator_identity_observations t "
                "WHERE creator_user_id=ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": extension["retired_actor_ids"]},
        ).all()
        history["rows"] += 8
        history["row_fingerprints"] = sorted(
            history["row_fingerprints"] + extra
        )
        for target in case["plan"]["reset_audit_redactions"]:
            put(
                db,
                "audit_log",
                id=target["audit_id"],
                entity_id=target["actor_id"],
                entity_type="test_registration_reset",
                action="delete",
                changed_at=case["now"],
                old_values={
                    "account": "synthetic-test-account",
                    "had_verified_creator": True,
                },
                new_values={
                    "reason": "synthetic original reset reason",
                    "messages_sent": 0,
                    "registration_deleted": True,
                    "current_verifications_deleted": True,
                    "immutable_identity_audit_retained": True,
                },
            )
            target["before_row_fingerprint"] = db.scalar(
                text(
                    "SELECT md5(to_jsonb(t)::text) FROM audit_log t "
                    "WHERE id=CAST(:id AS uuid)"
                ),
                {"id": target["audit_id"]},
            )
    return case


def test_extended_delete_redacts_only_agreed_fields_and_restores_everything(
    release_case,
):
    case = extend_case(release_case)
    snapshot = capture(case)
    assert sum(map(len, snapshot["rows"].values())) == 69
    before = database_digest(case["engine"], exclude_operations=True)
    execute(case, delete_statements(snapshot))
    with case["engine"].connect() as db:
        for original in snapshot["reset_audits"]:
            result = rows(
                db,
                "SELECT to_jsonb(t) AS doc FROM audit_log t "
                "WHERE id=CAST(:id AS uuid)",
                {"id": original["audit_id"]},
            )[0]["doc"]
            expected = json.loads(original["document"])
            expected["old_values"]["account"] = None
            expected["new_values"]["reason"] = load_extension()[
                "replacement_reason"
            ]
            assert result == expected
    execute(case, restore_statements(snapshot))
    assert database_digest(case["engine"], exclude_operations=True) == before


def test_extended_portable_recovery_checks_73_originals(release_case):
    case = extend_case(release_case)
    snapshot = capture(case)
    before = database_digest(case["engine"], exclude_operations=True)
    execute(case, delete_statements(snapshot))
    report = verify_documents_in_test_database(case["engine"], snapshot)
    assert report["verified_original_rows"] == 73
    assert report["guards_restored"] and report["foreign_keys_enabled"]
    assert database_digest(case["engine"], exclude_operations=True) == before


@pytest.mark.parametrize(
    "changed", ["new_fact", "actor_revived", "binding", "reset_audit"]
)
def test_extended_changes_after_backup_abort_without_partial_mutation(
    release_case, changed
):
    case = extend_case(release_case)
    snapshot = capture(case)
    actor = load_extension()["retired_actor_ids"][0]
    with case["engine"].begin() as db:
        if changed == "new_fact":
            put(
                db,
                "creator_identity_observations",
                creator_user_id=actor,
                instagram_user_id=None,
                active=False,
                source="instagram_webhook",
                business_key="late-retired-fact",
            )
        elif changed == "actor_revived":
            put(
                db,
                "users",
                user_id=actor,
                messenger_type="telegram",
                username="unexpected reused UUID",
                status="active",
            )
        elif changed == "binding":
            put(
                db,
                "creator_direct_binding_observations",
                referrer_user_id=actor,
                referred_user_id=uuid4(),
                active=True,
                created_at=case["now"],
                registered_at=case["now"],
                source="direct_binding_observed",
                business_key="late-retired-binding",
            )
        else:
            db.execute(
                text(
                    "UPDATE audit_log SET new_values=new_values || "
                    '\'{"reason":"changed after backup"}\'::jsonb '
                    "WHERE id=CAST(:id AS uuid)"
                ),
                {"id": load_extension()["audit_redactions"][0]["audit_id"]},
            )
    before = database_digest(case["engine"])
    with pytest.raises(DBAPIError):
        execute(case, delete_statements(snapshot))
    assert database_digest(case["engine"]) == before


def test_extended_failure_after_redaction_rolls_back_audits_and_deletes(
    release_case,
):
    case = extend_case(release_case)
    snapshot = capture(case)
    before = database_digest(case["engine"])

    def fail(_number, statement, _db):
        if (
            "reset_audit_row_changed" in statement
            and "synthetic-test-account" not in statement
        ):
            raise RuntimeError("injected after redaction")

    with pytest.raises(RuntimeError):
        execute(case, delete_statements(snapshot), hook=fail)
    assert database_digest(case["engine"]) == before


@pytest.mark.parametrize("tamper", ["audit_payload", "extra_audit", "scope"])
def test_extended_compiler_rejects_scope_expansion_or_changed_backup(
    release_case, tamper
):
    snapshot = capture(extend_case(release_case))
    if tamper == "audit_payload":
        snapshot["reset_audits"][0]["document"] += " "
    elif tamper == "extra_audit":
        snapshot["reset_audits"].append(snapshot["reset_audits"][0])
    else:
        snapshot["scope_sha256"] = "0" * 64
    with pytest.raises(UnsafePurge):
        delete_statements(snapshot)

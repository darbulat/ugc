"""The closed, owner-approved extension; production execution stays separate."""

import copy
import hashlib
import json

from scripts.residual_purge import APPROVED_SCOPE_SHA256, load_plan
from scripts.residual_purge_catalog import digest, require

EXTENSION_SHA256 = (
    "20202397ba01dcc9c000a27eecfd826e1db4c3f4501ab6719c5bb1a9e4e007d2"
)


def load_extension():
    from scripts.residual_purge import MANIFEST_PATH

    path = MANIFEST_PATH.with_name("test-residual-extension-20261120.json")
    extension = json.loads(path.read_text())
    require(digest(extension) == EXTENSION_SHA256, "extension_file_changed")
    require(
        extension["base_scope_sha256"] == APPROVED_SCOPE_SHA256,
        "extension_base_changed",
    )
    return extension


def load_extended_plan():
    plan = copy.deepcopy(load_plan())
    extension = load_extension()
    plan.update(
        extension_sha256=EXTENSION_SHA256,
        schema_heads=extension["schema_heads"],
        retired_actor_ids=extension["retired_actor_ids"],
        reset_audit_redactions=extension["audit_redactions"],
        reset_reason=extension["replacement_reason"],
        delete_rows=69,
    )
    history = next(
        t
        for t in plan["delete_tables"]
        if t["table"] == "creator_identity_observations"
    )
    history["rows"] += 8
    history["row_fingerprints"] = sorted(
        history["row_fingerprints"]
        + [r["fingerprint"] for r in extension["history_rows"]]
    )
    return plan


def approved_scope(snapshot):
    if snapshot["scope_sha256"] == APPROVED_SCOPE_SHA256:
        return load_plan()
    plan = load_extended_plan()
    require(snapshot["scope_sha256"] == digest(plan), "wrong_scope")
    return plan


def allowed_audit_ids(snapshot):
    from scripts.residual_purge import AUDIT_ID

    return [AUDIT_ID] + [
        r["audit_id"]
        for r in approved_scope(snapshot).get("reset_audit_redactions", [])
    ]


def reset_audit_document(document, *, redact):
    result = json.loads(document)
    if redact:
        result["old_values"]["account"] = None
        result["new_values"]["reason"] = load_extension()["replacement_reason"]
    return result


def validate_reset_audits(snapshot, scope):
    expected = scope.get("reset_audit_redactions", [])
    captured = snapshot.get("reset_audits", [])
    require(len(captured) == len(expected), "wrong_reset_audit_count")
    require(
        len({r["audit_id"] for r in captured}) == len(expected),
        "duplicate_reset_audit",
    )
    tests = snapshot.get("rehearsal_reset_hashes", {})
    if tests:
        require("rehearsal_hashes" in snapshot, "test_hashes_in_production")
    for target in expected:
        row = next(
            (r for r in captured if r["audit_id"] == target["audit_id"]), None
        )
        require(row is not None, "reset_audit_missing")
        expected_hash = tests.get(
            target["audit_id"], target["before_row_fingerprint"]
        )
        require(
            hashlib.md5(row["document"].encode()).hexdigest() == expected_hash,
            "reset_audit_fingerprint_changed",
        )
        document = json.loads(row["document"])
        require(
            document["id"] == target["audit_id"]
            and document["entity_id"] == target["actor_id"]
            and document["entity_type"] == "test_registration_reset"
            and document["action"] == "delete",
            "reset_audit_identity_changed",
        )
        require(
            set(document["old_values"]) == {"account", "had_verified_creator"}
            and set(document["new_values"])
            == {
                "reason",
                "messages_sent",
                "registration_deleted",
                "current_verifications_deleted",
                "immutable_identity_audit_retained",
            },
            "reset_audit_payload_shape_changed",
        )

"""Prove unsafe database targets are rejected before any connection."""

from unittest.mock import Mock

import pytest
from sqlalchemy.engine import make_url

from scripts.rehearse_test_residual_purge import main
from scripts.residual_purge import (
    load_plan,
    require_rehearsal_url,
    sandbox_transaction,
    validate_plan,
)
from scripts.residual_purge_catalog import UnsafePurge


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:secret@31.59.106.143/ugc",
        "postgresql://user:secret@127.0.0.1/ugc",
        "postgresql://user:secret@127.0.0.1/ugc_test?host=31.59.106.143",
        "postgresql://user:secret@127.0.0.1/ugc_test?options=-csearch_path=public",
        "postgresql://user:secret@db/ugc_test",
        "sqlite:///:memory:",
    ],
)
def test_remote_and_routing_overrides_are_rejected(url):
    with pytest.raises(UnsafePurge):
        require_rehearsal_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:secret@31.59.106.143/ugc",
        "postgresql://user:secret@127.0.0.1/ugc_test",
        "postgresql://user:secret@127.0.0.1/ugc_test?options=-csearch_path=public",
        "postgresql://user:secret@127.0.0.1/ugc_test?host=31.59.106.143",
    ],
)
def test_no_engine_connection_for_unsafe_target(url):
    engine = Mock(url=make_url(url))
    with pytest.raises(UnsafePurge), sandbox_transaction(engine):
        pytest.fail("Must never enter")
    engine.begin.assert_not_called()


def test_approved_manifest_is_self_consistent():
    plan = load_plan()
    validate_plan(plan)
    assert sum(row["rows"] for row in plan["delete_tables"]) == 61


@pytest.mark.parametrize(
    "change", ["users", "scope", "guard", "redaction", "coverage"]
)
def test_manifest_cannot_expand_scope(change):
    plan = load_plan()
    if change == "users":
        plan["user_ids"][0] = plan["protected_accounts"][0]["user_id"]
    elif change == "scope":
        plan["delete_tables"][0]["rows"] += 1
    elif change == "guard":
        plan["delete_guards"][0]["trigger_name"] = "other_guard"
    elif change == "redaction":
        plan["audit_redaction"]["field"] = "new_values"
    else:
        plan["coverage_update"]["after_profile_seed_count"] = 0
    with pytest.raises(UnsafePurge):
        validate_plan(plan)


@pytest.mark.parametrize("url", ["", "bad-url", None])
def test_missing_or_malformed_database_fails_closed(url):
    with pytest.raises(UnsafePurge):
        require_rehearsal_url(url)


def test_cli_ignores_application_database_and_never_connects(
    monkeypatch, capsys
):
    factory = Mock()
    monkeypatch.setattr(
        "scripts.rehearse_test_residual_purge.create_engine", factory
    )
    monkeypatch.delenv("PURGE_REHEARSAL_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret@31.59.106.143/ugc")
    assert main(["--schema", "financial_test_" + "a" * 32]) == 1
    factory.assert_not_called()
    output = capsys.readouterr().err
    assert "secret" not in output and "31.59" not in output


def test_cli_does_not_log_database_exception_payload(monkeypatch, capsys):
    engine = Mock()
    monkeypatch.setenv(
        "PURGE_REHEARSAL_DATABASE_URL",
        "postgresql://u:secret@localhost/ugc_test",
    )
    monkeypatch.setattr(
        "scripts.rehearse_test_residual_purge.create_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        "scripts.rehearse_test_residual_purge.inspect_rehearsal",
        Mock(side_effect=RuntimeError("secret profile payload")),
    )
    assert main(["--schema", "financial_test_" + "a" * 32]) == 1
    assert "secret" not in capsys.readouterr().err
    engine.dispose.assert_called_once()

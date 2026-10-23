"""Safety regressions run even when the optional local PG is absent."""

from types import SimpleNamespace

import pytest

from tests.e2e import conftest as e2e
from tests.helpers.financial_environment import require_test_database


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "sqlite:///:memory:",
        "postgresql+psycopg://ugc:ugc@localhost/ugc",
        "postgresql+psycopg://ugc:ugc@production.example/ugc_test",
        "postgresql+psycopg://ugc:ugc@localhost/contest",
        "postgresql+psycopg://ugc:ugc@localhost/ugc_test?host=production",
    ],
)
def test_requires_explicit_test_database(url):
    with pytest.raises(ValueError, match="isolated PostgreSQL test"):
        require_test_database(url)


@pytest.mark.parametrize(
    "values",
    [
        {"E2E_DATABASE_URL": "postgresql+psycopg://u:p@prod/ugc"},
        {
            "E2E_DATABASE_URL": "postgresql+psycopg://u:p@localhost/ugc_test",
            "E2E_BASE_URL": "http://127.0.0.1:8001",
        },
        {
            "E2E_TEST_ONLY": "1",
            "E2E_DATABASE_URL": "postgresql+psycopg://u:p@localhost/ugc_test",
            "E2E_BASE_URL": "https://live.example",
        },
        {"E2E_BASE_URL": "https://live.example"},
        {
            "E2E_TEST_ONLY": "1",
            "E2E_DATABASE_URL": "postgresql+psycopg://u:p@localhost/ugc",
            "E2E_BASE_URL": "http://127.0.0.1:8001",
        },
    ],
)
def test_e2e_refuses_before_connection_or_cleanup(monkeypatch, values):
    import os

    for key in tuple(os.environ):
        if key.startswith(("E2E_", "TELEGRAM_E2E_", "MAX_E2E_")):
            monkeypatch.delenv(key)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    calls = []
    monkeypatch.setattr(
        e2e, "create_engine", lambda *a, **k: calls.append("db")
    )
    monkeypatch.setattr(
        e2e.subprocess, "run", lambda *a, **k: calls.append("cleanup")
    )
    with pytest.raises(pytest.UsageError, match="test-only"):
        e2e.pytest_sessionstart(SimpleNamespace(items=[]))
    assert calls == []


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]", "db_test"])
def test_accepts_explicit_isolated_database(host):
    url = f"postgresql+psycopg://ugc:ugc@{host}:5432/ugc_test"
    assert require_test_database(url) == url


def test_financial_invalid_url_refused_before_engine(monkeypatch):
    from tests.helpers import financial_environment as guard

    calls = []
    monkeypatch.setattr(guard, "create_engine", lambda *a, **k: calls.append(a))
    with (
        pytest.raises(ValueError, match="isolated PostgreSQL test"),
        guard.isolated_financial_database(
            "postgresql+psycopg://u:p@localhost/ugc"
        ),
    ):
        pytest.fail("Unsafe context was entered")
    assert calls == []


def test_synthetic_e2e_requires_only_artificial_target():
    from tests.helpers.financial_environment import require_synthetic_e2e

    require_synthetic_e2e(
        {
            "E2E_TEST_ONLY": "1",
            "E2E_BASE_URL": "http://127.0.0.1:8001",
            "E2E_DATABASE_URL": "postgresql+psycopg://u:p@localhost/ugc_test",
            "E2E_BOT_TOKEN": "test-token",
        }
    )


@pytest.mark.timeout(60)
def test_required_pg_option_is_registered_before_root_collection():
    import os
    import subprocess
    import sys
    from pathlib import Path

    env = os.environ.copy()
    env.pop("FINANCIAL_TEST_DATABASE_URL", None)
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--require-financial-postgres",
            "--collect-only",
            "--no-cov",
            "-q",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode != 0
    assert "isolated PostgreSQL test" in result.stderr
    assert "unrecognized arguments" not in result.stderr


@pytest.mark.timeout(60)
def test_independent_sessions_see_committed_data(financial_pg_engine):
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    assert financial_pg_engine is not None
    with (
        Session(financial_pg_engine) as first,
        Session(financial_pg_engine) as second,
    ):
        assert first.scalar(text("SELECT pg_backend_pid()")) != second.scalar(
            text("SELECT pg_backend_pid()")
        )
        first.execute(text("CREATE TABLE harness_probe (value integer)"))
        first.execute(text("INSERT INTO harness_probe VALUES (42)"))
        first.commit()
        assert second.scalar(text("SELECT value FROM harness_probe")) == 42
        assert second.scalar(text("SELECT postgis_version()"))
        assert second.scalar(text("SELECT version_num FROM alembic_version"))
        assert second.scalar(text("SELECT current_schema()")).startswith(
            "financial_test_"
        )


@pytest.mark.timeout(60)
def test_schema_cleanup_and_engine_disposal(financial_pg_engine):
    import os

    from sqlalchemy import event, text

    from tests.helpers.financial_environment import isolated_financial_database

    disposed = []
    with (
        pytest.raises(RuntimeError, match="synthetic test failure"),
        isolated_financial_database(
            os.environ["FINANCIAL_TEST_DATABASE_URL"]
        ) as engine,
    ):
        event.listen(engine, "engine_disposed", lambda e: disposed.append(e))
        with engine.connect() as conn:
            schema = conn.scalar(text("SELECT current_schema()"))
        raise RuntimeError("synthetic test failure")
    assert disposed == [engine]
    with financial_pg_engine.connect() as conn:
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM pg_namespace WHERE nspname = :schema"
                ),
                {"schema": schema},
            )
            == 0
        )
        # Cleanup does not touch another suite's schema or shared PostGIS.
        assert conn.scalar(text("SELECT postgis_version()"))
        assert conn.scalar(text("SELECT version_num FROM alembic_version"))

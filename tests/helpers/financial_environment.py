"""Fail-closed helpers for isolated financial and synthetic E2E tests."""

import os
import re
import subprocess
import sys
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


def require_test_database(value: str | None) -> str:
    """Validate before engine creation; reject routing query overrides."""
    message = "An explicit isolated PostgreSQL test database URL is required"
    try:
        url = make_url(value or "")
        safe = (
            url.drivername in {"postgresql", "postgresql+psycopg"}
            and url.host in {"localhost", "127.0.0.1", "::1", "db_test"}
            and bool(re.fullmatch(r"[a-z][a-z0-9_]*_test", url.database or ""))
            and not url.query
        )
    except (ArgumentError, ValueError, TypeError):
        raise ValueError(message) from None
    if not safe:
        raise ValueError(message)
    assert value is not None
    return value


@contextmanager
def isolated_financial_database(value: str):
    """Migrate a fresh UUID schema; teardown only that schema, never public.

    PostGIS types/functions live in public; application tables and Alembic's
    version table use the private first search_path entry. A worker/CI migration
    invocation always gets its own schema, including on migration failure.
    """
    value = require_test_database(value)
    schema = "financial_test_" + uuid4().hex
    url = make_url(value).set(drivername="postgresql+psycopg")
    admin = create_engine(url, connect_args={"connect_timeout": 5})
    engine = None
    created = False
    try:
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
            conn.execute(
                text(
                    'CREATE EXTENSION IF NOT EXISTS "uuid-ossp" '
                    "WITH SCHEMA public"
                )
            )
            conn.execute(
                text(
                    "CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public"
                )
            )
        scoped_url = url.update_query_dict(
            {"options": f"-csearch_path={schema},public"}
        )
        env = os.environ.copy()
        env.pop("MIGRATION_SCHEMA", None)
        env["DATABASE_URL"] = scoped_url.render_as_string(hide_password=False)
        root = Path(__file__).resolve().parents[2]
        # Commit each revision: legacy enum additions must commit before later
        # revisions reference their values (PG UnsafeNewEnumValueUsage).
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from alembic import command; "
                    "from alembic.config import Config; "
                    "from alembic.script import ScriptDirectory; "
                    "c = Config('alembic.ini'); "
                    "s = ScriptDirectory.from_config(c); "
                    "revs = list(s.walk_revisions()); "
                    "[command.upgrade(c, r.revision) for r in reversed(revs)]"
                ),
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode:
            raise RuntimeError(
                "Isolated test migrations failed:\n" + result.stderr
            )
        engine = create_engine(
            scoped_url,
            pool_size=2,
            max_overflow=0,
            connect_args={"connect_timeout": 5},
        )
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        try:
            if created:
                with admin.begin() as conn:
                    conn.execute(
                        text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                    )
        finally:
            admin.dispose()


def require_synthetic_e2e(env: Mapping[str, str]) -> None:
    """URLs alone never authorize cleanup or use of an external app."""
    keys = ("E2E_DATABASE_URL", "E2E_BASE_URL", "E2E_MINIAPP_URL")
    if not any(env.get(key) for key in keys):
        return
    message = "E2E requires explicit test-only marker and synthetic local app"
    if env.get("E2E_TEST_ONLY") != "1":
        raise ValueError(message)
    for key in ("E2E_BASE_URL", "E2E_MINIAPP_URL"):
        if not env.get(key):
            continue
        url = urlsplit(env[key])
        if (
            url.scheme != "http"
            or url.hostname
            not in {
                "localhost",
                "127.0.0.1",
                "::1",
                "admin_test",
                "miniapp_test",
                "testserver",
            }
            or url.username
            or url.password
        ):
            raise ValueError(message)
    if env.get("E2E_BOT_TOKEN", "test-token") != "test-token":
        raise ValueError(message)
    if env.get("E2E_DATABASE_URL"):
        try:
            require_test_database(env["E2E_DATABASE_URL"])
        except ValueError:
            raise ValueError(message) from None


if __name__ == "__main__":
    with (
        isolated_financial_database(
            require_test_database(os.environ.get("FINANCIAL_TEST_DATABASE_URL"))
        ) as migrated,
        migrated.connect() as connection,
    ):
        print(
            "Isolated migrations ready:",
            connection.scalar(text("SELECT version_num FROM alembic_version")),
        )

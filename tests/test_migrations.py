"""Tests for Alembic migrations."""

import os
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url


def _alembic_config() -> Config:
    """Build Alembic config from ini file."""

    root = Path(__file__).resolve().parents[1]
    return Config(str(root / "alembic.ini"))


def _psycopg_conninfo(database_url: str) -> str:
    """Convert SQLAlchemy-style URL to conninfo string for psycopg.

    psycopg expects 'postgresql://...' or libpq key=value form.
    SQLAlchemy uses 'postgresql+psycopg://...' which psycopg does not accept.
    """
    url = make_url(database_url)
    # Build standard postgresql:// URI (no +dialect)
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _build_urls(database_url: str, schema: str) -> tuple[str, str]:
    """Return (admin_url, migrations_url) with search_path set."""

    url = make_url(database_url)
    admin_query = {k: v for k, v in url.query.items() if k != "options"}
    admin_url = url.set(query=admin_query)
    migrations_url = url.set(
        query={**admin_query, "options": f"-csearch_path={schema}"}
    )
    return str(admin_url), str(migrations_url)


@pytest.mark.integration
def test_migrations_upgrade_downgrade_upgrade() -> None:
    """Ensure upgrade/downgrade/upgrade completes without errors."""

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for migration tests.")

    schema_name = "migration_test"
    conninfo = _psycopg_conninfo(database_url)

    with psycopg.connect(conninfo, autocommit=True) as connection:
        connection.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')

    config = _alembic_config()
    os.environ["DATABASE_URL"] = database_url

    try:
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        command.upgrade(config, "head")
    finally:
        with psycopg.connect(conninfo, autocommit=True) as connection:
            connection.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')

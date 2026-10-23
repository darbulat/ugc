"""Schema parity and upgrade preflight on an actual PostgreSQL server."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import UniqueConstraint, inspect
from sqlalchemy.engine import make_url

from ugc_bot.infrastructure.db.models import ReferralIncomeEntryModel


@pytest.mark.asyncio
async def test_income_constraints_match_migrations(legacy_pg):
    engine, _ = legacy_pg
    async with engine.connect() as conn:
        schema = await conn.run_sync(
            lambda c: c.exec_driver_sql("SELECT current_schema()").scalar_one()
        )
    # Replace the metadata-created schema with a genuine upgrade from base.
    async with engine.begin() as conn:
        await conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        await conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    url = make_url(os.environ["FINANCIAL_TEST_DATABASE_URL"]).update_query_dict(
        {"options": f"-csearch_path={schema},public"}
    )
    env = dict(
        os.environ, DATABASE_URL=url.render_as_string(hide_password=False)
    )
    env.pop("MIGRATION_SCHEMA", None)
    for target in ("0059_add_deleted_status_to_enums", "head"):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", target],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stderr
    async with engine.connect() as conn:
        actual = await conn.run_sync(
            lambda c: {
                tuple(x["column_names"])
                for x in inspect(c).get_unique_constraints(
                    "referral_income_entries"
                )
            }
        )
    expected = {
        tuple(c.columns.keys())
        for c in ReferralIncomeEntryModel.__table__.constraints
        if isinstance(c, UniqueConstraint)
    }
    assert actual == expected

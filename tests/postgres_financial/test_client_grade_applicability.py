"""CLIENT N/A is truthful; creator grade/history must not be fabricated."""

import importlib
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from tests.postgres_financial.test_financial_ledger_schema import put
from ugc_bot.infrastructure.db.base import Base

pytest_plugins = ("tests.postgres_financial.test_financial_ledger_schema",)


def test_creator_grade_cannot_be_not_applicable(
    financial_pg_engine, ledger_seed
):
    row = {
        **ledger_seed["rate"],
        "id": uuid4(),
        "side": "creator",
        "verified_count": None,
    }
    with (
        financial_pg_engine.begin() as conn,
        pytest.raises(IntegrityError, match="ck_snapshot_grade_applicable"),
        conn.begin_nested(),
    ):
        put(conn, "rate_snapshots", row)


def test_metadata_matches_actual_migrated_grade_applicability(
    financial_pg_engine,
):
    with financial_pg_engine.connect() as conn:
        columns = {
            c["name"]: c for c in inspect(conn).get_columns("rate_snapshots")
        }
        assert columns["verified_count"]["nullable"] is True
        table = Base.metadata.tables["rate_snapshots"]
        assert table.c.verified_count.nullable is True
        # Compare to the actual sole head, not this older additive revision:
        # later additive migrations must not make the grade-parity test stale.
        from pathlib import Path

        from alembic.script import ScriptDirectory

        scripts = ScriptDirectory(
            str(
                Path(__file__).resolve().parents[2]
                / "src/ugc_bot/infrastructure/db/migrations"
            )
        )
        heads = scripts.get_heads()
        assert len(heads) == 1
        assert (
            conn.scalar(text("SELECT version_num FROM alembic_version"))
            == heads[0]
        )


def test_downgrade_refuses_na_history_without_fabricated_backfill(
    financial_pg_engine, ledger_seed
):
    row = {**ledger_seed["rate"], "id": uuid4(), "verified_count": None}
    revision = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.client_grade_na"
    )
    query = text("SELECT * FROM rate_snapshots ORDER BY id")
    with financial_pg_engine.begin() as conn:
        put(conn, "rate_snapshots", row)
    with financial_pg_engine.begin() as conn:
        before = conn.execute(query).all()
        with (
            pytest.raises(
                RuntimeError, match="client_grade_na_history_prevents_downgrade"
            ),
            conn.begin_nested(),
            Operations.context(MigrationContext.configure(conn)),
        ):
            revision.downgrade()
        assert conn.execute(query).all() == before
        column = next(
            c
            for c in inspect(conn).get_columns("rate_snapshots")
            if c["name"] == "verified_count"
        )
        assert column["nullable"] is True

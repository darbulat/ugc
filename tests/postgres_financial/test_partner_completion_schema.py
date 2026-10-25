"""Operational history supports an empty rollback and genuine reinstallation."""

import importlib
import os

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect

from tests.helpers.financial_environment import isolated_financial_database
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.replacement_schema import replacement_tables


def test_empty_operational_migrations_round_trip_real_postgres():
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Explicit isolated PostgreSQL test database is required")
    package = "ugc_bot.infrastructure.db.migrations.versions."
    names = (
        "0111_lead_review",
        "0112_referral_binding_audit",
        "0114_refund_replacements",
    )
    migrations = [importlib.import_module(package + name) for name in names]
    with (
        isolated_financial_database(
            url, target_revision="0114_refund_replacements"
        ) as engine,
        engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        for migration in reversed(migrations):
            migration.downgrade()
        for migration in migrations:
            migration.upgrade()
        assert {
            "accompaniment_lead_reviews",
            "referral_binding_corrections",
            "paid_replacement_requests",
        } <= set(inspect(connection).get_table_names())
    assert (
        replacement_tables(Base.metadata)["requests"]
        is Base.metadata.tables["paid_replacement_requests"]
    )

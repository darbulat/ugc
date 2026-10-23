"""Real PostgreSQL fixtures; no SQLite integration fixture inheritance."""

import os
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from tests.helpers.financial_environment import isolated_financial_database
from tests.postgres_financial.legacy_support import legacy_pg as legacy_pg


def pytest_collection_modifyitems(items):
    suite = Path(__file__).parent
    for item in items:
        if item.path.is_relative_to(suite) and not item.get_closest_marker(
            "timeout"
        ):
            item.add_marker(pytest.mark.timeout(60))


@pytest.fixture(scope="session")
def financial_pg_engine(request):
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        if request.config.getoption("--require-financial-postgres"):
            pytest.fail("FINANCIAL_TEST_DATABASE_URL is required")
        pytest.skip("Local unit-only run: FINANCIAL_TEST_DATABASE_URL not set")
    with isolated_financial_database(url) as engine:
        yield engine


@pytest.fixture
def financial_session_factory(financial_pg_engine):
    """Independent sessions for concurrency tests; no outer rollback."""
    return sessionmaker(financial_pg_engine, expire_on_commit=False)

"""SQLite is a legacy-flow fixture only, never a financial race oracle."""

import pytest
from sqlalchemy.dialects.sqlite import dialect
from sqlalchemy.schema import CreateTable

from ugc_bot.infrastructure.db.models import (
    LegacyFinancialCaseEventModel,
    LegacyFinancialCaseModel,
    LegacyFinancialGuardModel,
)


@pytest.mark.parametrize(
    "model",
    [
        LegacyFinancialCaseModel,
        LegacyFinancialCaseEventModel,
        LegacyFinancialGuardModel,
    ],
)
def test_legacy_case_timestamp_defaults_compile_portably(model):
    ddl = str(CreateTable(model.__table__).compile(dialect=dialect()))
    assert "now()" not in ddl.lower()
    assert "current_timestamp" in ddl.lower()

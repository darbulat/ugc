"""Registration hook for immutable readable publication and acceptance."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.payout_contract_schema import (
    IMMUTABILITY_SQL,
    contract_tables,
)

TABLE_MAP = contract_tables(Base.metadata)
TABLES = tuple(TABLE_MAP.values())
for table in TABLES:
    sa.event.listen(
        table,
        "after_create",
        sa.DDL(
            IMMUTABILITY_SQL
            + "CREATE TRIGGER payout_contract_immutable BEFORE UPDATE "
            f"OR DELETE OR TRUNCATE ON {table.name} FOR EACH STATEMENT "
            "EXECUTE FUNCTION payout_contract_deny_mutation();"
        ).execute_if(dialect="postgresql"),
    )

"""Metadata registration for immutable payout authority and mutable state."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.payout_schema import (
    GUARD_SQL,
    IMMUTABILITY_SQL,
    SCOPE_GUARD_SQL,
    payout_tables,
)

TABLE_MAP = payout_tables(Base.metadata)
TABLES = tuple(TABLE_MAP.values())
for name, table in TABLE_MAP.items():
    if name != "states":
        sa.event.listen(
            table,
            "after_create",
            sa.DDL(
                IMMUTABILITY_SQL
                + f"CREATE TRIGGER payout_immutable BEFORE UPDATE OR DELETE OR "
                f"TRUNCATE ON {table.name} FOR EACH STATEMENT "
                "EXECUTE FUNCTION payout_deny_mutation();"
            ).execute_if(dialect="postgresql"),
        )

sa.event.listen(
    TABLE_MAP["movement_links"],
    "after_create",
    sa.DDL(GUARD_SQL + SCOPE_GUARD_SQL).execute_if(dialect="postgresql"),
)

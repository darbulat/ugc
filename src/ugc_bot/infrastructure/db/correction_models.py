"""Correction metadata registration shares the additive migration builder."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.correction_schema import (
    correction_tables,
    correction_trigger_sql,
)

TABLE_MAP = correction_tables(Base.metadata)
TABLES = tuple(TABLE_MAP.values())
for key, table in TABLE_MAP.items():
    sa.event.listen(
        table,
        "after_create",
        sa.DDL(correction_trigger_sql({key: table})).execute_if(
            dialect="postgresql"
        ),
    )

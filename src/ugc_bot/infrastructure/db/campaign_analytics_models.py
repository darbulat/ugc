"""Manual marketing analytics metadata."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.campaign_analytics_schema import (
    analytics_tables,
    immutability_sql,
)

TABLES = analytics_tables(Base.metadata)
SOURCES, EVENTS, ACTIONS, COMMANDS, PILOTS = TABLES
for table in TABLES:
    sa.event.listen(
        table,
        "after_create",
        sa.DDL(immutability_sql((table,))).execute_if(dialect="postgresql"),
    )

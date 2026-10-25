"""Campaign runtime metadata imported by the application registry."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.campaign_runtime_schema import (
    immutability_sql,
    runtime_tables,
)

TABLES = runtime_tables(Base.metadata)
(
    COMMANDS,
    STATES,
    SUBMISSIONS,
    DECISIONS,
    JOBS,
    CAPACITY,
    ATTEMPTS,
    OUTCOMES,
    RESPONSES,
    OBSERVATIONS,
) = TABLES
for table in TABLES:
    sa.event.listen(
        table,
        "after_create",
        sa.DDL(immutability_sql((table,))).execute_if(dialect="postgresql"),
    )

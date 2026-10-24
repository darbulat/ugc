"""Root-registerable draft metadata; no queue, moderation or transport."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.campaign_review_schema import (
    draft_tables,
    immutability_sql,
)

TABLES = draft_tables(Base.metadata)
COMMANDS, DRAFTS, REVISIONS = TABLES
for table in TABLES:
    sa.event.listen(
        table,
        "after_create",
        sa.DDL(immutability_sql((table,))).execute_if(dialect="postgresql"),
    )

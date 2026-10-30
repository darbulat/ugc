"""Register persisted selection closure and maturity with complete metadata."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.selection_maturity_schema import (
    selection_maturity_guards,
    selection_maturity_tables,
)

TABLES = selection_maturity_tables(Base.metadata, per_item=True)
sa.event.listen(
    TABLES["schedules"],
    "after_create",
    sa.DDL(selection_maturity_guards(TABLES, per_item=True)).execute_if(
        dialect="postgresql"
    ),
)

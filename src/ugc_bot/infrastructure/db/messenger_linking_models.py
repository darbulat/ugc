"""Runtime metadata uses the frozen table builder from its revision."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.messenger_linking_schema import (
    FACT_KEYS,
    linking_tables,
)

TABLES = linking_tables(Base.metadata)
CHALLENGES = TABLES["challenges"]
CLAIMS = TABLES["claims"]
STATE = TABLES["state"]
ACTIVE_OWNER = TABLES["active_owner"]
ACTIVE_TG = TABLES["active_tg"]
COMMANDS = TABLES["commands"]
NATIVE_ATTEMPTS = TABLES["native_attempts"]
NATIVE_RESULTS = TABLES["native_results"]
EVENTS = TABLES["events"]

# Full metadata.create_all must protect facts just like the Alembic revision.

MODEL_GUARD_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION messenger_link_deny_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'messenger_link_evidence_immutable' USING ERRCODE='23514';
END $$;
"""
for key in FACT_KEYS:
    table = TABLES[key]
    sa.event.listen(
        table,
        "after_create",
        sa.DDL(
            MODEL_GUARD_FUNCTION_SQL + f"CREATE TRIGGER {table.name}_immutable "
            f"BEFORE UPDATE OR DELETE OR TRUNCATE ON {table.name} "
            "FOR EACH STATEMENT "
            "EXECUTE FUNCTION messenger_link_deny_mutation();"
        ).execute_if(dialect="postgresql"),
    )

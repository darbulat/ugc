"""The additive identity schema stores safe facts, never launch credentials."""

import importlib
import importlib.util

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def test_frozen_linking_schema_has_no_clear_bearer_columns_or_target_user_fk():
    module = "ugc_bot.infrastructure.db.messenger_linking_schema"
    assert importlib.util.find_spec(module) is not None, (
        "frozen linking schema missing"
    )
    schema = importlib.import_module(module)
    metadata = sa.MetaData()
    sa.Table(
        "users",
        metadata,
        sa.Column("user_id", postgresql.UUID, primary_key=True),
    )
    tables = schema.linking_tables(metadata)
    assert len(tables) == 9
    for table in tables.values():
        assert not {"token", "launch_url", "raw_token"}.intersection(
            table.c.keys()
        )
        assert str(
            sa.schema.CreateTable(table).compile(dialect=postgresql.dialect())
        )
    assert not tables["active_tg"].c.telegram_id.foreign_keys
    assert not tables["native_attempts"].c.sender_id.foreign_keys
    assert not tables["claims"].c.telegram_id.foreign_keys
    for key in schema.FACT_KEYS:
        assert tables[key].name in schema.immutability_sql(tables)
    assert "FOR EACH STATEMENT" in schema.immutability_sql(tables)

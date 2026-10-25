"""Registered immutable replacement facts, separate from billable delivery."""

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.replacement_schema import replacement_tables

TABLES = replacement_tables(Base.metadata)

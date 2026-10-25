"""Register immutable financial sources; final metadata hook installs guards."""

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.manual_grant_schema import manual_grant_tables

TABLES = manual_grant_tables(Base.metadata)

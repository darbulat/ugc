"""Register source tables; SQL migrations install deferred provenance checks."""

from ugc_bot.infrastructure.db.accompaniment_refund_schema import (
    accompaniment_refund_tables,
)
from ugc_bot.infrastructure.db.base import Base

TABLES = accompaniment_refund_tables(Base.metadata)

"""Register immutable delayed original assessment source facts."""

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.refund_original_schema import (
    refund_original_tables,
)

TABLES = refund_original_tables(Base.metadata)

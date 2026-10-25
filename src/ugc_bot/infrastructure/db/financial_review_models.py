"""Register immutable financial sources; final metadata hook installs guards."""

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.financial_review_schema import (
    financial_review_tables,
)

TABLES = financial_review_tables(Base.metadata)

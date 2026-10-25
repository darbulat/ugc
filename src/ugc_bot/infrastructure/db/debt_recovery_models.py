"""Repayment tables share the production metadata registry."""

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.debt_recovery_schema import debt_recovery_tables

COMMANDS, OBSERVATIONS, APPLICATIONS = debt_recovery_tables(Base.metadata)

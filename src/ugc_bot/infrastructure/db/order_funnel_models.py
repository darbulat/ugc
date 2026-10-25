"""Intake telemetry metadata, independent of money and recipient attribution."""

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.order_funnel_schema import funnel_table

FUNNEL = funnel_table(Base.metadata)

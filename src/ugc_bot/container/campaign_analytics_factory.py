"""Manual marketing evidence graph; no financial writes or live connectors."""

from ugc_bot.application.services.campaign_analytics_service import (
    CampaignAnalyticsService,
)
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.repositories.campaign_analytics import (
    SqlAlchemyCampaignAnalyticsRepository,
)


def build_campaign_analytics(transactions, *, clock=None):
    if transactions is None:
        return {}
    return {
        "campaign_analytics_service": CampaignAnalyticsService(
            SqlAlchemyCampaignAnalyticsRepository(), clock or SystemClock()
        )
    }

"""Manual paid subscriptions and optional campaign access checks."""

from ugc_bot.application.services.subscription_campaign_access import (
    SubscriptionCampaignAccess,
)
from ugc_bot.infrastructure.db.repositories.subscription_campaign_usage import (
    SqlAlchemySubscriptionCampaignUsage,
)
from ugc_bot.infrastructure.db.repositories.subscriptions import (
    SqlAlchemySubscriptionRepository,
)


def build_subscription_access(config):
    if not config.campaign.require_paid_subscription:
        return None
    return SubscriptionCampaignAccess(
        SqlAlchemySubscriptionRepository(),
        SqlAlchemySubscriptionCampaignUsage(),
    )

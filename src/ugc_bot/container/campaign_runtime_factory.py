"""Campaign runtime graph; transport needs explicit enablement."""

from ugc_bot.application.services.campaign_capacity_service import (
    CampaignCapacityService,
)
from ugc_bot.application.services.campaign_delivery_service import (
    CampaignDeliveryService,
)
from ugc_bot.application.services.campaign_moderation_service import (
    CampaignModerationService,
)
from ugc_bot.application.services.campaign_response_service import (
    CampaignResponseService,
)
from ugc_bot.application.services.campaign_submission_service import (
    CampaignSubmissionService,
)
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.repositories.campaign_delivery import (
    SqlAlchemyCampaignDeliveryRepository,
)
from ugc_bot.infrastructure.db.repositories.campaign_moderation import (
    SqlAlchemyCampaignModerationRepository,
)
from ugc_bot.infrastructure.db.repositories.campaign_review import (
    SqlAlchemyCampaignReviewRepository,
)
from ugc_bot.infrastructure.db.repositories.campaigns import (
    SqlAlchemyCampaignRepository,
)


def build_campaign_runtime(
    config,
    transactions,
    *,
    miniapp_url=None,
    clock=None,
    bot=None,
    transport=None,
    delivery_enabled=False,
    access=None,
):
    if transactions is None:
        return {}
    clock = clock or SystemClock()
    foundation = SqlAlchemyCampaignRepository()
    drafts = SqlAlchemyCampaignReviewRepository(foundation)
    repo = SqlAlchemyCampaignModerationRepository(foundation, drafts)
    delivery = SqlAlchemyCampaignDeliveryRepository(repo, clock)
    capacity = CampaignCapacityService(repo, clock)
    base = (
        miniapp_url
        or config.webhook.webhook_base_url.rstrip("/") + "/miniapp/app.html"
    )
    worker = None
    if delivery_enabled:
        if transport is None:
            if bot is None:
                raise ValueError("campaign_transport_required")
            from ugc_bot.infrastructure.messenger.notice_receipts import (
                TelegramNoticeReceipts,
            )

            transport = TelegramNoticeReceipts(bot)
        worker = CampaignDeliveryService(
            delivery,
            transactions,
            transport,
            clock,
            enabled=True,
            access=access,
        )
    return {
        "campaign_submission_service": CampaignSubmissionService(
            repo, capacity, clock, base, access=access
        ),
        "campaign_moderation_service": CampaignModerationService(
            repo, capacity, clock
        ),
        "campaign_capacity_service": capacity,
        "campaign_response_service": CampaignResponseService(delivery, clock),
        "campaign_delivery_service": worker,
    }

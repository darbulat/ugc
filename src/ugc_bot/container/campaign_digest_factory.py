"""A separate default-off delivery gate, independent of critical notices."""

from urllib.parse import urlsplit

from ugc_bot.application.services.campaign_digest_service import (
    CampaignDigestService,
)
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.repositories.campaign_digest import (
    SqlAlchemyCampaignDigestRepository,
)
from ugc_bot.infrastructure.messenger.notice_receipts import (
    MaxNoticeReceipts,
    RoutedNoticeReceipts,
    TelegramNoticeReceipts,
)


def enabled(config):
    feedback = getattr(config, "feedback", None)
    return bool(
        getattr(feedback, "feedback_enabled", False)
        and getattr(feedback, "campaign_digest_enabled", False)
    )


def build_campaign_digest(config, transactions, bot, *, max_session=None):
    if not enabled(config):
        return None
    if transactions is None:
        raise ValueError("DATABASE_URL is required for campaign summaries.")
    transports = {"telegram": TelegramNoticeReceipts(bot)}
    max_config = config.max_bot
    if max_config and max_config.token.strip() and max_session is not None:
        transports["max"] = MaxNoticeReceipts(max_session, max_config.token)
    telegram_base = config.webhook.webhook_base_url.rstrip("/")
    try:
        parsed = urlsplit(max_config.webhook_url if max_config else "")
        max_base = (
            f"{parsed.scheme}://{parsed.netloc}" if parsed.hostname else ""
        )
    except ValueError:
        max_base = ""
    return CampaignDigestService(
        SqlAlchemyCampaignDigestRepository(),
        transactions,
        RoutedNoticeReceipts(transports),
        SystemClock(),
        {
            "telegram": telegram_base + "/miniapp/app.html"
            if telegram_base
            else "",
            "max": max_base + "/miniapp/max_app.html" if max_base else "",
        },
    )

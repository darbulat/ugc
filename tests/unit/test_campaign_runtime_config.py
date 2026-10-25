import pytest
from pydantic import ValidationError


def test_campaign_delivery_is_off_until_explicitly_enabled(monkeypatch):
    from ugc_bot.config import AppConfig

    for key in (
        "CAMPAIGN_DELIVERY_ENABLED",
        "CAMPAIGN_REQUIRE_PAID_SUBSCRIPTION",
    ):
        monkeypatch.delenv(key, raising=False)
    config = AppConfig.model_validate(
        dict(
            BOT_TOKEN="test-token",
            DATABASE_URL="sqlite:///:memory:",
            CAMPAIGN_DELIVERY_ENABLED=True,
            CAMPAIGN_REQUIRE_PAID_SUBSCRIPTION=True,
        )
    )
    assert config.campaign.delivery_enabled is True
    assert config.campaign.require_paid_subscription is True
    assert (
        AppConfig.model_validate(
            dict(BOT_TOKEN="test-token", DATABASE_URL="sqlite:///:memory:")
        ).campaign.delivery_enabled
        is False
    )


def test_campaign_loop_cannot_spin_without_interval():
    from ugc_bot.config import CampaignRuntimeConfig

    with pytest.raises(ValidationError):
        CampaignRuntimeConfig(CAMPAIGN_DELIVERY_INTERVAL_SECONDS=0)

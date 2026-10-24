"""Both configured referral bot names survive supported config inputs."""

import pytest

from ugc_bot.config import AppConfig, load_config


@pytest.mark.parametrize("source", ["flat", "nested", "environment"])
def test_partner_referral_names_survive_flat_nested_and_env(
    source, monkeypatch
):
    values = {
        "BOT_TOKEN": "test-token",
        "REFERRAL_BOT_USERNAME": "synthetic_tg",
        "MAX_REFERRAL_BOT_USERNAME": "synthetic_max",
    }
    if source == "flat":
        config = AppConfig.model_validate(values)
    elif source == "nested":
        payload = AppConfig.model_validate(
            {"BOT_TOKEN": "test-token"}
        ).model_dump(by_alias=True)
        payload["referral"].update(
            {key: value for key, value in values.items() if key != "BOT_TOKEN"}
        )
        config = AppConfig.model_validate(payload)
    else:
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        config = load_config()
    assert config.referral.referral_bot_username == "synthetic_tg"
    assert config.referral.max_referral_bot_username == "synthetic_max"

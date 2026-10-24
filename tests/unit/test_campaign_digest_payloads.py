"""Native summary links and localized text cannot assert work success."""

from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from ugc_bot.application.campaign_digest_ports import DigestSource
from ugc_bot.application.notice_delivery_ports import DeliveryContact
from ugc_bot.application.services.campaign_digest_service import _render
from ugc_bot.config import AppConfig
from ugc_bot.container.campaign_digest_factory import build_campaign_digest


def source(locale="ru", channel="telegram"):
    actor, order = uuid4(), uuid4()
    return DigestSource(
        order,
        actor,
        {
            "source": "legacy_feedback",
            "role": "client",
            "total": 30,
            "states": {"legacy_pending": 30},
            "contact_accepted": None,
        },
        DeliveryContact(actor, channel, "123", locale, "active"),
        "a" * 64,
    )


@pytest.mark.parametrize("locale", ["ru", "en-US", "kk", "be", "uz", "unknown"])
@pytest.mark.parametrize("channel", ["telegram", "max"])
def test_localized_native_links_keep_exact_own_summary_context(locale, channel):
    value = source(locale, channel)
    language, text, url, label = _render(
        value, {channel: "https://example.test/miniapp/app.html?lang=en"}
    )
    assert language == (locale.split("-")[0] if locale != "unknown" else "ru")
    assert "30" in text and "success" not in text
    assert str(value.recipient_id) not in text and "legacy_pending" not in text
    assert parse_qs(urlsplit(url).query) == {
        "summary": [str(value.order_id)],
        "lang": ["en"],
    }
    assert label


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://example.test/app.html",
        "https:///app.html",
        "https://user:secret@example.test/app.html",
        "https://example.test/app.html#fragment",
        "https://example.test:443/app.html",
        "https://example.test:bad/app.html",
        "https://example.test/app.html?summary=foreign",
        "https://example.test/app.html?view=partner",
        "https://example.test/app.html?assignment=foreign",
        "https://example.test/app.html?selection=foreign",
        "https://example.test/app.html?checkout=foreign",
        "https://example.test/app.html?campaign=foreign",
        "https://example.test/app.html?unsafe=two words",
    ],
)
def test_unavailable_or_ambiguous_launch_urls_fail_before_transport(url):
    with pytest.raises(ValueError):
        _render(source(), {"telegram": url})


@pytest.mark.parametrize(
    "webhook", ["https://example.test/hooks/max", "https://["]
)
def test_max_factory_uses_only_configured_native_host_without_io(webhook):
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "synthetic",
            "FEEDBACK_ENABLED": True,
            "CAMPAIGN_DIGEST_ENABLED": True,
            "MAX_BOT_TOKEN": "synthetic",
            "MAX_BOT_WEBHOOK_URL": webhook,
        }
    )
    worker = build_campaign_digest(
        config, object(), object(), max_session=object()
    )
    assert worker is not None
    assert "max" in worker.transport.transports
    if webhook == "https://[":
        assert worker.launch_urls["max"] == ""
    else:
        assert (
            worker.launch_urls["max"]
            == "https://example.test/miniapp/max_app.html"
        )

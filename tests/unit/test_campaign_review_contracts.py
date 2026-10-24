"""No recipient selection, invented metrics or mutable sealed bytes."""

from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest


def content_payload():
    return {
        "title": "A task",
        "text": "Exact creator task",
        "link": "https://product.example/item",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"recipient_ids": []},
        {"country": None},
        {"topics_any": []},
        {"social": {"platform": "instagram", "followers_min": True}},
        {"social": {"platform": "instagram", "followers_min": -1}},
        {
            "social": {
                "platform": "instagram",
                "followers_min": 8,
                "followers_max": 7,
            }
        },
        {"social": {"platform": "email"}},
        {"social": {"platform": "vk", "verified": True}},
    ],
)
def test_segment_rejects_non_allowlisted_or_ambiguous_intent(payload):
    from ugc_bot.domain.campaign_review import CampaignSegmentV1

    with pytest.raises(ValueError):
        CampaignSegmentV1.parse(payload)


def test_segment_normalizes_existing_values_without_inventing_a_taxonomy():
    from ugc_bot.domain.campaign_review import CampaignSegmentV1

    segment = CampaignSegmentV1.parse(
        {
            "city": "  ОрЁл  ",
            "topics_any": [" Beauty ", "beauty"],
            "social": {"platform": "youtube", "followers_min": 0},
        }
    )
    assert segment.payload == {
        "city": "орел",
        "topics_any": ["beauty"],
        "social": {"platform": "youtube", "followers_min": 0},
    }
    assert CampaignSegmentV1.parse({}).payload == {}
    with pytest.raises(FrozenInstanceError):
        segment.city = "other"


@pytest.mark.parametrize(
    "url",
    [
        "http://x.test",
        "https://user:secret@x.test",
        "https://127.0.0.1/x",
        "https://localhost/x",
        "https://x.test/a\nb",
        "https://x.test:bad/x",
    ],
)
def test_content_rejects_unsafe_link_without_network_io(url):
    from ugc_bot.domain.campaign_review import CampaignDraftContent

    with pytest.raises(ValueError):
        CampaignDraftContent.parse({**content_payload(), "link": url})


def test_content_requires_actual_policy_limits_and_preserves_exact_text():
    from ugc_bot.domain.campaign_review import CampaignDraftContent

    content = CampaignDraftContent.parse(
        {"title": "  Task  ", "text": "  A\n<literal>🙂  "}
    )
    assert content.payload == {"title": "Task", "text": "A\n<literal>🙂"}
    content.validate(
        {"title_max_chars": 4, "text_max_chars": 13, "link_max_chars": 1}
    )
    with pytest.raises(ValueError):
        content.validate(
            {"title_max_chars": 3, "text_max_chars": 13, "link_max_chars": 1}
        )
    with pytest.raises(ValueError):
        content.validate({})


def envelope(*, text="body", sender="Brand", version="template-v1", **changes):
    from ugc_bot.domain.campaign_envelope import CampaignEnvelopeV1
    from ugc_bot.domain.campaign_review import CampaignDraftContent

    arguments = dict(
        content=CampaignDraftContent.parse({"title": "T", "text": text}),
        campaign_id=UUID(int=7),
        sender_label=sender,
        sender_source="brand:real-row",
        template_version=version,
        default_locale="ru",
        miniapp_url="https://app.example/miniapp/app.html",
        templates={
            locale: ("From", "Open")
            for locale in ("ru", "en", "kk", "be", "uz")
        },
    )
    return CampaignEnvelopeV1.render(**{**arguments, **changes})


def test_five_locale_envelope_binds_sender_version_text_and_native_uuid():
    value = envelope()
    assert len(value.locales) == 5
    payload = value.payload
    assert payload["locales"]["ru"]["text"] == "From Brand\n\nT\n\nbody"
    assert (
        payload["locales"]["ru"]["action_url"]
        == "https://app.example/miniapp/app.html?campaign=00000000-0000-0000-0000-000000000007"
    )
    assert value.digest != envelope(sender="Other").digest
    assert value.digest != envelope(version="template-v2").digest
    payload["locales"]["ru"]["text"] = "caller changed it"
    assert value.payload["locales"]["ru"]["text"] == "From Brand\n\nT\n\nbody"


def test_complete_body_counts_sender_and_astral_characters_at_real_boundaries():
    # Exact envelope prefix is 15 ASCII characters with sender='Brand'.
    value = envelope(text="x" * (4096 - 15))
    assert len(value.payload["locales"]["ru"]["text"]) == 4096
    with pytest.raises(ValueError, match="technical_message"):
        envelope(text="x" * (4097 - 15))
    with pytest.raises(ValueError, match="technical_message"):
        envelope(text="🙂" * 2048)


def test_typed_constructors_cannot_bypass_validated_content_or_segment():
    from ugc_bot.domain.campaign_review import (
        CampaignDraftContent,
        CampaignSegmentV1,
        CampaignSocialFilter,
    )

    for construct in (
        lambda: CampaignDraftContent("", "body"),
        lambda: CampaignDraftContent("T", "body", "http://unsafe.test"),
        lambda: CampaignSegmentV1(city="Not normalized"),
        lambda: CampaignSegmentV1(topics_any=["mutable"]),
        lambda: CampaignSocialFilter("instagram", followers_min=True),
    ):
        with pytest.raises(ValueError):
            construct()


def test_frozen_envelope_rejects_mutable_or_incomplete_locale_payloads():
    from dataclasses import replace

    value = envelope()
    for locales in (
        list(value.locales),
        value.locales[:4],
        (value.locales[0],) * 5,
    ):
        with pytest.raises(ValueError):
            replace(value, locales=locales)
    with pytest.raises(ValueError):
        replace(value.locales[0], text="x" * 4097)
    with pytest.raises(ValueError):
        replace(value.locales[0], action_label="Open\nforeign action")


@pytest.mark.parametrize(
    "changes",
    [
        {"campaign_id": UUID(int=0)},
        {"default_locale": "de"},
        {"templates": {"ru": ("From", "Open")}},
        {"miniapp_url": "https://app.example/miniapp?owner=forged"},
        {"miniapp_url": "https://app.example/miniapp#forged"},
    ],
)
def test_render_rejects_unknown_native_uuid_locale_or_base(changes):
    with pytest.raises(ValueError):
        envelope(**changes)


def test_sealed_contract_rejects_forged_templates_and_action_targets():
    from dataclasses import replace

    value = envelope()
    for change in (
        {"locale": "de"},
        {"action_url": " " + value.locales[0].action_url},
    ):
        with pytest.raises(ValueError):
            replace(value.locales[0], **change)
    for change in (
        {"campaign_id": UUID(int=0)},
        {"template_digest": "not a template proof"},
        {
            "locales": (
                replace(
                    value.locales[0],
                    action_url="https://foreign.example/?campaign="
                    + str(value.campaign_id),
                ),
                *value.locales[1:],
            )
        },
        {
            "locales": tuple(
                replace(locale, action_url=locale.action_url + "&owner=forged")
                for locale in value.locales
            )
        },
    ):
        with pytest.raises(ValueError):
            replace(value, **change)


def test_link_bytes_are_included_in_complete_envelope_and_locale_digests():
    from ugc_bot.domain.campaign_review import CampaignDraftContent

    content = CampaignDraftContent.parse(content_payload())
    value = envelope(content=content)
    for locale in value.locales:
        assert locale.text.endswith("\n\n" + content.payload["link"])
    assert value.digest != envelope().digest
    with pytest.raises(ValueError, match="technical_message"):
        envelope(
            content=CampaignDraftContent("T", "x" * (4096 - 15), content.link)
        )


def test_direct_constructors_preserve_canonical_immutable_intent():
    from dataclasses import replace

    from tests.unit.test_campaign_draft_service import save_command
    from ugc_bot.domain.campaign_review import (
        CampaignDraftContent,
        CampaignSegmentV1,
    )

    for construct in (
        lambda: CampaignDraftContent(" T ", "body"),
        lambda: CampaignDraftContent("T", "body", " https://product.example "),
        lambda: CampaignSegmentV1(social={"platform": "instagram"}),
        lambda: replace(save_command(), expected_version=True),
        lambda: replace(save_command(), content={"title": "mutable"}),
    ):
        with pytest.raises(ValueError):
            construct()
    first = CampaignSegmentV1.parse({"city": "Орёл"})
    second = CampaignSegmentV1.parse({"city": " ОРЕЛ "})
    assert first.digest == second.digest

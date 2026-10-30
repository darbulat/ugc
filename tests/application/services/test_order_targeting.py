import pytest


def test_targeting_uses_actual_matching_fields_and_changes_intake_identity():
    from tests.application.services.test_order_intake_service import values
    from ugc_bot.domain.order_intake import OrderIntakeCommand
    from ugc_bot.domain.order_targeting import OrderTargeting

    original = OrderIntakeCommand(**values())
    target = OrderTargeting(
        min_followers=1000,
        max_followers=20000,
        min_age=18,
        max_age=40,
        gender="f",
    )
    changed = OrderIntakeCommand(
        **values() | dict(client_id=original.client_id, targeting=target)
    )
    assert original.payload_hash != changed.payload_hash
    assert target.order_fields()["required_blogger_gender"] == "f"


@pytest.mark.parametrize(
    "changes",
    [
        dict(min_age=True),
        dict(min_age=-1),
        dict(min_age=40, max_age=20),
        dict(min_followers=20, max_followers=10),
        dict(gender="invented"),
        dict(min_followers=-1),
    ],
)
def test_targeting_rejects_ambiguous_or_impossible_filters(changes):
    from ugc_bot.domain.order_targeting import OrderTargeting

    with pytest.raises(ValueError):
        OrderTargeting(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        dict(city="  "),
        dict(geography=" "),
        dict(city="Москва", geography="Россия"),
        dict(platforms=["youtube"]),
        dict(platforms=("youtube", "youtube")),
        dict(platforms=("unknown",)),
        dict(brief_link="javascript:alert(1)"),
        dict(brief_link="https://user:pass@example.com/brief"),
        dict(content_usage=" " * 20),
    ],
)
def test_extended_brief_rejects_unsafe_links_and_platforms(changes):
    from ugc_bot.domain.order_targeting import OrderTargeting

    with pytest.raises(ValueError):
        OrderTargeting(**changes)


def test_platforms_are_canonical_and_independent_of_order_geography():
    from ugc_bot.domain.order_targeting import OrderTargeting

    target = OrderTargeting(
        city=" Москва ",
        platforms=("youtube", "tiktok"),
        content_usage="reels",
        brief_link="https://example.com/brief",
    )
    assert target.city == "Москва" and target.platforms == ("tiktok", "youtube")
    assert target.order_fields()["geography"] == "Москва"
    assert "platforms" not in target.order_fields()

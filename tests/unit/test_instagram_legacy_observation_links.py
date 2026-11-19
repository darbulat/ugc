"""Legacy URL support stays inside observation, not public link validation."""

from types import SimpleNamespace

import pytest

from ugc_bot.domain.social import SocialPlatform, normalize_social_url
from ugc_bot.infrastructure.db.repositories.instagram_maintenance import (
    _observation_handle,
)


@pytest.mark.parametrize(
    "link",
    [
        "https://instagram.com/Alice",
        "http://instagram.com/Alice",
        "HTTP://WWW.INSTAGRAM.COM/Alice/",
        "instagram.com/Alice",
        "www.instagram.com/Alice/",
        "@Alice",
        "Alice",
        "http://instagram.com/Alice?utm_source=legacy",
    ],
)
def test_observation_accepts_historic_links_without_editing_profile(link):
    profile = SimpleNamespace(instagram_url=link, instagram_username=None)
    assert _observation_handle(profile) == "alice"
    assert profile.instagram_url == link


@pytest.mark.parametrize(
    "known,expected",
    [
        ("Api.Name", "api.name"),
        (None, ""),
        ("untrusted/name", ""),
    ],
)
def test_unknown_link_uses_only_valid_previously_observed_username(
    known, expected
):
    profile = SimpleNamespace(
        instagram_url="invalid legacy value", instagram_username=known
    )
    assert _observation_handle(profile) == expected


def test_public_editor_validation_keeps_https_requirement():
    with pytest.raises(ValueError):
        normalize_social_url(
            SocialPlatform.INSTAGRAM, "http://instagram.com/alice"
        )

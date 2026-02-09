"""Tests for content moderation service."""

from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)


def test_contains_banned_content_empty() -> None:
    """Empty or None text returns False."""
    svc = ContentModerationService()
    assert svc.contains_banned_content(None) is False
    assert svc.contains_banned_content("") is False
    assert svc.contains_banned_content("   ") is False


def test_contains_banned_content_clean() -> None:
    """Clean text returns False."""
    svc = ContentModerationService()
    assert svc.contains_banned_content("UGC видео для бренда") is False
    assert svc.contains_banned_content("https://example.com/product") is False


def test_contains_banned_content_casino() -> None:
    """Casino keyword is detected."""
    svc = ContentModerationService()
    assert svc.contains_banned_content("Играй в казино онлайн") is True
    assert svc.contains_banned_content("Play casino games") is True


def test_contains_banned_content_gambling() -> None:
    """Gambling keyword is detected."""
    svc = ContentModerationService()
    assert svc.contains_banned_content("Гэмблинг и ставки") is True
    assert svc.contains_banned_content("gambling site") is True


def test_contains_banned_content_no_false_positive() -> None:
    """Words containing 'bet' as substring are not flagged."""
    svc = ContentModerationService()
    assert svc.contains_banned_content("alphabet") is False
    assert svc.contains_banned_content("beta test") is False


def test_get_banned_matches() -> None:
    """get_banned_matches returns found keywords."""
    svc = ContentModerationService()
    assert svc.get_banned_matches(None) == []
    assert svc.get_banned_matches("Clean text") == []
    matches = svc.get_banned_matches("Играй в казино и рулетку")
    assert "казино" in matches or "рулетк" in matches or len(matches) > 0


def test_order_contains_banned_content() -> None:
    """order_contains_banned_content checks all fields."""
    svc = ContentModerationService()
    assert (
        svc.order_contains_banned_content(
            offer_text="UGC для бренда",
            product_link="https://example.com",
        )
        is False
    )
    assert (
        svc.order_contains_banned_content(
            offer_text="Продвижение казино",
        )
        is True
    )

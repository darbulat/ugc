"""Tests for ReferralService."""

from ugc_bot.application.services.referral_service import ReferralService


def test_parse_referral_code_returns_none_for_empty() -> None:
    """parse_referral_code returns None for empty or None."""
    service = ReferralService(
        manager_repo=object(),
        user_referral_pending_repo=object(),
        creator_manager_binding_repo=object(),
        transaction_manager=None,
    )
    assert service.parse_referral_code(None) is None
    assert service.parse_referral_code("") is None
    assert service.parse_referral_code("   ") is None


def test_parse_referral_code_returns_none_for_plain_start() -> None:
    """parse_referral_code returns None for /start without payload."""
    service = ReferralService(
        manager_repo=object(),
        user_referral_pending_repo=object(),
        creator_manager_binding_repo=object(),
        transaction_manager=None,
    )
    assert service.parse_referral_code("/start") is None


def test_parse_referral_code_extracts_code() -> None:
    """parse_referral_code extracts code from /start ref_XXX."""
    service = ReferralService(
        manager_repo=object(),
        user_referral_pending_repo=object(),
        creator_manager_binding_repo=object(),
        transaction_manager=None,
    )
    assert service.parse_referral_code("/start ref_abc123") == "abc123"
    assert service.parse_referral_code("/start ref_xyz") == "xyz"

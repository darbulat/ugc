"""Tests for draft prompt mapping."""

from ugc_bot.bot.handlers.draft_prompts import (
    EDIT_FIELD_PROMPTS,
    get_draft_prompt,
)


def test_get_draft_prompt_blogger_name() -> None:
    """Return prompt for blogger registration name step."""
    prompt = get_draft_prompt("BloggerRegistrationStates:name", {})
    assert "ваше имя" in prompt.lower()


def test_get_draft_prompt_order_product_link() -> None:
    """Return prompt for order product_link step."""
    prompt = get_draft_prompt("OrderCreationStates:product_link", {})
    assert "ссылку на продукт" in prompt.lower()


def test_get_draft_prompt_order_order_photo() -> None:
    """Return prompt for order order_photo step."""
    prompt = get_draft_prompt("OrderCreationStates:order_photo", {})
    assert "фото" in prompt.lower() and "креатор" in prompt.lower()


def test_get_draft_prompt_order_content_usage() -> None:
    """Return prompt for order content_usage step."""
    prompt = get_draft_prompt("OrderCreationStates:content_usage", {})
    assert "ugc" in prompt.lower() and "использовать" in prompt.lower()


def test_get_draft_prompt_order_deadlines() -> None:
    """Return prompt for order deadlines step."""
    prompt = get_draft_prompt("OrderCreationStates:deadlines", {})
    assert "сроки" in prompt.lower() or "превью" in prompt.lower()


def test_get_draft_prompt_order_geography() -> None:
    """Return prompt for order geography step."""
    prompt = get_draft_prompt("OrderCreationStates:geography", {})
    assert (
        "город" in prompt.lower()
        or "регион" in prompt.lower()
        or "рф" in prompt.lower()
    )


def test_get_draft_prompt_edit_profile_entering_value_uses_field() -> None:
    """EditProfileStates:entering_value uses editing_field for prompt."""
    prompt = get_draft_prompt(
        "EditProfileStates:entering_value",
        {"editing_field": "city"},
    )
    assert "город" in prompt.lower()


def test_get_draft_prompt_unknown_state_returns_fallback() -> None:
    """Unknown state_key returns fallback prompt."""
    prompt = get_draft_prompt("UnknownStates:foo", {})
    assert "Продолжите" in prompt or len(prompt) > 0


def test_edit_field_prompts_has_expected_keys() -> None:
    """EDIT_FIELD_PROMPTS contains expected field keys."""
    expected = {"nickname", "city", "price", "audience_gender", "work_format"}
    assert expected.issubset(EDIT_FIELD_PROMPTS)

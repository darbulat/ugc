"""Smoke tests: every Max handler module imports without errors."""

import importlib

import pytest

_HANDLER_MODULES = [
    "ugc_bot.bot.max.handlers.advertiser_registration",
    "ugc_bot.bot.max.handlers.blogger_registration",
    "ugc_bot.bot.max.handlers.complaints",
    "ugc_bot.bot.max.handlers.feedback",
    "ugc_bot.bot.max.handlers.instagram_verification",
    "ugc_bot.bot.max.handlers.my_orders",
    "ugc_bot.bot.max.handlers.offer_responses",
    "ugc_bot.bot.max.handlers.order_creation",
    "ugc_bot.bot.max.handlers.profile",
    "ugc_bot.bot.max.handlers.referral",
    "ugc_bot.bot.max.handlers.start",
    "ugc_bot.bot.max.handlers.support_chat",
]


@pytest.mark.parametrize("module_path", _HANDLER_MODULES)
def test_handler_module_imports(module_path: str) -> None:
    mod = importlib.import_module(module_path)
    assert hasattr(mod, "router"), f"{module_path} must export a 'router'"

"""E2E UI tests for Telegram Mini App."""

import pytest
from playwright.sync_api import Page

from tests.e2e.conftest import MINIAPP_TEST_USER_IDS
from tests.e2e.miniapp_helpers import (
    build_telegram_mock_script,
    generate_init_data,
    wait_for_screen,
)

# Country buttons: text displayed in the country selector grid
_COUNTRY_FOR_LOCALE = {"ru": "Россия", "en": "Georgia"}


def _open_miniapp(
    page: Page, base_url: str, bot_token: str, user_id: int, username: str
) -> None:
    """Open mini app with mocked Telegram.WebApp."""
    init_data = generate_init_data(bot_token, user_id, username)
    script = build_telegram_mock_script(init_data, user_id, username)
    page.add_init_script(script=script)
    page.goto(f"{base_url}/miniapp/app.html")


def _select_country(page: Page, locale: str) -> None:
    """Select country in the country selector screen."""
    country_name = _COUNTRY_FOR_LOCALE[locale]
    wait_for_screen(page, "screen-country-select")
    page.locator("#country-grid .btn", has_text=country_name).click()


@pytest.mark.e2e
@pytest.mark.timeout(60)
@pytest.mark.parametrize("locale", ["ru", "en"])
class TestMiniAppAdvertiser:
    """Advertiser flow: register → create order → view orders."""

    def test_register_advertiser(
        self, page: Page, miniapp_base_url: str, miniapp_bot_token: str, locale: str
    ) -> None:
        user_id = MINIAPP_TEST_USER_IDS["advertiser"][locale]
        _open_miniapp(page, miniapp_base_url, miniapp_bot_token, user_id, f"e2e_adv_{locale}")

        # Country selection
        _select_country(page, locale)

        # Role choice
        wait_for_screen(page, "screen-role-choice")
        page.locator('[data-role="advertiser"]').click()

        # Registration form
        wait_for_screen(page, "screen-register-advertiser")
        page.locator("#adv-name").fill("E2E Advertiser")
        page.locator("#adv-phone").fill("89001234567")
        page.locator("#adv-brand").fill("E2E Brand")
        page.locator("#btn-submit-advertiser").click()

        # Agreements
        wait_for_screen(page, "screen-agreements-advertiser")
        page.locator("#adv-agree-checkbox").check()
        page.locator("#btn-confirm-adv-agreement").click()

        # Dashboard
        wait_for_screen(page, "screen-advertiser-dashboard")

    def test_create_order(
        self, page: Page, miniapp_base_url: str, miniapp_bot_token: str, locale: str
    ) -> None:
        user_id = MINIAPP_TEST_USER_IDS["advertiser"][locale]
        _open_miniapp(page, miniapp_base_url, miniapp_bot_token, user_id, f"e2e_adv_{locale}")

        # Already registered → should land on dashboard
        wait_for_screen(page, "screen-advertiser-dashboard")

        # Open create order form
        page.locator("#btn-show-create-order").click()
        page.wait_for_selector("#block-create-order", state="visible")

        # Fill order form
        page.locator("#ord-link").fill("https://example.com/product")
        page.locator("#ord-offer").fill("E2E test offer text")
        page.locator("#ord-price").fill("5000")
        page.locator("#btn-submit-order").click()

        # Assert success
        page.wait_for_selector("#ord-success:not(:empty)", timeout=10000)
        success_text = page.locator("#ord-success").inner_text()
        assert success_text  # Non-empty success message

    def test_view_orders(
        self, page: Page, miniapp_base_url: str, miniapp_bot_token: str, locale: str
    ) -> None:
        user_id = MINIAPP_TEST_USER_IDS["advertiser"][locale]
        _open_miniapp(page, miniapp_base_url, miniapp_bot_token, user_id, f"e2e_adv_{locale}")

        wait_for_screen(page, "screen-advertiser-dashboard")

        # Open orders list
        page.locator("#btn-show-orders-list").click()
        page.wait_for_selector("#block-orders-list", state="visible")

        # Should have at least one order from test_create_order
        page.wait_for_selector("#orders-list li", timeout=10000)
        orders = page.locator("#orders-list li")
        assert orders.count() >= 1

        # Click first order to open detail
        orders.first.click()
        wait_for_screen(page, "screen-order-detail")

        # Verify fields are populated
        link_value = page.locator("#ord-detail-link").input_value()
        assert link_value  # Non-empty

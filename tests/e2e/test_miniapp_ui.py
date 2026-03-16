"""E2E UI tests for Telegram Mini App."""

import pytest
from playwright.sync_api import Page

from tests.e2e.miniapp_helpers import (
    MINIAPP_TEST_USER_IDS,
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
    # Block the real Telegram SDK so our mock isn't overwritten
    page.route(
        "**/telegram-web-app.js",
        lambda route: route.fulfill(
            status=200, body="", content_type="text/javascript"
        ),
    )
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
        self,
        page: Page,
        miniapp_base_url: str,
        miniapp_bot_token: str,
        locale: str,
    ) -> None:
        user_id = MINIAPP_TEST_USER_IDS["advertiser"][locale]
        _open_miniapp(
            page,
            miniapp_base_url,
            miniapp_bot_token,
            user_id,
            f"e2e_adv_{locale}",
        )

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
        self,
        page: Page,
        miniapp_base_url: str,
        miniapp_bot_token: str,
        locale: str,
    ) -> None:
        user_id = MINIAPP_TEST_USER_IDS["advertiser"][locale]
        _open_miniapp(
            page,
            miniapp_base_url,
            miniapp_bot_token,
            user_id,
            f"e2e_adv_{locale}",
        )

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
        self,
        page: Page,
        miniapp_base_url: str,
        miniapp_bot_token: str,
        locale: str,
    ) -> None:
        user_id = MINIAPP_TEST_USER_IDS["advertiser"][locale]
        _open_miniapp(
            page,
            miniapp_base_url,
            miniapp_bot_token,
            user_id,
            f"e2e_adv_{locale}",
        )

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


@pytest.mark.e2e
@pytest.mark.timeout(60)
@pytest.mark.parametrize("locale", ["ru", "en"])
class TestMiniAppBlogger:
    """Blogger (creator) registration flow."""

    def test_register_blogger(
        self,
        page: Page,
        miniapp_base_url: str,
        miniapp_bot_token: str,
        locale: str,
    ) -> None:
        user_id = MINIAPP_TEST_USER_IDS["blogger"][locale]
        _open_miniapp(
            page,
            miniapp_base_url,
            miniapp_bot_token,
            user_id,
            f"e2e_blg_{locale}",
        )

        # Country selection
        _select_country(page, locale)

        # Role choice
        wait_for_screen(page, "screen-role-choice")
        page.locator('[data-role="blogger"]').click()

        # Registration form
        wait_for_screen(page, "screen-register-blogger")
        page.locator("#blg-name").fill("E2E Creator")
        page.locator("#blg-instagram").fill(f"e2e_creator_{locale}")
        page.locator("#blg-birth-day").select_option("15")
        page.locator("#blg-birth-month").select_option("6")
        page.locator("#blg-birth-year").select_option("1995")
        page.locator("#blg-topics").fill("beauty, fashion")
        page.locator("#blg-audience-geo").fill("Russia")
        page.locator("#blg-price").fill("10000")

        # City: use search instead of map click
        page.locator("#btn-blogger-city-map").click()
        page.wait_for_selector("#block-blogger-city-map", state="visible")
        page.locator("#blg-city-search").fill(
            "Moscow" if locale == "en" else "Москва"
        )
        page.locator("#btn-blogger-city-search").click()

        # Wait for city field to be populated by geocode API
        page.wait_for_function(
            "document.getElementById('blg-city').value.length > 0",
            timeout=15000,
        )

        # Submit
        page.locator("#btn-submit-blogger").click()

        # Agreements
        wait_for_screen(page, "screen-agreements-blogger")
        page.locator("#blg-agree-checkbox").check()
        page.locator("#btn-confirm-blg-agreement").click()

        # Blogger dashboard
        wait_for_screen(page, "screen-blogger-dashboard")


@pytest.mark.e2e
@pytest.mark.timeout(60)
@pytest.mark.parametrize("locale", ["ru", "en"])
class TestMiniAppNavigation:
    """Navigation and role switching (requires existing advertiser profile)."""

    def test_switch_role(
        self,
        page: Page,
        miniapp_base_url: str,
        miniapp_bot_token: str,
        locale: str,
    ) -> None:
        # Use advertiser user_id (has profile from TestMiniAppAdvertiser)
        user_id = MINIAPP_TEST_USER_IDS["advertiser"][locale]
        _open_miniapp(
            page,
            miniapp_base_url,
            miniapp_bot_token,
            user_id,
            f"e2e_adv_{locale}",
        )

        # Should land on advertiser dashboard (already registered)
        wait_for_screen(page, "screen-advertiser-dashboard")

        # Switch role
        page.locator("#btn-change-role-from-adv").click()
        wait_for_screen(page, "screen-role-choice")

        # Click blogger — should go to registration
        # (no blogger profile for this user)
        page.locator('[data-role="blogger"]').click()
        wait_for_screen(page, "screen-register-blogger")

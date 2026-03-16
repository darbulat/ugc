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
_COUNTRY_FOR_LOCALE = {"ru": "Россия", "en": "საქართველო"}


def _open_miniapp(
    page: Page, base_url: str, bot_token: str, user_id: int, username: str
) -> None:
    """Open mini app with mocked Telegram.WebApp."""
    init_data = generate_init_data(bot_token, user_id, username)
    script = build_telegram_mock_script(init_data, user_id, username)
    page.add_init_script(script=script)
    page.goto(f"{base_url}/miniapp/app.html", wait_until="load")


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
        miniapp_page: Page,
        miniapp_base_url: str,
        miniapp_bot_token: str,
        locale: str,
    ) -> None:
        user_id = MINIAPP_TEST_USER_IDS["advertiser"][locale]
        _open_miniapp(
            miniapp_page,
            miniapp_base_url,
            miniapp_bot_token,
            user_id,
            f"e2e_adv_{locale}",
        )

        # Country selection
        _select_country(miniapp_page, locale)

        # Role choice
        wait_for_screen(miniapp_page, "screen-role-choice")
        miniapp_page.locator('[data-role="advertiser"]').click()

        # Registration form
        wait_for_screen(miniapp_page, "screen-register-advertiser")
        miniapp_page.locator("#adv-name").fill("E2E Advertiser")
        miniapp_page.locator("#adv-phone").fill("89001234567")
        miniapp_page.locator("#adv-brand").fill("E2E Brand")
        miniapp_page.locator("#btn-submit-advertiser").click()

        # Agreements
        wait_for_screen(miniapp_page, "screen-agreements-advertiser")
        miniapp_page.locator("#adv-agree-checkbox").check()
        miniapp_page.locator("#btn-confirm-adv-agreement").click()

        # Dashboard
        wait_for_screen(miniapp_page, "screen-advertiser-dashboard")

    def test_create_order(
        self,
        miniapp_page: Page,
        miniapp_base_url: str,
        miniapp_bot_token: str,
        locale: str,
    ) -> None:
        user_id = MINIAPP_TEST_USER_IDS["advertiser"][locale]
        _open_miniapp(
            miniapp_page,
            miniapp_base_url,
            miniapp_bot_token,
            user_id,
            f"e2e_adv_{locale}",
        )

        # Already registered → should land on dashboard
        wait_for_screen(miniapp_page, "screen-advertiser-dashboard")

        # Open create order form
        miniapp_page.locator("#btn-show-create-order").click()
        miniapp_page.wait_for_selector("#block-create-order", state="visible")

        # Wait for config to populate bloggers select
        miniapp_page.wait_for_selector(
            "#ord-bloggers option", state="attached", timeout=10000
        )

        # Fill order form
        miniapp_page.locator("#ord-link").fill("https://example.com/product")
        miniapp_page.locator("#ord-offer").fill(
            "E2E test offer text for product review"
        )
        miniapp_page.locator("#ord-price").fill("5000")
        miniapp_page.locator("#btn-submit-order").click()

        # Wait for either success or error response
        miniapp_page.wait_for_function(
            """() => {
                const ok = document.getElementById('ord-success');
                const err = document.getElementById('ord-error');
                return (ok && ok.textContent.trim()) ||
                       (err && err.textContent.trim());
            }""",
            timeout=15000,
        )
        err_text = miniapp_page.locator("#ord-error").inner_text()
        assert not err_text, f"Order creation error: {err_text}"
        success_text = miniapp_page.locator("#ord-success").inner_text()
        assert success_text  # Non-empty success message

    def test_view_orders(
        self,
        miniapp_page: Page,
        miniapp_base_url: str,
        miniapp_bot_token: str,
        locale: str,
    ) -> None:
        user_id = MINIAPP_TEST_USER_IDS["advertiser"][locale]
        _open_miniapp(
            miniapp_page,
            miniapp_base_url,
            miniapp_bot_token,
            user_id,
            f"e2e_adv_{locale}",
        )

        wait_for_screen(miniapp_page, "screen-advertiser-dashboard")

        # Open orders list
        miniapp_page.locator("#btn-show-orders-list").click()
        miniapp_page.wait_for_selector("#block-orders-list", state="visible")

        # Should have at least one order from test_create_order
        miniapp_page.wait_for_selector("#orders-list li", timeout=10000)
        orders = miniapp_page.locator("#orders-list li")
        assert orders.count() >= 1

        # Click first order to open detail
        orders.first.click()
        wait_for_screen(miniapp_page, "screen-order-detail")

        # Verify fields are populated
        link_value = miniapp_page.locator("#ord-detail-link").input_value()
        assert link_value  # Non-empty


@pytest.mark.e2e
@pytest.mark.timeout(60)
@pytest.mark.parametrize("locale", ["ru", "en"])
class TestMiniAppBlogger:
    """Blogger (creator) registration flow."""

    def test_register_blogger(
        self,
        miniapp_page: Page,
        miniapp_base_url: str,
        miniapp_bot_token: str,
        locale: str,
    ) -> None:
        user_id = MINIAPP_TEST_USER_IDS["blogger"][locale]
        _open_miniapp(
            miniapp_page,
            miniapp_base_url,
            miniapp_bot_token,
            user_id,
            f"e2e_blg_{locale}",
        )

        # Country selection
        _select_country(miniapp_page, locale)

        # Role choice
        wait_for_screen(miniapp_page, "screen-role-choice")
        miniapp_page.locator('[data-role="blogger"]').click()

        # Registration form
        wait_for_screen(miniapp_page, "screen-register-blogger")
        miniapp_page.locator("#blg-name").fill("E2E Creator")
        miniapp_page.locator("#blg-instagram").fill(f"e2e_creator_{locale}")
        miniapp_page.locator("#blg-birth-day").select_option("15")
        miniapp_page.locator("#blg-birth-month").select_option("6")
        miniapp_page.locator("#blg-birth-year").select_option("1995")
        miniapp_page.locator("#blg-topics").fill("beauty, fashion")
        miniapp_page.locator("#blg-audience-geo").fill("Russia")
        miniapp_page.locator("#blg-price").fill("10000")

        # City: use search instead of map click
        miniapp_page.locator("#btn-blogger-city-map").click()
        miniapp_page.wait_for_selector(
            "#block-blogger-city-map", state="visible"
        )
        miniapp_page.locator("#blg-city-search").fill(
            "Moscow" if locale == "en" else "Москва"
        )
        miniapp_page.locator("#btn-blogger-city-search").click()

        # Wait for city field to be populated by geocode API
        miniapp_page.wait_for_function(
            "document.getElementById('blg-city').value.length > 0",
            timeout=15000,
        )

        # Submit
        miniapp_page.locator("#btn-submit-blogger").click()

        # Agreements
        wait_for_screen(miniapp_page, "screen-agreements-blogger")
        miniapp_page.locator("#blg-agree-checkbox").check()
        miniapp_page.locator("#btn-confirm-blg-agreement").click()

        # Blogger dashboard
        wait_for_screen(miniapp_page, "screen-blogger-dashboard")


@pytest.mark.e2e
@pytest.mark.timeout(60)
@pytest.mark.parametrize("locale", ["ru", "en"])
class TestMiniAppNavigation:
    """Navigation and role switching (requires existing advertiser profile)."""

    def test_switch_role(
        self,
        miniapp_page: Page,
        miniapp_base_url: str,
        miniapp_bot_token: str,
        locale: str,
    ) -> None:
        # Use advertiser user_id (has profile from TestMiniAppAdvertiser)
        user_id = MINIAPP_TEST_USER_IDS["advertiser"][locale]
        _open_miniapp(
            miniapp_page,
            miniapp_base_url,
            miniapp_bot_token,
            user_id,
            f"e2e_adv_{locale}",
        )

        # Should land on advertiser dashboard (already registered)
        wait_for_screen(miniapp_page, "screen-advertiser-dashboard")

        # Switch role
        miniapp_page.locator("#btn-change-role-from-adv").click()
        wait_for_screen(miniapp_page, "screen-role-choice")

        # Click blogger — should go to registration
        # (no blogger profile for this user)
        miniapp_page.locator('[data-role="blogger"]').click()
        wait_for_screen(miniapp_page, "screen-register-blogger")

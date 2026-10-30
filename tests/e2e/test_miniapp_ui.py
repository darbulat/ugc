"""E2E UI tests for Telegram Mini App."""

from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import Page, expect

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

        # The current purchase flow uses the signed financial intake.
        with miniapp_page.expect_response(
            lambda response: (
                response.url.endswith("/financial/orders/policies")
                and response.request.method == "POST"
            )
        ) as pending_policies:
            miniapp_page.locator("#btn-show-create-order").click()
        wait_for_screen(miniapp_page, "screen-intake")
        policies_response = pending_policies.value
        policies = policies_response.json()
        assert policies_response.status == 200, policies
        if locale == "en":
            # Georgia uses GEL; the currently published financial policy is
            # RUB-only and must not offer a misleading invoice.
            assert policies["currency"] == "GEL"
            assert policies["policies"] == []
            expect(miniapp_page.locator("#intake-empty")).to_be_visible()
            expect(miniapp_page.locator("#form-umc-intake")).to_be_hidden()
            return
        assert policies["currency"] == "RUB" and policies["policies"]
        miniapp_page.wait_for_function(
            "document.querySelectorAll('#intake-policy option').length > 1"
        )
        miniapp_page.locator("#intake-policy").select_option(index=1)
        miniapp_page.locator("#intake-count").fill("10")
        miniapp_page.locator("#intake-product").fill(
            "https://example.test/product"
        )
        miniapp_page.locator("#intake-brief").fill(
            "Synthetic E2E offer text for product review"
        )
        miniapp_page.locator("#intake-honorarium").fill("5000")
        miniapp_page.locator("#intake-contact").fill("@synthetic_client")
        due = datetime.now(timezone.utc) + timedelta(days=3)
        miniapp_page.locator("#intake-due").fill(due.strftime("%Y-%m-%dT%H:%M"))
        miniapp_page.locator(
            'input[name="intake-mode"][value="with_manager"]'
        ).check()
        with miniapp_page.expect_response(
            lambda response: (
                response.url.endswith("/financial/orders")
                and response.request.method == "POST"
            )
        ) as pending:
            miniapp_page.locator("#btn-intake-create").click()
        response = pending.value
        body = response.json()
        assert response.status == 200, body
        assert len(body["items"]) == 10
        assert body["total_minor"] > 0
        expect(miniapp_page.locator("#intake-result")).to_be_visible()
        expect(miniapp_page.locator("#umc-checkout-action")).to_be_visible()

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

        # Open the persisted order and check its actual selection snapshot.
        with miniapp_page.expect_response(
            lambda response: (
                response.url.endswith("/orders/list")
                and response.request.method == "POST"
            )
        ) as pending_list:
            miniapp_page.locator("#btn-show-orders-list").click()
        wait_for_screen(miniapp_page, "screen-customer-orders")
        listing = pending_list.value
        listing_body = listing.json()
        assert listing.status == 200, listing_body
        orders = miniapp_page.locator("#orders-list [data-order-id]")
        if locale == "en":
            assert listing_body["orders"] == []
            expect(orders).to_have_count(0)
            return
        expect(orders.first).to_be_visible()
        order_id = orders.first.get_attribute("data-order-id")
        with miniapp_page.expect_response(
            lambda response: (
                response.url.endswith("/selection")
                and response.request.method == "POST"
            )
        ) as pending:
            orders.first.locator("button").first.click()
        response = pending.value
        body = response.json()
        assert response.status == 200, body
        assert body["order_id"] == order_id
        assert len(body["positions"]) == 10
        wait_for_screen(miniapp_page, "screen-selection")


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

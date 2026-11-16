"""Interrupted registration keeps the verified account, profile and intent."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_miniapp_design_system import MiniAppNetwork, open_app
from tests.e2e.test_miniapp_selection_ui import SelectionNetwork
from tests.e2e.test_miniapp_social_ui import SIGNED_DATA, SocialNetwork

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.timeout(30),
    pytest.mark.parametrize("platform", ["telegram", "max"]),
]


@pytest.mark.parametrize(
    ("role", "prefix"), [("advertiser", "adv"), ("blogger", "blg")]
)
def test_resumed_agreement_cannot_confirm_another_account(
    page: Page, platform: str, role: str, prefix: str
) -> None:
    network = MiniAppNetwork(registered=role == "advertiser")
    network.advertiser_agreed = False
    network.blogger_registered = role == "blogger"
    network.blogger_agreement_confirmed = False
    errors = open_app(page, network, platform)
    expect(page.locator(f"#screen-agreements-{role}")).to_be_visible()
    page.locator(f"#{prefix}-agree-checkbox").check()
    page.evaluate("window.__host.wa.initData = 'different-account'")
    button = page.locator(f"#btn-confirm-{prefix}-agreement")
    button.click()
    expect(page.locator(f"#{prefix}-agreement-error")).not_to_be_empty()
    expect(button).to_be_enabled()
    assert not any(
        path.endswith("/confirm-agreement") for path, _ in network.requests
    )
    assert not errors


def test_resumed_agreement_prefills_the_latest_saved_profile(
    page: Page, platform: str
) -> None:
    network = MiniAppNetwork(registered=True)
    network.advertiser_agreed = False
    errors = open_app(page, network, platform)
    page.locator("#back-from-adv-agreements").click()
    page.locator("#adv-brand").fill("Updated brand")
    page.locator("#btn-submit-advertiser").click()
    expect(page.locator("#screen-agreements-advertiser")).to_be_visible()
    page.locator("#back-from-adv-agreements").click()
    page.locator("#back-from-advertiser").click()
    page.locator('[data-role="advertiser"]').click()
    page.locator("#back-from-adv-agreements").click()
    expect(page.locator("#adv-brand")).to_have_value("Updated brand")
    assert not errors


def test_agreement_order_history_cannot_open_for_a_switched_account(
    page: Page, platform: str
) -> None:
    network = MiniAppNetwork(registered=True)
    network.advertiser_agreed = False
    open_app(page, network, platform)
    expect(page.locator("#screen-agreements-advertiser")).to_be_visible()
    page.evaluate("window.__host.wa.initData = 'different-account'")
    page.locator("#btn-agreement-orders").click()
    expect(page.locator("#adv-agreement-error")).not_to_be_empty()
    expect(page.locator("#screen-customer-orders")).to_be_hidden()
    assert not any(
        path == "/orders/list" and body["init_data"] == "different-account"
        for path, body in network.requests
    )


def test_pending_creator_can_read_orders_and_gets_social_prompt_after_consent(
    page: Page, platform: str
) -> None:
    network = SocialNetwork()
    network.blogger_agreement_confirmed = False
    network.creator_orders = [
        {
            "order_id": "existing-creator-order",
            "status": "active",
            "price": 1000,
        }
    ]
    errors = open_app(page, network, platform, init_data=SIGNED_DATA)
    expect(page.locator("#screen-agreements-blogger")).to_be_visible()
    page.locator("#btn-blogger-agreement-orders").click()
    expect(page.locator("#blogger-agreement-orders-list")).to_contain_text(
        "existing-creator-order"
    )
    expect(page.locator("#screen-blogger-dashboard")).to_be_hidden()
    assert not any(path == "/social/accounts" for path, _ in network.requests)
    page.locator("#blg-agree-checkbox").check()
    page.locator("#btn-confirm-blg-agreement").click()
    expect(page.locator("#screen-social-prompt")).to_be_visible()
    assert not errors


def test_order_intent_keeps_manager_option_during_consent(
    page: Page, platform: str
) -> None:
    network = SelectionNetwork()
    network.advertiser_agreed = False
    errors = open_app(page, network, platform, query="?view=order")
    expect(page.locator("#screen-agreements-advertiser")).to_be_visible()
    page.evaluate("window.UMCSelection.create({withManager: true})")
    expect(page.locator("#screen-intake")).to_be_hidden()
    page.locator("#adv-agree-checkbox").check()
    page.locator("#btn-confirm-adv-agreement").click()
    expect(page.locator("#form-umc-intake")).to_be_visible()
    expect(
        page.locator('[name="intake-mode"][value="with_manager"]')
    ).to_be_checked()
    assert not errors

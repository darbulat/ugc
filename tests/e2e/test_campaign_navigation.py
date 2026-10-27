"""Campaign shortcuts follow server capabilities in both Mini App shells."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_campaign_settings import CampaignNetwork
from tests.e2e.test_miniapp_design_system import open_app

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


def network_for(*, publisher=False, creator=False, admin=False):
    network = CampaignNetwork(admin=admin)
    network.registered = True
    network.blogger_registered = creator
    network.manager = publisher or admin
    network.settings["publisher"].update(
        active=publisher, version=int(publisher)
    )
    network.settings["navigation"] = {
        "workbench": publisher or admin,
        "settings": publisher or creator or admin,
        "consent": creator,
        "administration": admin,
    }
    network.settings["delivery_state"] = "enabled"
    return network


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_unrelated_client_and_role_picker_have_no_campaign_shortcuts(
    page, platform
):
    errors = open_app(page, network_for(), platform)
    expect(page.locator("#screen-advertiser-dashboard")).to_be_visible()
    for screen in ("screen-advertiser-dashboard", "screen-role-choice"):
        expect(
            page.locator(f"#{screen} [data-campaign-workbench-open]")
        ).to_be_hidden()
        expect(
            page.locator(f"#{screen} [data-campaign-settings-open]")
        ).to_be_hidden()
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_creator_gets_consent_settings_without_publishing_controls(
    page, platform
):
    errors = open_app(page, network_for(creator=True), platform)
    page.evaluate(
        "window.__umcAppBridge.showScreen('screen-blogger-dashboard')"
    )
    expect(
        page.locator("#screen-blogger-dashboard [data-campaign-workbench-open]")
    ).to_be_hidden()
    page.locator(
        "#screen-blogger-dashboard [data-campaign-settings-open]"
    ).click()
    expect(page.locator("#btn-campaign-consent")).to_be_visible()
    expect(page.locator("#campaign-publisher")).to_be_hidden()
    expect(page.locator("#campaign-admin")).to_be_hidden()
    expect(page.locator("#campaign-delivery-status")).not_to_contain_text(
        "недоступна"
    )
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("role", ["publisher", "admin"])
def test_publisher_and_admin_shortcuts_live_in_network_and_manager_cabinets(
    page, platform, role
):
    errors = open_app(
        page,
        network_for(publisher=role == "publisher", admin=role == "admin"),
        platform,
    )
    page.evaluate("window.__umcAppBridge.showScreen('screen-manager-orders')")
    expect(
        page.locator("#screen-manager-orders [data-campaign-workbench-open]")
    ).to_be_visible()
    expect(
        page.locator("#screen-partner [data-campaign-workbench-open]")
    ).to_have_count(1)
    expect(
        page.locator("#screen-blogger-dashboard [data-campaign-workbench-open]")
    ).to_be_hidden()
    page.locator("#screen-manager-orders [data-campaign-settings-open]").click()
    expect(page.locator("#campaign-publisher")).to_contain_text(
        "Выдано" if role == "publisher" else "Не выдано"
    )
    expect(page.locator("#campaign-consent")).to_be_hidden()
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_identity_change_hides_granted_shortcuts_and_clears_settings(
    page, platform
):
    errors = open_app(page, network_for(publisher=True), platform)
    page.evaluate("window.__umcAppBridge.showScreen('screen-manager-orders')")
    page.locator("#screen-manager-orders [data-campaign-settings-open]").click()
    expect(page.locator("#campaign-content")).to_be_visible()
    page.evaluate(
        "window.__host.wa.initData='different-account';"
        "window.dispatchEvent(new Event('focus'))"
    )
    expect(page.locator("#campaign-content")).to_be_hidden()
    expect(
        page.locator("#screen-partner [data-campaign-workbench-open]")
    ).to_be_hidden()
    expect(
        page.locator("#screen-manager-orders [data-campaign-settings-open]")
    ).to_be_hidden()
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_identity_change_clears_admin_grant_reason(page, platform):
    network = network_for(admin=True)
    errors = open_app(page, network, platform)
    page.evaluate("window.__umcAppBridge.showScreen('screen-manager-orders')")
    page.locator("#screen-manager-orders [data-campaign-settings-open]").click()
    page.locator("#campaign-grant-reason").fill("Previous administrator reason")
    page.evaluate(
        "window.__host.wa.initData='different-admin';"
        "window.dispatchEvent(new Event('focus'))"
    )
    network.settings["actor_id"] = "10000000-0000-4000-8000-000000000099"
    page.evaluate("window.UMCCampaignSettings.open()")
    expect(page.locator("#campaign-admin")).to_be_visible()
    expect(page.locator("#campaign-grant-reason")).to_have_value("")
    assert not errors

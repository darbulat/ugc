"""Actual campaign settings UI, synthetic only at signed API boundary."""

from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import (
    MiniAppNetwork,
    open_app,
    screenshot,
)

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
ACTOR = "10000000-0000-4000-8000-000000000001"
OWNER = "10000000-0000-4000-8000-000000000002"
LIMITS = (
    "recipients_per_campaign",
    "submissions_per_owner",
    "active_per_owner",
    "attempts_per_owner",
    "attempts_global",
    "attempts_per_recipient",
    "window_seconds",
    "recipient_cooldown_seconds",
    "title_max_chars",
    "text_max_chars",
    "link_max_chars",
    "review_ttl_seconds",
    "dispatch_ttl_seconds",
    "claim_batch_size",
    "worker_concurrency",
    "starts_per_second",
    "metrics_max_age_seconds",
)


class CampaignNetwork(MiniAppNetwork):
    def __init__(self, admin=False, locale="ru"):
        super().__init__(
            locale if locale in ("ru", "en", "kk") else "ru", registered=True
        )
        self.admin = admin
        self.ui_locale = locale
        self.failure_code = None
        self.fail_action = None
        self.account = {
            "owner_id": OWNER,
            "label": "Synthetic own-network publisher",
            "status": "active",
            "can_grant": True,
            "can_revoke": False,
            "version": 0,
            "active": False,
        }
        self.settings = {
            "actor_id": ACTOR,
            "consent_context": "c" * 64,
            "as_of": "2026-10-23T12:00:00Z",
            "can_admin": admin,
            "policy": {
                "version": 1,
                "publication_version": 1,
                "terms_version": "synthetic-v1",
                "terms_hash": "a" * 64,
                "default_locale": "ru",
                "terms": {
                    "ru": "Синтетические полные условия. Можно отписаться.",
                    "en": "Full synthetic terms. Unsubscribe at any time.",
                },
                "limits": dict.fromkeys(LIMITS, 7),
                "enabled": True,
                "recorded_at": "2026-10-23T12:00:00Z",
            },
            "publisher": {"version": 0, "active": False},
            "inviter": {"label": "Synthetic inviter"},
            "consent": {
                "version": 0,
                "active": False,
                "effective": False,
                "terms_version": None,
            },
            "can_consent": True,
            "consent_unavailable_reason": None,
            "can_unsubscribe": False,
            "delivery_state": "not_implemented",
        }

    def route(self, route):  # noqa: PLR0912
        path = urlparse(route.request.url).path
        if path.endswith("/me") and self.ui_locale in ("be", "uz"):
            route.fulfill(
                json={
                    "locale": self.ui_locale,
                    "country": "ru",
                    "has_advertiser_profile": True,
                    "has_blogger_profile": False,
                    "is_manager": False,
                }
            )
            return
        if "/campaigns/" not in path:
            super().route(route)
            return
        body = route.request.post_data_json
        self.requests.append((path, body))
        suffix = path.split("/campaigns", 1)[1]
        if self.fail_action and suffix not in ("/settings", "/admin/accounts"):
            failure = self.fail_action
            self.fail_action = None
            if failure == "abort":
                route.abort("failed")
            else:
                route.fulfill(
                    status=failure, json={"detail": "synthetic conflict"}
                )
            return
        if self.failure_code:
            route.fulfill(
                status=self.failure_code,
                json={"detail": "synthetic unavailable"},
            )
            return
        if suffix == "/settings":
            data = self.settings
        elif suffix == "/admin/accounts":
            data = {
                "accounts": [self.account],
                "has_more": False,
                "page": body.get("page", 0),
            }
        else:
            data = {
                "receipt_id": "synthetic-receipt",
                "version": body["expected_version"] + 1,
                "is_current": True,
            }
            if suffix == "/consent/allow":
                if (
                    body.get("consent_context")
                    != self.settings["consent_context"]
                ):
                    route.fulfill(
                        status=409,
                        json={"detail": "campaign_consent_context_changed"},
                    )
                    return
                self.settings["consent"] = {
                    "version": 1,
                    "active": True,
                    "effective": True,
                }
                self.settings["can_consent"] = False
                self.settings["can_unsubscribe"] = True
            elif suffix == "/consent/revoke":
                self.settings["consent"] = {
                    "version": 2,
                    "active": False,
                    "effective": False,
                }
                self.settings["can_unsubscribe"] = False
                self.settings["can_consent"] = True
            elif suffix == "/policy/publish":
                self.settings["policy"] = {
                    **self.settings["policy"],
                    **{
                        k: body[k]
                        for k in (
                            "terms_version",
                            "default_locale",
                            "terms",
                            "limits",
                        )
                    },
                    "version": body["expected_version"] + 1,
                    "publication_version": body["expected_version"] + 1,
                }
            elif suffix in ("/publishers/grant", "/publishers/revoke"):
                self.account["active"] = suffix.endswith("/grant")
                self.account["version"] += 1
                self.account["can_revoke"] = self.account["active"]
            elif suffix == "/policy/suspend":
                self.settings["policy"]["enabled"] = False
                self.settings["policy"]["version"] += 1
                self.settings["can_consent"] = False
        route.fulfill(json=data)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_creator_exact_current_terms_opt_in_and_unsubscribe(page, platform):
    network = CampaignNetwork()
    errors = open_app(page, network, platform)
    page.locator(".screen.active [data-campaign-settings-open]").click()
    expect(page.locator("#screen-campaign-settings")).to_be_visible()
    expect(page.locator("#campaign-terms")).to_contain_text(
        "Синтетические полные условия"
    )
    page.locator("#btn-campaign-consent").click()
    expect(page.locator("#btn-campaign-unsubscribe")).to_be_visible()
    payload = next(
        body
        for path, body in network.requests
        if path.endswith("/consent/allow")
    )
    assert (
        payload["platform"] == platform
        and payload["policy_version"] == 1
        and payload["terms_hash"] == "a" * 64
    )
    assert payload["expected_version"] == 0 and payload["operation_key"]
    assert set(payload) == {
        "init_data",
        "platform",
        "operation_key",
        "expected_version",
        "policy_version",
        "terms_hash",
        "consent_context",
    }
    assert not page.locator("#campaign-admin").is_visible()
    screenshot(page, "campaign-" + platform + "-creator-consent")
    page.locator("#btn-campaign-unsubscribe").click()
    expect(page.locator("#btn-campaign-unsubscribe")).to_be_hidden()
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_actual_publish_grant_revoke_suspend_intents(page, platform):
    network = CampaignNetwork(admin=True)
    errors = open_app(page, network, platform)
    page.locator(".screen.active [data-campaign-settings-open]").click()
    expect(page.locator("#campaign-admin")).to_be_visible()
    page.locator("#campaign-terms-version").fill("synthetic-updated-terms")
    page.locator("#campaign-policy-reason").fill(
        "Actual synthetic admin publication"
    )
    page.locator("#btn-campaign-publish").click()
    expect(page.locator("#campaign-terms")).to_contain_text(
        "synthetic-updated-terms"
    )
    publication = next(
        body
        for path, body in network.requests
        if path.endswith("/policy/publish")
    )
    assert publication["expected_version"] == 1 and publication[
        "limits"
    ] == dict.fromkeys(LIMITS, 7)
    assert (
        publication["terms"]["ru"].startswith("Синтетические")
        and "is_admin" not in publication
    )
    page.locator("#campaign-grant-reason").fill(
        "Approved existing own-network owner"
    )
    page.locator("#campaign-accounts button").click()
    expect(page.locator("#campaign-accounts")).to_contain_text("Выдано")
    page.locator("#campaign-accounts button").click()
    expect(page.locator("#campaign-accounts")).to_contain_text("Не выдано")
    changes = [
        body for path, body in network.requests if "/publishers/" in path
    ]
    assert [body["expected_version"] for body in changes] == [0, 1]
    assert all(
        body["owner_id"] == OWNER
        and body["reason"] == "Approved existing own-network owner"
        for body in changes
    )
    page.locator("#campaign-suspend-reason").fill("Pause new consents")
    page.locator("#btn-campaign-suspend").click()
    expect(page.locator("#campaign-terms")).to_contain_text("приостановлен")
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_unknown_request_survives_reload_and_explicit_same_key_retry(
    page, platform
):
    network = CampaignNetwork()
    errors = open_app(page, network, platform)
    page.locator(".screen.active [data-campaign-settings-open]").click()
    network.fail_action = "abort"
    page.locator("#btn-campaign-consent").click()
    expect(page.locator("[data-campaign-retry]")).to_be_visible()
    original = next(
        body
        for path, body in network.requests
        if path.endswith("/consent/allow")
    )
    page.reload()
    expect(page.locator("[data-campaign-retry]")).to_be_visible()
    assert (
        sum(path.endswith("/consent/allow") for path, _ in network.requests)
        == 1
    )
    page.locator("[data-campaign-retry]").click()
    expect(page.locator("#btn-campaign-unsubscribe")).to_be_visible()
    retries = [
        body
        for path, body in network.requests
        if path.endswith("/consent/allow")
    ]
    assert retries == [original, original]
    assert not errors


@pytest.mark.parametrize("locale", ["ru", "en", "kk", "be", "uz"])
@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_localized_terms_settings_narrow_theme_and_safe_text(
    page, platform, locale
):
    network = CampaignNetwork(admin=True, locale=locale)
    network.settings["inviter"]["label"] = "<img src=x onerror=alert(1)>"
    page.set_viewport_size({"width": 320, "height": 720})
    errors = open_app(page, network, platform, native=True)
    page.locator(".screen.active [data-campaign-settings-open]").click()
    expect(page.locator("#campaign-inviter")).to_contain_text("<img")
    assert not page.locator("#campaign-inviter img").count()
    page.locator("#campaign-policy-reason").focus()
    assert page.evaluate(
        "document.documentElement.scrollWidth<=window.innerWidth"
    )
    screenshot(page, "campaign-" + platform + "-" + locale + "-320-light")
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_conflict_refreshes_without_replaying_and_paused_unsubscribe_works(
    page, platform
):
    network = CampaignNetwork()
    errors = open_app(page, network, platform)
    page.locator(".screen.active [data-campaign-settings-open]").click()
    network.fail_action = 409
    page.locator("#btn-campaign-consent").click()
    expect(page.locator("#campaign-error")).to_contain_text("Данные изменились")
    assert (
        sum(path.endswith("/consent/allow") for path, _ in network.requests)
        == 1
    )
    network.settings["policy"]["enabled"] = False
    network.settings["can_consent"] = False
    network.settings["can_unsubscribe"] = True
    network.settings["consent"] = {
        "version": 1,
        "active": True,
        "effective": False,
    }
    page.locator("#btn-campaign-refresh").click()
    expect(page.locator("#btn-campaign-consent")).to_be_hidden()
    expect(page.locator("#btn-campaign-unsubscribe")).to_be_visible()
    page.locator("#btn-campaign-unsubscribe").click()
    expect(page.locator("#btn-campaign-unsubscribe")).to_be_hidden()
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_native_current_consent_action_and_dark_keyboard_form(page, platform):
    network = CampaignNetwork(admin=True, locale="kk")
    page.set_viewport_size({"width": 320, "height": 800})
    errors = open_app(page, network, platform, native=True)
    page.locator(".screen.active [data-campaign-settings-open]").click()
    expect(page.locator("#campaign-admin")).to_be_visible()
    page.evaluate(
        "window.__host.wa.colorScheme='dark';window.__host.events.themeChanged()"
    )
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    assert page.evaluate("window.__host.wa.MainButton.visible")
    page.evaluate("window.__host.wa.MainButton.click()")
    expect(page.locator("#btn-campaign-unsubscribe")).to_be_visible()
    assert not page.evaluate("window.__host.wa.MainButton.visible")
    page.locator("#campaign-policy-reason").focus()
    page.set_viewport_size({"width": 320, "height": 450})
    expect(page.locator("html")).to_have_attribute("data-keyboard", "open")
    assert page.evaluate(
        "document.documentElement.scrollWidth<=window.innerWidth"
    )
    screenshot(page, "campaign-" + platform + "-kk-320-dark-keyboard")
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("role", ["creator", "manager", "client"])
def test_settings_entry_all_existing_roles_and_no_policy(page, platform, role):
    network = CampaignNetwork()
    network.registered = role == "client"
    network.blogger_registered = role == "creator"
    network.manager = role == "manager"
    network.settings["policy"] = None
    network.settings["can_consent"] = False
    network.settings["consent_unavailable_reason"] = "policy_missing"
    errors = open_app(page, network, platform)
    page.locator(".screen.active [data-campaign-settings-open]").click()
    expect(page.locator("#campaign-terms")).to_contain_text("не опубликованы")
    expect(page.locator("#btn-campaign-consent")).to_be_hidden()
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_pending_consent_keeps_original_inviter_context_after_reload(
    page, platform
):
    network = CampaignNetwork()
    errors = open_app(page, network, platform)
    page.locator(".screen.active [data-campaign-settings-open]").click()
    expect(page.locator("#campaign-inviter")).to_contain_text(
        "Synthetic inviter"
    )
    network.fail_action = "abort"
    page.locator("#btn-campaign-consent").click()
    expect(page.locator("[data-campaign-retry]")).to_be_visible()
    original = next(
        body
        for path, body in network.requests
        if path.endswith("/consent/allow")
    )
    assert original.get("consent_context") == "c" * 64
    network.settings["consent_context"] = "d" * 64
    network.settings["inviter"] = {"label": "Different current inviter"}
    page.reload()
    expect(page.locator("#campaign-inviter")).to_contain_text(
        "Different current inviter"
    )
    page.locator("[data-campaign-retry]").click()
    expect(page.locator("#campaign-error")).to_contain_text("Данные изменились")
    sent = [
        body
        for path, body in network.requests
        if path.endswith("/consent/allow")
    ]
    assert sent == [original, original]
    assert network.settings["consent"]["version"] == 0
    page.locator("#btn-campaign-consent").click()
    expect(page.locator("#btn-campaign-unsubscribe")).to_be_visible()
    latest = [
        body
        for path, body in network.requests
        if path.endswith("/consent/allow")
    ][-1]
    assert latest["consent_context"] == "d" * 64
    assert latest["operation_key"] != original["operation_key"]
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_paused_grant_owner_has_status_and_revoke_without_regrant(
    page, platform
):
    page.set_viewport_size({"width": 320, "height": 740})
    network = CampaignNetwork(admin=True)
    network.account.update(
        status="pause", active=True, version=1, can_grant=False, can_revoke=True
    )
    errors = open_app(page, network, platform)
    page.locator(".screen.active [data-campaign-settings-open]").click()
    expect(page.locator("#campaign-accounts article")).to_be_visible()
    assert "Приостановлен" in page.locator("#campaign-accounts").inner_text()
    page.locator("#campaign-account-search").fill(OWNER)
    page.locator("#btn-campaign-find").click()
    page.locator("#campaign-grant-reason").fill("Revoke while paused")
    assert page.evaluate(
        "document.documentElement.scrollWidth<=window.innerWidth"
    )
    screenshot(page, "campaign-paused-owner-" + platform + "-320")
    page.locator("#campaign-accounts button").click()
    expect(page.locator("#campaign-accounts")).to_contain_text("Не выдано")
    assert page.locator("#campaign-accounts button").count() == 0
    payload = next(
        body
        for path, body in network.requests
        if path.endswith("/publishers/revoke")
    )
    assert payload["owner_id"] == OWNER and payload["expected_version"] == 1
    assert not errors

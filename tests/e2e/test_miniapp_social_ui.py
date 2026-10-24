"""Creator social editor uses the real UI and signed API request envelope."""

from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e.miniapp_helpers import generate_init_data
from tests.e2e.test_miniapp_design_system import (
    MiniAppNetwork,
    open_app,
    screenshot,
)

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
SIGNED_DATA = generate_init_data("test-token", 101, "synthetic_social")
UNKNOWN = {"ru": "Нет данных", "en": "No data", "kk": "Деректер жоқ"}


class SocialNetwork(MiniAppNetwork):
    def __init__(self, locale: str = "ru", *, confirmed: bool = True) -> None:
        super().__init__(locale if locale in UNKNOWN else "ru")
        self.locale = locale
        self.blogger_registered = True
        self.confirmed = confirmed
        self.me_confirmed = confirmed
        self.socials: list[dict] = []
        self.fail_list = False
        self.fail_save = False
        self.fail_remove = False
        self.empty_accounts = False

    def instagram(self) -> dict:
        return {
            "account_id": "00000000-0000-0000-0000-000000000001",
            "user_id": "00000000-0000-0000-0000-000000000101",
            "platform": "instagram",
            "url": "https://www.instagram.com/synthetic_social",
            "handle": "synthetic_social",
            "verified": self.confirmed,
            "work_format": "ugc_only",
            "followers_count": None,
            "metrics_source": None,
            "metrics_fetched_at": None,
        }

    def next_platform(self, body: dict) -> str | None:
        if not self.confirmed:
            return "instagram"
        present = {account["platform"] for account in self.socials}
        present.update(body.get("skipped", []))
        order = ["tiktok", "youtube", "telegram"]
        if body.get("include_vk"):
            order.append("vk")
        return next(
            (network for network in order if network not in present), None
        )

    def route(self, route: Route) -> None:
        path = urlparse(route.request.url).path
        if not path.startswith("/miniapp/api/"):
            super().route(route)
            return
        path = path.removeprefix("/miniapp/api")
        body = route.request.post_data_json
        if path not in {
            "/me",
            "/social/accounts",
            "/social/accounts/save",
            "/social/accounts/remove",
            "/blogger/instagram-verification/start",
        }:
            super().route(route)
            return
        self.requests.append((path, body))
        if path == "/me":
            route.fulfill(
                json={
                    "locale": self.locale,
                    "country": "ru",
                    "currency_symbol": self.symbol,
                    "has_advertiser_profile": False,
                    "has_blogger_profile": True,
                    "blogger_profile": {
                        "confirmed": self.me_confirmed,
                        "work_format": "ugc_only",
                    },
                    "is_manager": False,
                }
            )
        elif path == "/blogger/instagram-verification/start":
            route.fulfill(
                json={
                    "code": "synthetic-verification",
                    "instagram_url": self.instagram()["url"],
                }
            )
        elif path == "/social/accounts":
            if self.fail_list:
                route.fulfill(
                    status=503, json={"detail": "Synthetic list unavailable"}
                )
            else:
                route.fulfill(
                    json={
                        "accounts": []
                        if self.empty_accounts
                        else [self.instagram(), *self.socials],
                        "next_platform": self.next_platform(body),
                    }
                )
        elif path == "/social/accounts/save":
            if self.fail_save or not self.confirmed:
                route.fulfill(
                    status=400, json={"detail": "Synthetic save rejected"}
                )
                return
            network = body["network"]
            existing = next(
                (item for item in self.socials if item["platform"] == network),
                None,
            )
            account = {
                "account_id": existing["account_id"]
                if existing
                else f"00000000-0000-0000-0000-{len(self.socials) + 2:012d}",
                "user_id": self.instagram()["user_id"],
                "platform": network,
                "url": body["url"],
                "handle": body["url"].rsplit("/", 1)[-1],
                "verified": False,
                "work_format": body["work_format"],
                "followers_count": None,
                "metrics_source": None,
                "metrics_fetched_at": None,
            }
            self.socials = [
                item for item in self.socials if item["platform"] != network
            ] + [account]
            route.fulfill(
                json={
                    "account": account,
                    "next_platform": self.next_platform({}),
                }
            )
        elif self.fail_remove:
            route.fulfill(
                status=503, json={"detail": "Synthetic remove unavailable"}
            )
        else:
            self.socials = [
                item
                for item in self.socials
                if item["account_id"] != body["account_id"]
            ]
            route.fulfill(json={"removed": True})


def open_socials(
    page: Page,
    network: SocialNetwork,
    platform: str = "telegram",
    *,
    native: bool = False,
) -> list[str]:
    return open_app(
        page, network, platform, native=native, init_data=SIGNED_DATA
    )


def save_link(page: Page, network: str, url: str) -> None:
    expect(page.locator("#form-social-account")).to_have_attribute(
        "data-network", network
    )
    expect(page.locator("#form-social-account")).to_be_visible()
    page.locator("#social-account-url").fill(url)
    page.locator("#btn-social-save").click()
    expect(page.locator(f'[data-social-network="{network}"]')).to_be_visible()


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("locale", ["ru", "en", "kk"])
def test_sequential_socials_skip_edit_reload_remove(
    page: Page, platform: str, locale: str
) -> None:
    page.set_viewport_size(
        {"width": 320 if locale == "kk" else 390, "height": 844}
    )
    network = SocialNetwork(locale)
    errors = open_socials(page, network, platform)
    expect(page.locator("#screen-social-accounts")).to_be_visible()
    screenshot(page, f"social-{platform}-{locale}-tiktok-prompt")
    save_link(page, "tiktok", "https://www.tiktok.com/@synthetic_social")
    expect(page.locator("#form-social-account")).to_have_attribute(
        "data-network", "youtube"
    )
    page.locator("#btn-social-skip").click()
    expect(page.locator("#form-social-account")).to_have_attribute(
        "data-network", "telegram"
    )
    save_link(page, "telegram", "https://t.me/synthetic_social")
    expect(page.locator("#form-social-account")).to_be_hidden()
    expect(page.locator(".umc-social-account")).to_have_count(3)
    expect(page.locator(".is-verified")).to_have_count(1)
    expect(page.locator('[data-social-network="tiktok"]')).to_contain_text(
        UNKNOWN[locale]
    )
    assert not any(item["platform"] == "vk" for item in network.socials)
    page.locator('[data-social-add="vk"]').click()
    expect(page.locator("#form-social-account")).to_have_attribute(
        "data-network", "vk"
    )
    page.locator("#btn-social-skip").click()
    expect(page.locator("#form-social-account")).to_be_hidden()
    assert any(
        body.get("skipped") == ["youtube", "vk"]
        and body.get("include_vk") is True
        for path, body in network.requests
        if path == "/social/accounts"
    )
    screenshot(page, f"social-{platform}-{locale}-saved-links")
    page.reload()
    expect(page.locator("#screen-social-accounts")).to_be_visible()
    expect(page.locator(".umc-social-account")).to_have_count(3)
    page.locator('[data-social-edit="tiktok"]').click()
    page.locator("#social-account-url").fill(
        "https://www.tiktok.com/@synthetic_updated"
    )
    page.locator("#social-account-work-format").select_option("ads_in_account")
    page.locator("#btn-social-save").click()
    expect(page.locator('[data-social-network="tiktok"] a')).to_have_attribute(
        "href", "https://www.tiktok.com/@synthetic_updated"
    )
    page.locator('[data-social-remove="telegram"]').click()
    expect(page.locator('[data-social-network="telegram"]')).to_have_count(0)
    page.locator("#btn-social-back").click()
    page.locator("#btn-blogger-update-profile").click()
    page.locator("#btn-edit-profile-socials").click()
    expect(page.locator("#screen-social-accounts")).to_be_visible()
    assert not any(path == "/register/blogger" for path, _ in network.requests)
    for path, body in network.requests:
        if not path.startswith("/social/"):
            continue
        assert body["init_data"] == SIGNED_DATA and body["platform"] == platform
        if path.endswith("/save"):
            assert set(body) == {
                "init_data",
                "platform",
                "network",
                "url",
                "work_format",
            }
        elif path.endswith("/remove"):
            assert set(body) == {"init_data", "platform", "account_id"}
        else:
            assert set(body) == {
                "init_data",
                "platform",
                "skipped",
                "include_vk",
            }
    assert page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth"
    )
    assert not errors


def test_unverified_instagram_gate_uses_existing_verification(
    page: Page,
) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    network = SocialNetwork(confirmed=False)
    errors = open_socials(page, network)
    expect(page.locator("#screen-blogger-dashboard")).to_be_visible()
    page.locator("#btn-blogger-social-accounts").click()
    expect(page.locator("#social-accounts-gate")).to_be_visible()
    expect(page.locator("#form-social-account")).to_be_hidden()
    expect(page.locator("#social-accounts-add-options button")).to_have_count(0)
    expect(page.locator(".is-verified")).to_have_count(0)
    screenshot(page, "social-unverified-instagram-gate")
    page.locator("#btn-social-verify-instagram").click()
    expect(page.locator("#screen-instagram-verification")).to_be_visible()
    assert any(
        path == "/blogger/instagram-verification/start"
        for path, _ in network.requests
    )
    assert not any(path.endswith("/save") for path, _ in network.requests)
    # Only canonical verification from the server unlocks the next prompts.
    network.confirmed = True
    network.me_confirmed = True
    page.locator("#btn-instagram-verification-back").click()
    expect(page.locator("#screen-social-accounts")).to_be_visible()
    expect(page.locator("#form-social-account")).to_have_attribute(
        "data-network", "tiktok"
    )
    assert not errors


def test_social_loading_save_remove_failures_are_retryable(page: Page) -> None:
    network = SocialNetwork()
    network.fail_list = True
    errors = open_socials(page, network)
    expect(page.locator("#screen-blogger-dashboard")).to_be_visible()
    expect(page.locator("#screen-social-accounts")).to_have_attribute(
        "aria-busy", "false"
    )
    page.locator("#btn-blogger-social-accounts").click()
    expect(page.locator("#social-accounts-error")).to_contain_text(
        "Не удалось загрузить соцсети."
    )
    expect(page.locator("#form-social-account")).to_be_hidden()
    network.fail_list = False
    page.locator("#btn-social-reload").click()
    expect(page.locator("#form-social-account")).to_be_visible()
    network.fail_save = True
    page.locator("#social-account-url").fill(
        "https://www.tiktok.com/@synthetic_retry"
    )
    page.locator("#btn-social-save").click()
    expect(page.locator("#social-accounts-error")).to_contain_text(
        "Не удалось сохранить ссылку."
    )
    expect(page.locator("#social-account-url")).to_have_value(
        "https://www.tiktok.com/@synthetic_retry"
    )
    expect(page.locator("#btn-social-save")).to_be_enabled()
    screenshot(page, "social-save-error-retry")
    network.fail_save = False
    page.locator("#btn-social-save").click()
    expect(page.locator('[data-social-network="tiktok"]')).to_be_visible()
    network.fail_remove = True
    page.locator('[data-social-remove="tiktok"]').click()
    expect(page.locator("#social-accounts-error")).to_contain_text(
        "Не удалось удалить ссылку."
    )
    expect(page.locator('[data-social-network="tiktok"]')).to_be_visible()
    network.fail_remove = False
    page.locator('[data-social-remove="tiktok"]').click()
    expect(page.locator('[data-social-network="tiktok"]')).to_have_count(0)
    network.fail_list = True
    page.locator("#btn-social-reload").click()
    expect(page.locator("#social-accounts-error")).to_contain_text(
        "Не удалось загрузить соцсети."
    )
    expect(page.locator("#form-social-account")).to_be_hidden()
    expect(page.locator("#social-accounts-add-options")).to_be_hidden()
    assert not errors


@pytest.mark.parametrize("locale", ["be", "uz"])
def test_new_social_ui_localizes_existing_additional_locales(
    page: Page, locale: str
) -> None:
    errors = open_socials(page, SocialNetwork(locale))
    expect(page.locator("#screen-social-accounts")).to_be_visible()
    title = "Сацыяльныя сеткі" if locale == "be" else "Ijtimoiy tarmoqlar"
    expect(page.locator("#social-accounts-title")).to_have_text(title)
    expect(page.locator("#social-accounts-intro")).not_to_be_empty()
    assert not errors


def test_server_badges_unknown_metrics_and_link_rendering_are_authoritative(
    page: Page,
) -> None:
    network = SocialNetwork()
    network.socials = [
        {
            "account_id": "00000000-0000-0000-0000-000000000002",
            "platform": "tiktok",
            "verified": False,
            "url": "javascript:window.socialInjected=true",
            "handle": "<img src=x onerror=window.socialInjected=true>",
            "work_format": "ugc_only",
            "followers_count": 999999,
            "metrics_source": None,
            "metrics_fetched_at": None,
        },
        {
            "account_id": "00000000-0000-0000-0000-000000000003",
            "platform": "youtube",
            "verified": False,
            "url": "https://www.youtube.com/@synthetic_social",
            "work_format": "ads_in_account",
            "followers_count": 0,
            "metrics_source": "Synthetic public observation <img src=x>",
            "metrics_fetched_at": "2026-10-23T10:00:00Z",
        },
    ]
    errors = open_socials(page, network)
    expect(page.locator("#screen-social-accounts")).to_be_visible()
    tiktok = page.locator('[data-social-network="tiktok"]')
    expect(tiktok.locator("a")).to_have_count(0)
    expect(tiktok).to_contain_text("Нет данных")
    expect(tiktok).not_to_contain_text("999999")
    youtube = page.locator('[data-social-network="youtube"]')
    expect(youtube).to_contain_text("Подписчики: 0")
    expect(youtube).to_contain_text("Synthetic public observation <img src=x>")
    expect(page.locator("#social-accounts-list img")).to_have_count(0)
    expect(page.locator(".is-verified")).to_have_count(1)
    assert page.evaluate("window.socialInjected === undefined")
    assert not errors


def test_native_social_save_pending_state_and_exact_signed_payload(
    page: Page,
) -> None:
    network = SocialNetwork()
    errors = open_socials(page, network, native=True)
    expect(page.locator("#screen-social-accounts")).to_be_visible()
    expect(page.locator("#btn-social-save")).to_be_hidden()
    page.locator("#social-account-url").fill(
        "https://www.tiktok.com/@synthetic_pending"
    )
    pending: list[Route] = []
    page.route(
        "**/miniapp/api/social/accounts/save",
        lambda route: pending.append(route),
    )
    page.evaluate("window.__host.wa.MainButton.click()")
    expect(page.locator("#screen-social-accounts")).to_have_attribute(
        "aria-busy", "true"
    )
    assert len(pending) == 1
    body = pending[0].request.post_data_json
    assert body == {
        "init_data": SIGNED_DATA,
        "platform": "telegram",
        "network": "tiktok",
        "url": "https://www.tiktok.com/@synthetic_pending",
        "work_format": "ugc_only",
    }
    assert (
        page.evaluate("window.__host.wa.MainButton.params.is_active") is False
    )
    pending.pop().fulfill(
        status=400, json={"detail": "Synthetic pending rejected"}
    )
    expect(page.locator("#social-accounts-error")).to_contain_text(
        "Не удалось сохранить ссылку."
    )
    expect(page.locator("#screen-social-accounts")).to_have_attribute(
        "aria-busy", "false"
    )
    expect(page.locator("#social-account-url")).to_have_value(
        "https://www.tiktok.com/@synthetic_pending"
    )
    assert not errors


def test_empty_social_response_keeps_instagram_gate_and_can_reload(
    page: Page,
) -> None:
    network = SocialNetwork(confirmed=False)
    network.empty_accounts = True
    errors = open_socials(page, network)
    expect(page.locator("#screen-blogger-dashboard")).to_be_visible()
    page.locator("#btn-blogger-social-accounts").click()
    expect(page.locator("#social-accounts-empty")).to_be_visible()
    expect(page.locator("#social-accounts-gate")).to_be_visible()
    expect(page.locator("#form-social-account")).to_be_hidden()
    expect(page.locator("#social-accounts-list li")).to_have_count(0)
    network.empty_accounts = False
    page.locator("#btn-social-reload").click()
    expect(page.locator('[data-social-network="instagram"]')).to_be_visible()
    assert not errors


def test_server_instagram_gate_overrides_stale_profile_confirmation(
    page: Page,
) -> None:
    network = SocialNetwork(confirmed=False)
    network.me_confirmed = True
    errors = open_socials(page, network)
    expect(page.locator("#screen-blogger-dashboard")).to_be_visible()
    expect(page.locator("#screen-social-accounts")).to_have_attribute(
        "aria-busy", "false"
    )
    page.locator("#btn-blogger-social-accounts").click()
    expect(page.locator("#social-accounts-gate")).to_be_visible()
    expect(page.locator("#form-social-account")).to_be_hidden()
    expect(page.locator("#social-accounts-add-options button")).to_have_count(0)
    assert not any(path.endswith("/save") for path, _ in network.requests)
    assert not errors

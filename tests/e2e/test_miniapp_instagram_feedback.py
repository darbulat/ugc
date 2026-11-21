"""Server-confirmed feedback in real templates; all traffic is synthetic."""

from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import screenshot
from tests.e2e.test_miniapp_social_ui import SocialNetwork, open_socials

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.timeout(30),
    pytest.mark.parametrize("platform", ["telegram", "max"]),
]
STATUS = "/blogger/instagram-verification/status"
START = "/blogger/instagram-verification/start"


class FeedbackNetwork(SocialNetwork):
    def __init__(self):
        super().__init__(confirmed=False)
        self.dismissed = True
        self.blogger_agreement_confirmed = True
        self.code = "TEST1234"
        self.expires = datetime.now(UTC) + timedelta(minutes=15)
        self.status_code = 200
        self.held = None
        self.hold_next = False
        self.wrong_owner = False
        self.already_confirmed = False

    def response(self):
        return {
            "user_id": "wrong-owner"
            if self.wrong_owner
            else self.instagram()["user_id"],
            "instagram_url": self.instagram()["url"],
            "confirmed": self.confirmed,
            "agreement_confirmed": self.blogger_agreement_confirmed,
        }

    def route(self, route):
        path = urlparse(route.request.url).path.removeprefix("/miniapp/api")
        if path not in (START, STATUS):
            super().route(route)
            return
        self.requests.append((path, route.request.post_data_json))
        if path == START:
            route.fulfill(
                json={"already_confirmed": True}
                if self.already_confirmed
                else {
                    "code": self.code,
                    "expires_at": self.expires.isoformat(),
                    "instagram_url": "https://ig.me/m/synthetic_umc",
                }
            )
        elif self.hold_next:
            self.hold_next = False
            self.held = route
        else:
            route.fulfill(
                status=self.status_code,
                json=self.response()
                if self.status_code == 200
                else {"detail": "social_account_unavailable"},
            )

    def count(self, path):
        return sum(p == path for p, _ in self.requests)


def start(page, network, platform, *, native=False):
    page.set_viewport_size({"width": 390, "height": 844})
    errors = open_socials(page, network, platform, native=native)
    expect(page.locator("#screen-blogger-dashboard")).to_be_visible()
    if native:
        page.wait_for_function(
            "window.__host.wa.MainButton.params.text === "
            "'Подтвердить Instagram'"
        )
        page.evaluate("window.__host.wa.MainButton.click()")
    else:
        page.locator("#btn-blogger-confirm-instagram").click()
    expect(page.locator("#screen-instagram-verification")).to_be_visible()
    return errors


def confirmed(page):
    expect(page.locator("#instagram-verification-success-title")).to_have_text(
        "✅ Instagram подтверждён"
    )
    expect(page.locator("#instagram-verification-result")).to_be_visible()
    expect(page.locator("#instagram-verification-code")).to_be_hidden()
    expect(page.locator("#instagram-verification-code")).to_have_value("")
    expect(page.locator("#btn-instagram-open")).to_be_hidden()


def test_return_from_instagram_opens_social_editor_with_one_native_action(
    page, platform
):
    network = FeedbackNetwork()
    errors = start(page, network, platform, native=True)
    expect(page.locator("#instagram-verification-status")).to_have_text(
        "Ожидаем подтверждения в Instagram…"
    )
    me_reads = network.count("/me")
    network.confirmed = True
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    confirmed(page)
    expect(page.locator("#instagram-verification-account")).to_have_text(
        "@synthetic_social"
    )
    expect(page.locator("#instagram-verification-detail")).to_contain_text(
        "Профиль креатора готов"
    )
    screenshot(page, f"instagram-confirmed-{platform}")
    page.wait_for_function(
        "window.__host.wa.MainButton.params.text === 'Добавить соцсети'"
    )
    page.evaluate("window.__host.wa.MainButton.click()")
    editor = page.locator("#screen-social-accounts")
    expect(editor).to_be_visible()
    expect(
        editor.get_by_role("button", name="Добавить Telegram")
    ).to_be_visible()
    assert network.count("/social/accounts") == 1
    assert network.count("/social/prompt/dismiss") == 0
    page.evaluate("window.__host.wa.BackButton.click()")
    expect(page.locator("#screen-blogger-dashboard")).to_be_visible()
    expect(page.locator("#btn-blogger-confirm-instagram")).to_be_hidden()
    assert network.count(START) == 1
    assert network.count("/me") == me_reads
    assert all(
        set(body) == {"init_data", "platform"} and body["platform"] == platform
        for path, body in network.requests
        if path == STATUS
    )
    assert not any("/send" in path for path, _ in network.requests)
    assert not errors


def test_creator_can_go_to_cabinet_and_add_socials_later(page, platform):
    network = FeedbackNetwork()
    network.dismissed = False
    errors = start(page, network, platform)
    expect(page.locator("#btn-instagram-verification-check")).to_be_enabled()
    network.confirmed = True
    page.locator("#btn-instagram-verification-check").click()
    confirmed(page)
    page.locator("#btn-instagram-verification-done").click()
    expect(page.locator("#screen-blogger-dashboard")).to_be_visible()
    expect(page.locator("#screen-social-prompt")).to_be_hidden()
    page.locator("#btn-blogger-social-accounts").click()
    expect(page.locator("#screen-social-accounts")).to_be_visible()
    assert network.count("/social/prompt/dismiss") == 0
    assert not errors


def test_delayed_confirmation_polls_and_stops_after_success(page, platform):
    page.clock.install()
    network = FeedbackNetwork()
    errors = start(page, network, platform)
    expect(page.locator("#btn-instagram-verification-check")).to_be_enabled()
    network.confirmed = True
    page.clock.fast_forward(5000)
    confirmed(page)
    reads = network.count(STATUS)
    page.clock.fast_forward(30000)
    assert network.count(STATUS) == reads
    assert network.count(START) == 1
    assert not errors


def test_background_pauses_and_foreground_refreshes(page, platform):
    page.clock.install()
    network = FeedbackNetwork()
    errors = start(page, network, platform)
    expect(page.locator("#btn-instagram-verification-check")).to_be_enabled()
    page.evaluate("""() => {
      Object.defineProperty(document, 'hidden', {get: () => window.testHidden});
      window.testHidden = true;
      document.dispatchEvent(new Event('visibilitychange'));
    }""")
    reads = network.count(STATUS)
    network.confirmed = True
    page.clock.fast_forward(30000)
    assert network.count(STATUS) == reads
    page.evaluate("""() => {
      window.testHidden = false;
      document.dispatchEvent(new Event('visibilitychange'));
    }""")
    confirmed(page)
    assert not errors


@pytest.mark.parametrize("failure", [503, 403, "owner"])
def test_failure_never_claims_success_and_retry_recovers(
    page, platform, failure
):
    network = FeedbackNetwork()
    if failure == "owner":
        network.wrong_owner = True
    else:
        network.status_code = failure
    errors = start(page, network, platform)
    status = page.locator("#instagram-verification-status")
    expect(status).to_contain_text(
        "Не удалось обновить статус" if failure == 503 else "Откройте Mini App"
    )
    expect(page.locator("#instagram-verification-result")).to_be_hidden()
    if failure == 503:
        network.status_code = 200
        network.confirmed = True
        page.locator("#btn-instagram-verification-check").click()
        confirmed(page)
    else:
        expect(page.locator("#instagram-verification-code")).to_have_value("")
    assert not errors


def test_expired_code_stops_polling_but_late_confirmation_can_be_checked(
    page, platform
):
    page.clock.install()
    network = FeedbackNetwork()
    network.expires = datetime.now(UTC) + timedelta(seconds=2)
    errors = start(page, network, platform)
    expect(page.locator("#btn-instagram-verification-check")).to_be_enabled()
    page.clock.fast_forward(5000)
    expect(page.locator("#instagram-verification-status")).to_contain_text(
        "Срок действия кода истёк"
    )
    expect(page.locator("#instagram-verification-code")).to_have_value("")
    reads = network.count(STATUS)
    page.clock.fast_forward(30000)
    assert network.count(STATUS) == reads
    network.confirmed = True
    page.locator("#btn-instagram-verification-check").click()
    confirmed(page)
    assert network.count(START) == 1
    assert not errors


@pytest.mark.parametrize("change", ["leave", "auth", "platform", "owner"])
def test_late_response_cannot_update_another_screen_or_account(
    page, platform, change
):
    page.add_init_script("window.AbortController = undefined")
    network = FeedbackNetwork()
    errors = start(page, network, platform)
    expect(page.locator("#btn-instagram-verification-check")).to_be_enabled()
    network.hold_next = True
    page.locator("#btn-instagram-verification-check").click()
    page.wait_for_function(
        "document.querySelector('#btn-instagram-verification-check').disabled"
    )
    assert network.held is not None
    if change == "leave":
        page.evaluate(
            "window.__umcAppBridge.showScreen('screen-blogger-dashboard')"
        )
    elif change == "auth":
        page.evaluate("window.__host.wa.initData = 'another-session'")
    elif change == "platform":
        page.evaluate("window.__miniapp_platform = 'another-platform'")
    else:
        page.evaluate("window._me.user_id = 'another-owner'")
    network.confirmed = True
    with page.expect_response(
        lambda response: response.url.endswith(STATUS)
    ) as reply:
        network.held.fulfill(json=network.response())
    reply.value.finished()
    # Drain the fetch continuation before making a negative assertion.
    page.evaluate(
        "() => new Promise(resolve => requestAnimationFrame(() => "
        "requestAnimationFrame(resolve)))"
    )
    expect(page.locator("#instagram-verification-result")).to_be_hidden()
    expect(page.locator("#instagram-verification-code")).to_have_value("")
    assert not errors


def test_existing_confirmation_still_requires_server_status(page, platform):
    network = FeedbackNetwork()
    network.already_confirmed = True
    network.confirmed = True
    errors = start(page, network, platform)
    confirmed(page)
    assert network.count(STATUS) == 1
    assert not errors


def test_verification_does_not_bypass_registration_terms(page, platform):
    network = FeedbackNetwork()
    errors = start(page, network, platform)
    expect(page.locator("#btn-instagram-verification-check")).to_be_enabled()
    network.confirmed = True
    network.blogger_agreement_confirmed = False
    page.locator("#btn-instagram-verification-check").click()
    confirmed(page)
    expect(page.locator("#instagram-verification-detail")).to_contain_text(
        "Для завершения регистрации подтвердите условия"
    )
    expect(page.locator("#btn-instagram-add-socials")).to_be_hidden()
    page.locator("#btn-instagram-verification-done").click()
    expect(page.locator("#screen-agreements-blogger")).to_be_visible()
    assert network.count("/social/accounts") == 0
    assert not errors


def test_stalled_request_times_out_and_manual_retry_recovers(page, platform):
    page.clock.install()
    network = FeedbackNetwork()
    network.hold_next = True
    errors = start(page, network, platform)
    expect(page.locator("#btn-instagram-verification-check")).to_be_disabled()
    page.clock.fast_forward(15000)
    expect(page.locator("#instagram-verification-status")).to_contain_text(
        "Не удалось обновить статус"
    )
    expect(page.locator("#btn-instagram-verification-check")).to_be_enabled()
    network.confirmed = True
    page.locator("#btn-instagram-verification-check").click()
    confirmed(page)
    assert not errors


def test_page_restoration_keeps_verification_context(page, platform):
    page.clock.install()
    network = FeedbackNetwork()
    errors = start(page, network, platform)
    expect(page.locator("#btn-instagram-verification-check")).to_be_enabled()
    page.evaluate("window.dispatchEvent(new Event('pagehide'))")
    reads = network.count(STATUS)
    page.clock.fast_forward(30000)
    assert network.count(STATUS) == reads
    network.confirmed = True
    page.evaluate("window.dispatchEvent(new Event('pageshow'))")
    confirmed(page)
    assert network.count(START) == 1
    assert not errors


def test_account_change_clears_previous_success(page, platform):
    network = FeedbackNetwork()
    network.already_confirmed = True
    network.confirmed = True
    errors = start(page, network, platform)
    confirmed(page)
    page.evaluate("window.__host.wa.initData = 'another-session'")
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(page.locator("#instagram-verification-result")).to_be_hidden()
    expect(page.locator("#instagram-verification-status")).to_be_visible()
    expect(page.locator("#instagram-verification-status")).to_contain_text(
        "Откройте Mini App заново"
    )
    assert not errors

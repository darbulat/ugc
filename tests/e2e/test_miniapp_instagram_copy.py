"""Copy verification codes through the real Mini App and browser clipboard."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import (
    MiniAppNetwork,
    open_app,
    screenshot,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.timeout(30),
    pytest.mark.parametrize("platform", ["telegram", "max"]),
]


class VerificationNetwork(MiniAppNetwork):
    def __init__(self):
        super().__init__()
        self.blogger_registered = True
        self.blogger_agreement_confirmed = True
        self.code = "UMC-test-012345"

    def route(self, route):
        if route.request.url.endswith("/blogger/instagram-verification/start"):
            route.fulfill(
                json={
                    "code": self.code,
                    "instagram_url": "https://instagram.com/synthetic_umc",
                }
            )
            return
        super().route(route)


@pytest.mark.parametrize(
    "clipboard", ["native", "missing", "denied", "blocked"]
)
def test_verification_code_copies_and_recovers_in_messenger_webview(
    page, platform, clipboard
):
    network = VerificationNetwork()
    page.set_viewport_size({"width": 390, "height": 844})
    errors = open_app(page, network, platform, native=True)
    # The Clipboard API requires HTTPS. All responses still use local fixtures.
    page.goto(page.url.replace("http://", "https://", 1))
    page.context.grant_permissions(
        ["clipboard-read", "clipboard-write"], origin="https://miniapp.test"
    )
    page.evaluate("window.__host.wa.MainButton.click()")
    code = page.get_by_role("textbox", name="Ваш код")
    copy = page.get_by_role("button", name="Скопировать код", exact=True)
    status = page.locator("#instagram-copy-status")
    expect(code).to_have_value(network.code)
    expect(code).to_have_attribute("readonly", "")
    expect(copy).to_be_enabled()
    page.evaluate("""() => {
      window.clipboardForTest = navigator.clipboard;
      window.execCommandForTest = document.execCommand;
    }""")
    if clipboard == "missing":
        page.evaluate("""() => {
          Object.defineProperty(navigator, 'clipboard', {
            value: undefined, configurable: true
          });
        }""")
    if clipboard in ("denied", "blocked"):
        page.evaluate("""() => {
          Object.defineProperty(navigator, 'clipboard', {
            value: {writeText: () => Promise.reject(new Error('denied'))},
            configurable: true
          });
        }""")
    if clipboard == "blocked":
        page.evaluate("document.execCommand = () => false")

    copy.click()
    if clipboard == "blocked":
        expect(status).to_have_text(
            "Код выделен. Нажмите и удерживайте его, "
            "затем выберите «Скопировать»."
        )
        assert code.evaluate(
            "field => field.selectionStart === 0 && "
            "field.selectionEnd === field.value.length"
        )
        expect(copy).to_be_enabled()
        page.evaluate("""() => {
          Object.defineProperty(navigator, 'clipboard', {
            value: window.clipboardForTest, configurable: true
          });
          document.execCommand = window.execCommandForTest;
        }""")
        copy.click()
    expect(status).to_have_text("Код скопирован.")
    assert page.evaluate("window.clipboardForTest.readText()") == network.code
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if clipboard == "native":
        screenshot(page, f"instagram-copy-{platform}")
        page.evaluate("window.__host.wa.BackButton.click()")
        page.wait_for_function(
            "window.__host.wa.MainButton.visible && "
            "window.__host.wa.MainButton.params.text === "
            "'Подтвердить Instagram'"
        )
        network.code = "UMC-new-678901"
        page.evaluate("window.__host.wa.MainButton.click()")
        expect(code).to_have_value(network.code)
        expect(status).to_be_empty()
        copy.click()
        expect(status).to_have_text("Код скопирован.")
        assert (
            page.evaluate("window.clipboardForTest.readText()") == network.code
        )
    assert not errors

"""Trusted checkout transactions and native provider boundaries."""

from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import open_app, screenshot
from tests.e2e.test_miniapp_selection_ui import ORDER, SIGNED, SelectionNetwork

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


class CheckoutNetwork(SelectionNetwork):
    def __init__(self, locale="en", **kwargs):
        super().__init__(locale, **kwargs)
        self.checkout_requests = []
        self.invoice_abort = False
        self.value = dict(
            order_id=ORDER,
            policy_version="actual-policy",
            currency="RUB",
            amount_minor=1500000,
            invoice_state="not_requested",
            attempt_id=None,
            invoice_url=None,
            capture_state="not_recorded",
            captured_at=None,
            writes_paused=False,
            can_open=False,
            reason=None,
            version=0,
            authorization_id=None,
        )

    def route(self, route):
        path = urlparse(route.request.url).path
        prefix = f"/miniapp/api/financial/orders/{ORDER}/"
        if path.startswith(prefix) and path[len(prefix) :] in {
            "checkout-status",
            "invoice",
            "invoice/retry",
        }:
            self.checkout_requests.append((path, route.request.post_data_json))
            if path.endswith("invoice") or path.endswith("invoice/retry"):
                if self.invoice_abort:
                    route.abort("failed")
                    return
                self.value.update(
                    invoice_state="ready",
                    attempt_id="22000000-0000-4000-8000-000000000003",
                    invoice_url="https://t.me/$synthetic_invoice",
                    can_open=True,
                )
            route.fulfill(json=self.value)
            return
        super().route(route)


def open_selection(page, network, platform="telegram"):
    errors = open_app(
        page,
        network,
        platform,
        native=True,
        init_data=SIGNED,
        query=f"?selection={ORDER}",
    )
    expect(page.locator("#screen-selection")).to_be_visible()
    expect(page.locator("#selection-positions article")).to_have_count(1)
    return errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("invoice_state", ["not_requested", "ready", "unknown"])
def test_terminal_order_never_offers_a_payment_action(
    page, platform, invoice_state
):
    network = CheckoutNetwork()
    network.value.update(
        order_open_for_payment=False,
        invoice_state=invoice_state,
        invoice_url="https://t.me/$synthetic_invoice",
        can_open=True,
        telegram_handoff=f"https://t.me/actual_bot?start=pay_{ORDER}",
    )
    errors = open_selection(page, network, platform)
    expect(page.locator("#umc-checkout-status")).to_have_text(
        "This order is no longer available for payment."
    )
    expect(page.locator("#umc-checkout-action")).to_be_hidden()
    expect(page.locator("#umc-checkout-link-account")).to_be_hidden()
    assert all(
        path.endswith("/checkout-status")
        for path, _ in network.checkout_requests
    )
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "locale,notice",
    [
        ("ru", "Заказ больше недоступен для оплаты."),
        ("en", "This order is no longer available for payment."),
        ("kk", "Бұл тапсырысқа енді төлем жасау мүмкін емес."),
        ("be", "Гэта замова больш недаступная для аплаты."),
        ("uz", "Bu buyurtma uchun endi to‘lov qilib bo‘lmaydi."),
    ],
)
def test_terminal_checkout_explains_unavailability_on_small_screens(
    page, platform, locale, notice
):
    page.set_viewport_size({"width": 320, "height": 720})
    network = CheckoutNetwork(locale)
    network.value["order_open_for_payment"] = False
    errors = open_selection(page, network, platform)
    expect(page.locator("#umc-checkout-status")).to_have_text(notice)
    expect(page.locator("#umc-checkout-action")).to_be_hidden()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not errors


@pytest.mark.parametrize(
    "state,expected",
    [
        ("confirmed", "Payment confirmed by the server"),
        ("authorized", "Payment authorization awaits an outcome"),
    ],
)
def test_terminal_order_keeps_existing_payment_state_visible(
    page, state, expected
):
    network = CheckoutNetwork()
    network.value.update(order_open_for_payment=False)
    if state == "confirmed":
        network.value["capture_state"] = "confirmed"
    else:
        network.value["authorization_id"] = ORDER
    open_selection(page, network)
    expect(page.locator("#umc-checkout-status")).to_contain_text(expected)
    expect(page.locator("#umc-checkout-action")).to_be_hidden()


@pytest.mark.parametrize(
    "native_status", ["paid", "pending", "cancelled", "failed"]
)
def test_checkout_callback_only_refreshes_server_status(page, native_status):
    network = CheckoutNetwork()
    errors = open_selection(page, network)
    assert page.locator("#umc-checkout-action").count() == 1
    page.evaluate(
        (
            "window.__invoiceCalls=[];window.Telegram.WebApp.openInv"
            "oice=(url,cb)=>{window.__invoiceCalls.push(url);window."
            "__invoiceCallback=cb};void 0"
        )
    )
    page.locator("#umc-checkout-action").click()
    expect(page.locator("#umc-checkout-action")).to_have_text("Pay in Telegram")
    assert page.evaluate("window.__invoiceCalls") == []
    page.locator("#umc-checkout-action").click()
    assert page.evaluate("window.__invoiceCalls") == [
        "https://t.me/$synthetic_invoice"
    ]
    expect(page.locator("#umc-checkout-action")).to_be_disabled()
    page.evaluate("status => window.__invoiceCallback(status)", native_status)
    expect(page.locator("#umc-checkout-status")).not_to_have_attribute(
        "data-state", "confirmed"
    )
    assert (
        len([p for p, b in network.checkout_requests if p.endswith("/invoice")])
        == 1
    )
    assert all(
        b["init_data"] == SIGNED and b["platform"] == "telegram"
        for p, b in network.checkout_requests
    )
    assert all(
        not ({"paid", "status", "amount_minor", "client_id"} & b.keys())
        for p, b in network.checkout_requests
    )
    network.value.update(
        capture_state="confirmed",
        captured_at="2026-10-23T10:00:00Z",
        can_open=False,
    )
    page.locator("#umc-checkout-refresh").click()
    expect(page.locator("#umc-checkout-status")).to_have_attribute(
        "data-state", "confirmed"
    )
    expect(page.locator("#umc-checkout-action")).to_be_hidden()
    assert errors == []


def test_unknown_invoice_send_retries_same_saved_operation_without_submission(
    page,
):
    network = CheckoutNetwork()
    network.invoice_abort = True
    errors = open_selection(page, network)
    page.locator("#umc-checkout-action").click()
    expect(page.locator("#umc-checkout-action")).to_have_text(
        "Retry same request"
    )
    requests = [
        b for p, b in network.checkout_requests if p.endswith("/invoice")
    ]
    assert len(requests) == 1
    page.reload()
    expect(page.locator("#umc-checkout-action")).to_have_text(
        "Retry same request"
    )
    assert (
        len([p for p, b in network.checkout_requests if p.endswith("/invoice")])
        == 1
    )
    network.invoice_abort = False
    page.locator("#umc-checkout-action").click()
    expect(page.locator("#umc-checkout-action")).to_have_text("Pay in Telegram")
    assert [b for p, b in network.checkout_requests if p.endswith("/invoice")][
        1
    ]["operation_key"] == requests[0]["operation_key"]
    assert errors == []


@pytest.mark.parametrize("linked", [True, False])
def test_max_only_uses_verified_server_handoff_without_invoice_creation(
    page, linked
):
    network = CheckoutNetwork()
    network.value["telegram_handoff"] = (
        f"https://t.me/actual_bot?start=pay_{ORDER}" if linked else None
    )
    errors = open_selection(page, network, "max")
    if linked:
        expect(page.locator("#umc-checkout-action")).to_have_text(
            "Open order in Telegram"
        )
        page.locator("#umc-checkout-action").click()
        assert (
            page.evaluate("window.__host.calls").count(
                ["link", network.value["telegram_handoff"]]
            )
            == 1
        )
    else:
        expect(page.locator("#umc-checkout-action")).to_be_hidden()
        expect(page.locator("#umc-checkout-status")).to_contain_text(
            "securely linked"
        )
    assert all(
        p.endswith("/checkout-status") for p, b in network.checkout_requests
    )
    assert all(b["platform"] == "max" for p, b in network.checkout_requests)
    assert errors == []


@pytest.mark.parametrize("locale", ["ru", "en", "kk", "be", "uz"])
@pytest.mark.parametrize("dark", [False, True])
def test_checkout_paused_truthful_localized_and_fits_320(page, locale, dark):
    page.set_viewport_size({"width": 320, "height": 720})
    page.emulate_media(color_scheme="dark" if dark else "light")
    network = CheckoutNetwork(locale)
    network.value["writes_paused"] = True
    errors = open_selection(page, network)
    page.evaluate(
        "window.__host.wa.colorScheme='dark'"
        if dark
        else "window.__host.wa.colorScheme='light'"
    )
    page.evaluate(
        (
            "window.__host.events.themeChanged && "
            "window.__host.events.themeChanged()"
        )
    )
    expect(page.locator("#umc-checkout-action")).to_be_hidden()
    assert page.locator("#umc-checkout-status").inner_text()
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    screenshot(page, f"checkout-{locale}-" + ("dark" if dark else "light"))
    assert errors == []


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/$invoice",
        "https://t.me@evil.test/invoice/id",
        "javascript:alert(1)",
    ],
)
def test_invalid_provider_invoice_url_never_becomes_pay_control(page, url):
    network = CheckoutNetwork()
    network.value.update(invoice_state="ready", invoice_url=url, can_open=True)
    open_selection(page, network)
    expect(page.locator("#umc-checkout-action")).to_be_hidden()


def test_unknown_provider_link_creation_requires_explicit_new_attempt(page):
    network = CheckoutNetwork()
    network.value.update(
        invoice_state="unknown",
        attempt_id="22000000-0000-4000-8000-000000000003",
    )
    open_selection(page, network)
    expect(page.locator("#umc-checkout-action")).to_have_text(
        "Create another link"
    )
    assert all(
        p.endswith("/checkout-status") for p, b in network.checkout_requests
    )
    page.locator("#umc-checkout-action").click()
    expect(page.locator("#umc-checkout-action")).to_have_text("Pay in Telegram")
    payload = next(
        b for p, b in network.checkout_requests if p.endswith("/invoice/retry")
    )
    assert (
        payload["previous_attempt_id"] == "22000000-0000-4000-8000-000000000003"
    )


class TerminalCreationNetwork(CheckoutNetwork):
    def __init__(self, terminal):
        super().__init__()
        self.terminal = terminal

    def route(self, route):
        path = urlparse(route.request.url).path
        if path == f"/miniapp/api/financial/orders/{ORDER}/invoice":
            self.checkout_requests.append((path, route.request.post_data_json))
            self.value.update(
                invoice_state=self.terminal,
                attempt_id="22000000-0000-4000-8000-000000000003",
                invoice_url=None,
                can_open=False,
            )
            route.fulfill(json=self.value)
            return
        super().route(route)


@pytest.mark.parametrize("terminal", ["failed", "unknown"])
@pytest.mark.parametrize("reload", [False, True])
def test_received_terminal_creation_allows_explicit_new_attempt(
    page, terminal, reload
):
    network = TerminalCreationNetwork(terminal)
    errors = open_selection(page, network)
    page.locator("#umc-checkout-action").click()
    expect(page.locator("#umc-checkout-status")).to_have_attribute(
        "data-state", terminal
    )
    expect(page.locator("#umc-checkout-action")).to_have_text(
        "Create another link"
    )
    original = network.checkout_requests[-1][1]
    if reload:
        page.reload()
        expect(page.locator("#umc-checkout-action")).to_have_text(
            "Create another link"
        )
    assert (
        len(
            [
                path
                for path, body in network.checkout_requests
                if path.endswith("/invoice")
            ]
        )
        == 1
    )
    assert not any(
        path.endswith("/invoice/retry")
        for path, body in network.checkout_requests
    )
    page.locator("#umc-checkout-action").click()
    expect(page.locator("#umc-checkout-action")).to_have_text("Pay in Telegram")
    retry = next(
        body
        for path, body in network.checkout_requests
        if path.endswith("/invoice/retry")
    )
    assert retry["operation_key"] != original["operation_key"]
    assert retry["previous_attempt_id"] == (
        "22000000-0000-4000-8000-000000000003"
    )
    assert errors == []


def test_http_unknown_retry_keeps_original_attempt_and_entire_command(page):
    network = CheckoutNetwork()
    network.value.update(
        invoice_state="unknown",
        attempt_id="22000000-0000-4000-8000-000000000003",
    )
    network.invoice_abort = True
    errors = open_selection(page, network)
    expect(page.locator("#umc-checkout-action")).to_have_text(
        "Create another link"
    )
    page.locator("#umc-checkout-action").click()
    expect(page.locator("#umc-checkout-action")).to_have_text(
        "Retry same request"
    )
    original = next(
        body
        for path, body in network.checkout_requests
        if path.endswith("/invoice/retry")
    )
    page.reload()
    expect(page.locator("#umc-checkout-action")).to_have_text(
        "Retry same request"
    )
    assert (
        len(
            [
                path
                for path, body in network.checkout_requests
                if path.endswith("/invoice/retry")
            ]
        )
        == 1
    )
    network.invoice_abort = False
    page.locator("#umc-checkout-action").click()
    expect(page.locator("#umc-checkout-action")).to_have_text("Pay in Telegram")
    retried = [
        body
        for path, body in network.checkout_requests
        if path.endswith("/invoice/retry")
    ]
    assert retried == [original, original]
    assert errors == []

"""Production social UI against synthetic denied API responses in Chromium."""

from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e.test_miniapp_social_ui import SocialNetwork, open_socials

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]

AUTHORITY_MESSAGES = {
    "ru": "Доступ к соцсетям изменился. Обновите список, чтобы продолжить.",
    "en": "Access to social accounts has changed. Reload accounts to continue.",
    "kk": (
        "Әлеуметтік желілерге қолжетімділік өзгерді. "
        "Жалғастыру үшін тізімді жаңартыңыз."
    ),
    "be": "Доступ да сацыяльных сетак змяніўся. Абнавіце спіс, каб працягнуць.",
    "uz": (
        "Ijtimoiy tarmoqlarga kirish o‘zgardi. "
        "Davom etish uchun ro‘yxatni yangilang."
    ),
}
ERROR_MESSAGES = {
    "list": "Не удалось загрузить соцсети.",
    "save": "Не удалось сохранить ссылку.",
    "remove": "Не удалось удалить ссылку.",
}
PATHS = {
    "list": "/social/accounts",
    "save": "/social/accounts/save",
    "remove": "/social/accounts/remove",
}
DENIALS = [
    (401, "financial_session_invalid", "ru"),
    (404, "existing_financial_account_required", "en"),
    (403, "financial_principal_changed", "kk"),
    (403, "social_account_unavailable", "be"),
    (403, "financial_principal_changed", "uz"),
]
PRIVATE_HANDLE = "synthetic_private_social_owner"
PENDING_URL = "https://www.youtube.com/@synthetic_private_draft"


class AuthoritySocialNetwork(SocialNetwork):
    def __init__(self, locale: str = "ru") -> None:
        super().__init__(locale)
        self.private_handle = PRIVATE_HANDLE
        self.failure_path: str | None = None
        self.failure_status = 403
        self.failure_detail = "social_account_unavailable"
        self.socials = [
            {
                **self.instagram(),
                "account_id": "00000000-0000-0000-0000-000000000002",
                "platform": "tiktok",
                "url": f"https://www.tiktok.com/@{PRIVATE_HANDLE}",
                "handle": PRIVATE_HANDLE,
                "verified": False,
            }
        ]

    def instagram(self) -> dict:
        return {
            **super().instagram(),
            "handle": self.private_handle,
            "url": f"https://www.instagram.com/{self.private_handle}",
        }

    def route(self, route: Route) -> None:
        path = urlparse(route.request.url).path.removeprefix("/miniapp/api")
        if self.failure_path is not None and path == self.failure_path:
            body = route.request.post_data_json
            assert isinstance(body, dict)
            self.requests.append((path, body))
            route.fulfill(
                status=self.failure_status,
                json={"detail": self.failure_detail},
            )
            return
        super().route(route)


def prepared_editor(
    page: Page,
    network: AuthoritySocialNetwork,
    host: str,
    *,
    native: bool = False,
) -> list[str]:
    errors = open_socials(page, network, host, native=native)
    expect(page.locator("#screen-social-accounts")).to_be_visible()
    expect(page.locator(".umc-social-account")).to_have_count(2)
    expect(page.locator("#form-social-account")).to_have_attribute(
        "data-network", "youtube"
    )
    page.locator("#social-account-url").fill(PENDING_URL)
    page.locator("#social-account-work-format").select_option("ads_in_account")
    page.evaluate(
        "window.__staleSocialRemove = "
        "document.querySelector('[data-social-remove=\"tiktok\"]')"
    )
    return errors


def trigger(page: Page, operation: str) -> None:
    selector = {
        "list": "#btn-social-reload",
        "save": "#btn-social-save",
        "remove": '[data-social-remove="tiktok"]',
    }[operation]
    page.locator(selector).click()
    expect(page.locator("#screen-social-accounts")).to_have_attribute(
        "aria-busy", "false"
    )


@pytest.mark.parametrize("host", ["telegram", "max"])
@pytest.mark.parametrize("operation", ["list", "save", "remove"])
@pytest.mark.parametrize("status,code,locale", DENIALS)
def test_current_denial_clears_private_editor_until_successful_read(
    page: Page, host: str, operation: str, status: int, code: str, locale: str
) -> None:
    network = AuthoritySocialNetwork(locale)
    errors = prepared_editor(page, network, host)
    network.failure_path = PATHS[operation]
    network.failure_status = status
    network.failure_detail = code
    trigger(page, operation)

    expect(page.locator(".umc-social-account")).to_have_count(0, timeout=700)
    expect(page.locator("#social-account-url")).to_have_value("")
    expect(page.locator("#social-account-work-format")).to_have_value(
        "ugc_only"
    )
    expect(page.locator("#social-account-editor-title")).to_have_text("")
    expect(page.locator("#form-social-account")).not_to_have_attribute(
        "data-network", "youtube"
    )
    expect(page.locator("#form-social-account")).to_be_hidden()
    expect(page.locator("#social-accounts-gate")).to_be_hidden()
    expect(page.locator("#social-accounts-add-options button")).to_have_count(0)
    expect(page.locator("#social-accounts-success")).to_have_text("")
    expect(page.locator("#social-accounts-error")).to_have_text(
        AUTHORITY_MESSAGES[locale]
    )
    assert (
        PRIVATE_HANDLE
        not in page.locator("#screen-social-accounts").inner_html()
    )
    assert code not in page.locator("#screen-social-accounts").inner_text()
    network.failure_path = PATHS["list"]
    page.locator("#btn-social-reload").click()
    expect(page.locator("#social-accounts-error")).to_have_text(
        AUTHORITY_MESSAGES[locale]
    )
    expect(page.locator(".umc-social-account")).to_have_count(0)
    expect(page.locator("#form-social-account")).to_be_hidden()
    # Detached stale controls and a synthetic form event still meet the real
    # controller's write guard; no API mutation can use the discarded state.
    before = len(network.requests)
    before_mutations = sum(
        path in {PATHS["save"], PATHS["remove"]} for path, _ in network.requests
    )
    page.evaluate(
        """() => {
            window.__staleSocialRemove.click();
            document.querySelector('#form-social-account').dispatchEvent(
                new Event('submit', {bubbles: true, cancelable: true}));
        }"""
    )
    assert len(network.requests) == before

    # A fresh read can restore only the newly returned current facts.
    network.failure_path = None
    network.private_handle = "synthetic_current_social_owner"
    network.socials = []
    page.locator("#btn-social-reload").click()
    expect(page.locator(".umc-social-account")).to_have_count(1)
    expect(page.locator('[data-social-network="instagram"]')).to_contain_text(
        network.private_handle
    )
    expect(page.locator("#form-social-account")).to_have_attribute(
        "data-network", "tiktok"
    )
    expect(page.locator("#btn-social-save")).to_be_enabled()
    expect(page.locator("#social-account-url")).to_have_value("")
    assert (
        PRIVATE_HANDLE
        not in page.locator("#screen-social-accounts").inner_html()
    )
    assert before_mutations == sum(
        path in {PATHS["save"], PATHS["remove"]} for path, _ in network.requests
    )
    assert not errors


@pytest.mark.parametrize("host", ["telegram", "max"])
@pytest.mark.parametrize("operation", ["list", "save", "remove"])
def test_unknown_response_detail_is_private_and_transient_retry_is_usable(
    page: Page, host: str, operation: str
) -> None:
    network = AuthoritySocialNetwork()
    errors = prepared_editor(page, network, host)
    network.failure_path = PATHS[operation]
    network.failure_status = 503
    network.failure_detail = "Synthetic secret backend path /private/owner=909"
    trigger(page, operation)
    expect(page.locator("#social-accounts-error")).to_have_text(
        ERROR_MESSAGES[operation], timeout=700
    )
    assert (
        "Synthetic secret"
        not in page.locator("#screen-social-accounts").inner_text()
    )
    network.failure_path = None
    if operation == "list":
        page.locator("#btn-social-reload").click()
        expect(page.locator("#form-social-account")).to_be_visible()
    elif operation == "save":
        expect(page.locator("#social-account-url")).to_have_value(PENDING_URL)
        expect(page.locator("#btn-social-save")).to_be_enabled()
        page.locator("#btn-social-save").click()
        expect(page.locator('[data-social-network="youtube"]')).to_be_visible()
    else:
        expect(page.locator('[data-social-network="tiktok"]')).to_be_visible()
        page.locator('[data-social-remove="tiktok"]').click()
        expect(page.locator('[data-social-network="tiktok"]')).to_have_count(0)
    assert not errors


@pytest.mark.parametrize("host", ["telegram", "max"])
def test_url_validation_failure_keeps_draft_and_allows_correction(
    page: Page, host: str
) -> None:
    network = AuthoritySocialNetwork()
    errors = prepared_editor(page, network, host)
    network.failure_path = PATHS["save"]
    network.failure_status = 400
    network.failure_detail = "social_url_invalid"
    trigger(page, "save")
    expect(page.locator("#social-account-url")).to_have_value(PENDING_URL)
    expect(page.locator("#social-account-work-format")).to_have_value(
        "ads_in_account"
    )
    expect(page.locator("#btn-social-save")).to_be_enabled()
    expect(page.locator(".umc-social-account")).to_have_count(2)
    network.failure_path = None
    page.locator("#social-account-url").fill(
        "https://www.youtube.com/@synthetic_corrected"
    )
    page.locator("#btn-social-save").click()
    expect(page.locator('[data-social-network="youtube"] a')).to_have_attribute(
        "href", "https://www.youtube.com/@synthetic_corrected"
    )
    assert not errors


@pytest.mark.parametrize("host", ["telegram", "max"])
def test_current_denial_disables_the_native_save_action(
    page: Page, host: str
) -> None:
    network = AuthoritySocialNetwork()
    errors = prepared_editor(page, network, host, native=True)
    assert page.evaluate("window.__host.wa.MainButton.visible") is True
    network.failure_path = PATHS["save"]
    network.failure_detail = "financial_principal_changed"
    page.evaluate("window.__host.wa.MainButton.click()")
    expect(page.locator("#social-accounts-error")).to_have_text(
        AUTHORITY_MESSAGES["ru"]
    )
    assert page.evaluate("window.__host.wa.MainButton.visible") is False
    expect(page.locator(".umc-social-account")).to_have_count(0)
    page.evaluate("window.__host.wa.MainButton.click()")
    network.failure_path = None
    page.locator("#btn-social-reload").click()
    expect(page.locator("#form-social-account")).to_be_visible()
    assert sum(path == PATHS["save"] for path, _ in network.requests) == 1
    assert not errors

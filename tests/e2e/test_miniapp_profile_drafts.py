"""Device-local recovery through real Telegram/MAX forms and synthetic APIs."""

from urllib.parse import urlparse

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
USER_A = "00000000-0000-0000-0000-000000000101"
USER_B = "00000000-0000-0000-0000-000000000102"


class DraftNetwork(MiniAppNetwork):
    def __init__(self):
        super().__init__()
        self.user_id = USER_A
        self.advertiser = None
        self.creator = None
        self.reject = False
        self.hold = False
        self.held = None
        self.pending = None
        self.fail_next_me = False

    def accept(self, role, body):
        data = {**body, "agreement_confirmed": False}
        if role == "blogger":
            self.creator = {**data, "confirmed": False}
        else:
            self.advertiser = data

    def route(self, route):
        path = urlparse(route.request.url).path.removeprefix("/miniapp/api")
        if path == "/me":
            self.requests.append((path, route.request.post_data_json))
            if self.fail_next_me:
                self.fail_next_me = False
                route.fulfill(status=503, json={"detail": "Refresh failed"})
                return
            route.fulfill(
                json={
                    "user_id": self.user_id,
                    "locale": "ru",
                    "country": "ru",
                    "has_advertiser_profile": self.advertiser is not None,
                    "advertiser_profile": self.advertiser,
                    "has_blogger_profile": self.creator is not None,
                    "blogger_profile": self.creator,
                    "is_manager": False,
                }
            )
        elif path in ("/register/advertiser", "/register/blogger"):
            body = route.request.post_data_json
            self.requests.append((path, body))
            if self.reject:
                route.fulfill(
                    status=422, json={"detail": "Synthetic save failure"}
                )
            elif self.hold:
                self.held = route
                self.pending = (path.rsplit("/", 1)[-1], body)
            else:
                self.accept(path.rsplit("/", 1)[-1], body)
                route.fulfill(json={"needs_agreement": True})
        else:
            super().route(route)


def panel(page, role):
    return page.locator(f'[data-profile-draft="{role}"]')


def enter(page, role):
    if role == "advertiser":
        saved = page.locator("#btn-adv-update-profile")
    else:
        saved = page.locator("#btn-blogger-update-profile")
    if saved.is_visible():
        saved.click()
    else:
        page.locator(f'[data-role="{role}"]').click()
    expect(page.locator(f"#screen-register-{role}")).to_be_visible()


def field(role):
    return "#blg-name" if role == "blogger" else "#adv-brand"


def back(page, role):
    page.locator(
        "#back-from-blogger" if role == "blogger" else "#back-from-advertiser"
    ).click()


def city(page, *, confirm=True):
    page.locator("#btn-blogger-city-map").click()
    page.locator("#blg-city-search").fill("Synthetic city")
    page.locator("#btn-blogger-city-search").click()
    expect(page.locator("#blg-city")).to_have_value("Synthetic city")
    if confirm:
        page.locator("#btn-blogger-city-confirm").click()


def fill(page, role):
    if role == "advertiser":
        page.locator("#adv-brand").fill("Synthetic brand")
        page.locator("#adv-phone").fill("89001234567")
        return
    page.locator("#blg-name").fill("Synthetic creator")
    page.locator("#blg-instagram").fill("@synthetic_creator")
    page.locator("#blg-birth-day").select_option("15")
    page.locator("#blg-birth-month").select_option("6")
    page.locator("#blg-birth-year").select_option("1995")
    page.locator("#blg-topics").fill("beauty, fashion")
    page.locator("#blg-audience-geo").fill("Synthetic geography")
    page.locator("#blg-price").fill("10000")
    city(page)


def draft_records(page):
    return page.evaluate("""() => Object.keys(localStorage)
      .filter(k => k.startsWith('umc:profile-draft:') && !k.endsWith(':epoch'))
      .map(k => JSON.parse(localStorage.getItem(k)))""")


@pytest.mark.parametrize("role", ["blogger", "advertiser"])
def test_partial_profile_survives_closing_webview(page, platform, role):
    network = DraftNetwork()
    errors = open_app(page, network, platform)
    enter(page, role)
    page.locator(field(role)).fill("Unfinished profile")
    expect(panel(page, role)).to_contain_text(
        "Черновик сохранён на этом устройстве"
    )
    records = draft_records(page)
    assert len(records) == 1
    assert records[0]["identity"] == platform + ":" + USER_A
    assert not any(
        k in str(records)
        for k in (
            "init_data",
            "confirmed",
            "agree-checkbox",
            "verification-code",
        )
    )
    reopened = page.context.new_page()
    try:
        reopened.set_viewport_size({"width": 390, "height": 844})
        errors += open_app(reopened, network, platform)
        reopened.get_by_role(
            "button",
            name="Продолжить анкету креатора"
            if role == "blogger"
            else "Продолжить анкету заказчика",
        ).click()
        expect(reopened.locator(f"#form-{role}")).to_be_hidden()
        screenshot(reopened, f"{platform}-{role}-profile-draft-choice")
        panel(reopened, role).get_by_role(
            "button", name="Продолжить заполнение"
        ).click()
        expect(reopened.locator(field(role))).to_have_value(
            "Unfinished profile"
        )
        assert not any(p.startswith("/register/") for p, _ in network.requests)
        assert not errors
    finally:
        reopened.close()


def test_roles_are_separate_and_start_over_clears_only_one_draft(
    page, platform
):
    network = DraftNetwork()
    errors = open_app(page, network, platform)
    enter(page, "blogger")
    page.locator("#blg-name").fill("Creator draft")
    back(page, "blogger")
    enter(page, "advertiser")
    page.locator("#adv-brand").fill("Advertiser draft")
    page.reload()
    enter(page, "blogger")
    panel(page, "blogger").get_by_role("button", name="Начать заново").click()
    expect(page.locator("#blg-name")).to_have_value("")
    assert [r["role"] for r in draft_records(page)] == ["advertiser"]
    back(page, "blogger")
    enter(page, "advertiser")
    panel(page, "advertiser").get_by_role(
        "button", name="Продолжить заполнение"
    ).click()
    expect(page.locator("#adv-brand")).to_have_value("Advertiser draft")
    assert not errors


def test_another_account_cannot_restore_or_clear_previous_draft(page, platform):
    network = DraftNetwork()
    errors = open_app(page, network, platform)
    enter(page, "advertiser")
    page.locator("#adv-brand").fill("Private account A")
    network.user_id = USER_B
    page.reload()
    enter(page, "advertiser")
    expect(page.locator("#adv-brand")).to_have_value("")
    page.locator("#adv-brand").fill("Private account B")
    panel(page, "advertiser").get_by_role(
        "button", name="Начать заново"
    ).click()
    network.user_id = USER_A
    page.reload()
    enter(page, "advertiser")
    panel(page, "advertiser").get_by_role(
        "button", name="Продолжить заполнение"
    ).click()
    expect(page.locator("#adv-brand")).to_have_value("Private account A")
    assert not errors


def test_platforms_do_not_share_profile_drafts(page, platform):
    network = DraftNetwork()
    errors = open_app(page, network, platform)
    enter(page, "advertiser")
    page.locator("#adv-brand").fill("First messenger")
    other = page.context.new_page()
    try:
        errors += open_app(
            other, network, "max" if platform == "telegram" else "telegram"
        )
        enter(other, "advertiser")
        expect(other.locator("#adv-brand")).to_have_value("")
        expect(
            panel(other, "advertiser").get_by_role(
                "button", name="Продолжить заполнение"
            )
        ).to_be_hidden()
        assert not errors
    finally:
        other.close()


@pytest.mark.parametrize("role", ["blogger", "advertiser"])
def test_failure_keeps_draft_success_clears_it_without_accepting_terms(
    page, platform, role
):
    network = DraftNetwork()
    errors = open_app(page, network, platform)
    enter(page, role)
    fill(page, role)
    network.reject = True
    page.locator("#btn-submit-" + role).click()
    expect(
        page.locator("#blg-error" if role == "blogger" else "#adv-error")
    ).to_have_text("Synthetic save failure")
    expect(page.locator(field(role))).to_be_enabled()
    page.reload()
    enter(page, role)
    panel(page, role).get_by_role(
        "button", name="Продолжить заполнение"
    ).click()
    if role == "blogger":
        expect(page.locator("#blg-city")).to_have_value("Synthetic city")
        expect(page.locator("#blg-lat")).to_have_value("0")
        expect(page.locator("#blg-birth-year")).to_have_value("1995")
    network.reject = False
    page.locator("#btn-submit-" + role).click()
    expect(page.locator(f"#screen-agreements-{role}")).to_be_visible()
    expect(
        page.locator(
            "#blg-agree-checkbox"
            if role == "blogger"
            else "#adv-agree-checkbox"
        )
    ).not_to_be_checked()
    assert draft_records(page) == []
    assert not errors


def test_unconfirmed_city_is_not_restored_as_verified_coordinates(
    page, platform
):
    network = DraftNetwork()
    errors = open_app(page, network, platform)
    enter(page, "blogger")
    page.locator("#blg-name").fill("City selection interrupted")
    city(page, confirm=False)
    page.reload()
    enter(page, "blogger")
    panel(page, "blogger").get_by_role(
        "button", name="Продолжить заполнение"
    ).click()
    expect(page.locator("#blg-city")).to_have_value("")
    expect(page.locator("#blg-lat")).to_have_value("")
    expect(page.locator("#blg-city-search")).to_have_value("Synthetic city")
    assert not errors


def test_start_over_in_editor_restores_saved_profile_and_makes_no_request(
    page, platform
):
    network = DraftNetwork()
    network.advertiser = {
        "brand": "Saved brand",
        "phone": "89001234567",
        "agreement_confirmed": True,
    }
    errors = open_app(page, network, platform)
    enter(page, "advertiser")
    page.locator("#adv-brand").fill("Unsaved edits")
    page.reload()
    enter(page, "advertiser")
    panel(page, "advertiser").get_by_role(
        "button", name="Начать заново"
    ).click()
    expect(page.locator("#adv-brand")).to_have_value("Saved brand")
    assert network.advertiser["brand"] == "Saved brand"
    assert not any(p.startswith("/register/") for p, _ in network.requests)
    assert not errors


@pytest.mark.parametrize("blocked", ["setItem", "getItem"])
def test_storage_failure_does_not_block_registration_or_claim_durability(
    page, platform, blocked
):
    page.add_init_script(
        f"Storage.prototype.{blocked} = () => {{throw new Error('blocked')}}"
    )
    network = DraftNetwork()
    errors = open_app(page, network, platform)
    enter(page, "advertiser")
    fill(page, "advertiser")
    expect(panel(page, "advertiser")).to_contain_text(
        "Не удалось сохранить черновик"
    )
    page.locator("#btn-submit-advertiser").click()
    expect(page.locator("#screen-agreements-advertiser")).to_be_visible()
    assert not errors


def test_session_change_clears_visible_fields_and_never_saves_for_new_actor(
    page, platform
):
    network = DraftNetwork()
    errors = open_app(page, network, platform)
    enter(page, "advertiser")
    page.locator("#adv-brand").fill("Private account A")
    page.evaluate("window.__host.wa.initData = 'another-session'")
    page.locator("#adv-city").fill("A new keystroke")
    expect(page.locator("#adv-brand")).to_have_value("")
    expect(panel(page, "advertiser")).to_contain_text(
        "Откройте Mini App заново"
    )
    assert len(draft_records(page)) == 1
    assert not errors


def test_mobile_native_resume_uses_main_button(page, platform):
    network = DraftNetwork()
    page.set_viewport_size({"width": 320, "height": 640})
    errors = open_app(page, network, platform, native=True)
    enter(page, "advertiser")
    page.locator("#adv-brand").fill("Native draft")
    page.reload()
    enter(page, "advertiser")
    page.wait_for_function(
        "window.__host.wa.MainButton.params.text === 'Продолжить заполнение'"
    )
    screenshot(page, f"{platform}-profile-draft-resume")
    page.evaluate("window.__host.wa.MainButton.click()")
    expect(page.locator("#adv-brand")).to_have_value("Native draft")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not errors


def test_clearing_in_another_window_blocks_stale_draft_and_submit(
    page, platform
):
    network = DraftNetwork()
    errors = open_app(page, network, platform)
    enter(page, "advertiser")
    fill(page, "advertiser")
    other = page.context.new_page()
    try:
        errors += open_app(other, network, platform)
        enter(other, "advertiser")
        panel(other, "advertiser").get_by_role(
            "button", name="Начать заново"
        ).click()
        page.locator("#adv-brand").fill("Stale window")
        expect(panel(page, "advertiser")).to_contain_text(
            "Черновик изменился в другом окне"
        )
        page.locator("#btn-submit-advertiser").click()
        assert not any(p.startswith("/register/") for p, _ in network.requests)
        assert draft_records(page) == []
        assert not errors
    finally:
        other.close()


def test_success_preserves_newer_editor_draft_from_another_window(
    page, platform
):
    network = DraftNetwork()
    network.advertiser = {
        "brand": "Saved brand",
        "phone": "89001234567",
        "agreement_confirmed": True,
    }
    errors = open_app(page, network, platform)
    enter(page, "advertiser")
    page.locator("#adv-brand").fill("First submitted edit")
    network.hold = True
    page.locator("#btn-submit-advertiser").click()
    expect(page.locator("#adv-brand")).to_be_disabled()
    other = page.context.new_page()
    try:
        errors += open_app(other, network, platform)
        enter(other, "advertiser")
        panel(other, "advertiser").get_by_role(
            "button", name="Продолжить заполнение"
        ).click()
        other.locator("#adv-brand").fill("Newer unsaved edit")
        assert network.held is not None
        network.accept(*network.pending)
        network.held.fulfill(json={"needs_agreement": True})
        expect(page.locator("#screen-agreements-advertiser")).to_be_visible()
        records = draft_records(other)
        assert len(records) == 1
        assert records[0]["values"]["adv-brand"] == "Newer unsaved edit"
        assert not errors
    finally:
        other.close()


@pytest.mark.parametrize("damage", ["json", "owner", "oversized"])
def test_corrupt_or_foreign_storage_never_fills_the_profile(
    page, platform, damage
):
    network = DraftNetwork()
    errors = open_app(page, network, platform)
    enter(page, "advertiser")
    page.locator("#adv-brand").fill("An invalid draft")
    page.evaluate(
        """damage => {
      const key = Object.keys(localStorage).find(k =>
        k.startsWith('umc:profile-draft:') && !k.endsWith(':epoch'));
      const data = JSON.parse(localStorage.getItem(key));
      if (damage === 'owner') data.identity = 'another-account';
      if (damage === 'oversized') data.values['adv-brand'] = 'x'.repeat(40000);
      localStorage.setItem(key,
        damage === 'json' ? '{broken' : JSON.stringify(data));
    }""",
        damage,
    )
    page.reload()
    enter(page, "advertiser")
    expect(page.locator("#adv-brand")).to_have_value("")
    expect(
        panel(page, "advertiser").get_by_role(
            "button", name="Продолжить заполнение"
        )
    ).to_be_hidden()
    assert not errors


def test_accepted_registration_recovers_when_webview_missed_response(
    page, platform
):
    network = DraftNetwork()
    errors = open_app(page, network, platform)
    enter(page, "advertiser")
    fill(page, "advertiser")
    network.advertiser = {
        "brand": "Server accepted brand",
        "phone": "89001234567",
        "agreement_confirmed": False,
    }
    page.reload()
    expect(page.locator("#screen-agreements-advertiser")).to_be_visible()
    expect(page.locator("#adv-agree-checkbox")).not_to_be_checked()
    assert draft_records(page) == []
    assert not errors


def test_oversized_input_does_not_claim_a_restorable_draft(page, platform):
    network = DraftNetwork()
    errors = open_app(page, network, platform)
    enter(page, "advertiser")
    page.locator("#adv-activity").fill("x" * 4001)
    expect(panel(page, "advertiser")).to_contain_text(
        "Не удалось сохранить черновик"
    )
    assert draft_records(page) == []
    assert not errors


def test_switching_sdk_before_opening_a_form_never_offers_previous_draft(
    page, platform
):
    network = DraftNetwork()
    errors = open_app(page, network, platform)
    enter(page, "advertiser")
    page.locator("#adv-brand").fill("Private previous draft")
    back(page, "advertiser")
    page.evaluate("window.__host.wa.initData = 'another-session'")
    enter(page, "advertiser")
    expect(panel(page, "advertiser")).to_contain_text(
        "Откройте Mini App заново"
    )
    expect(
        panel(page, "advertiser").get_by_role(
            "button", name="Продолжить заполнение"
        )
    ).to_be_hidden()
    expect(page.locator("#adv-brand")).to_have_value("")
    assert len(draft_records(page)) == 1
    assert not errors


def test_further_typing_after_accepted_registration_and_failed_refresh_survives(
    page, platform
):
    network = DraftNetwork()
    errors = open_app(page, network, platform)
    enter(page, "advertiser")
    fill(page, "advertiser")
    network.fail_next_me = True
    page.locator("#btn-submit-advertiser").click()
    expect(page.locator("#adv-error")).to_have_text("Refresh failed")
    expect(page.locator("#adv-brand")).to_be_enabled()
    page.locator("#adv-brand").fill("New edits after accepted registration")
    page.reload()
    page.locator("#back-from-adv-agreements").click()
    panel(page, "advertiser").get_by_role(
        "button", name="Продолжить заполнение"
    ).click()
    expect(page.locator("#adv-brand")).to_have_value(
        "New edits after accepted registration"
    )
    assert not errors

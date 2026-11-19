"""Chat registration buttons open the selected role without another choice."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_country_identity import CountryNetwork
from tests.e2e.test_miniapp_design_system import MiniAppNetwork, open_app

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
ROLES = ["advertiser", "blogger"]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("has_other_profile", [False, True])
def test_registration_link_opens_selected_form(page, role, has_other_profile):
    network = MiniAppNetwork(registered=role == "blogger" and has_other_profile)
    network.blogger_registered = role == "advertiser" and has_other_profile
    network.advertiser_agreed = False
    network.blogger_agreement_confirmed = False
    errors = open_app(page, network, query=f"?view=register-{role}")
    expect(page.locator(f"#screen-register-{role}")).to_be_visible()
    expect(page.locator("#screen-role-choice")).to_be_hidden()
    assert not any(
        path.startswith("/register/") for path, _ in network.requests
    )
    assert not errors


@pytest.mark.parametrize("role", ROLES)
def test_registration_link_survives_country_selection(page, role):
    network = CountryNetwork()
    errors = open_app(page, network, query=f"?view=register-{role}")
    expect(page.locator("#screen-country-select")).to_be_visible()
    page.get_by_role("button", name="Россия").click()
    expect(page.locator(f"#screen-register-{role}")).to_be_visible()
    expect(page.locator("#screen-role-choice")).to_be_hidden()
    assert len(network.countries) == 1
    assert not errors


@pytest.mark.parametrize("role", ROLES)
def test_registration_link_keeps_first_input_and_resumes_draft(page, role):
    network = MiniAppNetwork()
    errors = open_app(page, network, query=f"?view=register-{role}")
    field = page.locator("#adv-brand" if role == "advertiser" else "#blg-name")
    draft = page.locator(f'[data-profile-draft="{role}"]')
    field.fill("Unfinished profile")
    expect(field).to_have_value("Unfinished profile")
    expect(draft).to_contain_text("Черновик сохранён на этом устройстве")

    page.reload()
    expect(page.locator(f"#screen-register-{role}")).to_be_visible()
    expect(page.locator(f"#form-{role}")).to_be_hidden()
    draft.get_by_role(
        "button", name="Продолжить заполнение", exact=True
    ).click()
    expect(field).to_have_value("Unfinished profile")
    assert not any(
        path.startswith("/register/") for path, _ in network.requests
    )
    assert not errors


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("agreed", [False, True])
def test_old_registration_link_reuses_existing_profile(page, role, agreed):
    network = MiniAppNetwork(registered=True)
    network.blogger_registered = True
    network.advertiser_agreed = agreed
    network.blogger_agreement_confirmed = agreed
    errors = open_app(page, network, query=f"?view=register-{role}")
    screen = (
        f"screen-{role}-dashboard" if agreed else f"screen-agreements-{role}"
    )
    expect(page.locator("#" + screen)).to_be_visible()
    expect(page.locator(f"#screen-register-{role}")).to_be_hidden()
    assert not any(
        path.startswith("/register/") for path, _ in network.requests
    )
    assert not errors


@pytest.mark.parametrize("role", ROLES)
def test_registration_link_still_requires_telegram_session(page, role):
    network = MiniAppNetwork()
    open_app(page, network, query=f"?view=register-{role}", init_data="")
    expect(page.locator("#screen-loading")).to_have_attribute(
        "data-failed", "true"
    )
    expect(page.locator(f"#screen-register-{role}")).to_be_hidden()
    assert not network.requests


def test_unknown_registration_role_keeps_normal_role_choice(page):
    network = MiniAppNetwork()
    errors = open_app(page, network, query="?view=register-manager")
    expect(page.locator("#screen-role-choice")).to_be_visible()
    assert not errors


@pytest.mark.parametrize(
    "role,prefix", [("advertiser", "adv"), ("blogger", "blg")]
)
def test_profile_can_be_submitted_from_registration_link(page, role, prefix):
    network = MiniAppNetwork()
    errors = open_app(page, network, query=f"?view=register-{role}")
    page.locator(f"#{prefix}-name").fill("Synthetic account")
    if role == "advertiser":
        page.locator("#adv-phone").fill("89001234567")
        page.locator("#adv-brand").fill("Synthetic brand")
    else:
        page.locator("#blg-instagram").fill("@synthetic_creator")
        page.locator("#blg-birth-year").select_option("1995")
        page.locator("#blg-topics").fill("beauty, fashion")
        page.locator("#blg-audience-geo").fill("Россия, Казань")
        page.locator("#blg-price").fill("10000")
        page.locator("#btn-blogger-city-map").click()
        page.locator("#blg-city-search").fill("Synthetic city")
        page.locator("#blg-city-search").press("Enter")
        expect(page.locator("#blg-city")).to_have_value("Synthetic city")
        page.locator("#btn-blogger-city-confirm").click()
    page.locator(f"#btn-submit-{role}").click()
    expect(page.locator(f"#screen-agreements-{role}")).to_be_visible()
    page.locator(f"#{prefix}-agree-checkbox").check()
    page.locator(f"#btn-confirm-{prefix}-agreement").click()
    expect(page.locator(f"#screen-{role}-dashboard")).to_be_visible()
    assert [
        path for path, _ in network.requests if path.startswith("/register/")
    ] == [f"/register/{role}", f"/register/{role}/confirm-agreement"]
    assert not errors

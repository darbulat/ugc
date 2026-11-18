"""Level progression uses the signed partner read and the existing UMC UI."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import open_app, screenshot
from tests.e2e.test_miniapp_partner_ui import SIGNED, PartnerNetwork

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


def set_verified_count(network, count):
    tiers = network.partner["standards"]["creator_tiers"]
    current = max(
        (tier for tier in tiers if tier["threshold"] <= count),
        key=lambda tier: tier["threshold"],
    )
    following = next(
        (tier["threshold"] for tier in tiers if tier["threshold"] > count),
        None,
    )
    network.partner["grade"].update(
        verified_creators=count,
        threshold=current["threshold"],
        tier_rate_bps=current["rate_bps"],
        next_threshold=following,
        remaining=following - count if following is not None else None,
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "count,name,progress,earned",
    [
        (0, "Старт", "0", 0),
        (1, "Старт", "1", 1),
        (99, "Старт", "99", 4),
        (100, "Бронза", "0", 5),
        (137, "Бронза", "37", 5),
        (199, "Бронза", "99", 5),
        (200, "Серебро", "0", 6),
        (399, "Серебро", "99.5", 6),
        (400, "Золото", "100", 7),
        (401, "Золото", "100", 7),
    ],
)
def test_partner_level_boundaries_and_current_achievements(
    page, platform, count, name, progress, earned
):
    network = PartnerNetwork()
    set_verified_count(network, count)
    errors = open_app(page, network, platform, query="?view=partner")
    level = page.locator("#partner-grade")
    expect(level.locator(".umc-partner-level-name")).to_have_text(name)
    expect(level.get_by_role("progressbar")).to_have_attribute(
        "aria-valuenow", progress
    )
    expect(page.locator("#partner-grade-count")).to_have_text(
        f"Подтверждённые авторы · {count}"
    )
    expect(
        page.locator('#partner-achievements [data-achieved="true"]')
    ).to_have_count(earned)
    if count >= 400:
        expect(page.locator("#partner-grade-next")).to_be_empty()
    else:
        remaining = network.partner["grade"]["remaining"]
        expect(page.locator("#partner-grade-next")).to_have_text(
            f"Осталось подтвердить {remaining}"
        )
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_manager_level_opens_same_achievements_and_native_back(page, platform):
    network = PartnerNetwork("manager")
    set_verified_count(network, 137)
    errors = open_app(page, network, platform, native=True, init_data=SIGNED)
    page.locator("#btn-manager-role").click()
    home = page.locator("#screen-manager-orders [data-partner-home]")
    expect(home.locator(".umc-partner-level-name")).to_have_text("Бронза")
    expect(home.get_by_role("progressbar")).to_have_attribute(
        "aria-valuenow", "37"
    )
    home.get_by_role("button", name="Все достижения · 5 из 7").click()
    expect(page.locator("#partner-achievements")).to_be_focused()
    expect(page.locator("#partner-grade-value")).to_have_text("12%")
    page.evaluate("window.__host.wa.BackButton.click()")
    expect(page.locator("#screen-manager-orders")).to_be_visible()
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_invite_uses_own_link_and_falls_back_to_selection(page, platform):
    network = PartnerNetwork()
    page.add_init_script("""
        Object.defineProperty(navigator, 'clipboard', {value: undefined});
        document.execCommand = () => false;
    """)
    errors = open_app(page, network, platform, query="?view=partner")
    level = page.locator("#partner-grade")
    level.get_by_role("button", name="Пригласить автора").click()
    expect(level.get_by_role("textbox")).to_have_value(
        network.partner["referral"]["link"]
    )
    expect(level.get_by_role("status")).to_contain_text("Ссылка выделена")
    assert (
        level.get_by_role("textbox").evaluate(
            "input => input.value.slice("
            "input.selectionStart, input.selectionEnd)"
        )
        == network.partner["referral"]["link"]
    )
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_refresh_recalculates_achievements_and_keeps_historical_rates(
    page, platform
):
    network = PartnerNetwork()
    set_verified_count(network, 400)
    network.partner["overrides"]["entries"] = [
        {
            "side": "creator",
            "rate_bps": 1700,
            "policy_version": "existing-individual-terms",
            "effective_from": "2026-01-01T00:00:00Z",
            "effective_until": "2027-01-01T00:00:00Z",
        }
    ]
    errors = open_app(page, network, platform, query="?view=partner")
    page.locator('#partner-achievements [data-threshold="400"]').click()
    expect(page.locator(".umc-partner-achievement-detail")).to_contain_text(
        "Достигнуто"
    )
    expect(page.locator("#partner-overrides")).to_contain_text("17%")
    expect(page.locator("#partner-history")).to_contain_text("10%")

    set_verified_count(network, 99)
    page.locator("#btn-partner-reload").click()
    expect(page.locator(".umc-partner-level-name").first).to_have_text("Старт")
    expect(
        page.locator('#partner-achievements [data-achieved="true"]')
    ).to_have_count(4)
    expect(page.locator("#partner-overrides")).to_contain_text("17%")
    expect(page.locator("#partner-history")).to_contain_text("10%")
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_unavailable_count_and_failed_read_do_not_show_zero_level(
    page, platform
):
    network = PartnerNetwork()
    network.partner["grade"]["verified_creators"] = None
    errors = open_app(page, network, platform, query="?view=partner")
    expect(page.locator("#partner-grade")).to_contain_text(
        "Данные источника временно недоступны"
    )
    expect(
        page.locator("#partner-grade").get_by_role("progressbar")
    ).to_have_count(0)
    expect(page.locator("#partner-achievements")).to_be_empty()
    network.partner_code = 503
    page.locator("#btn-partner-reload").click()
    expect(page.locator("#partner-content")).to_be_hidden()
    expect(page.locator("#partner-error")).to_contain_text(
        "Не удалось загрузить"
    )
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_account_change_clears_levels_and_achievements(page, platform):
    network = PartnerNetwork("manager")
    set_verified_count(network, 400)
    errors = open_app(page, network, platform, query="?view=partner")
    expect(page.locator("#partner-grade-value")).to_have_text("20%")
    page.evaluate("""() => {
        window._me.user_id = 'another-account';
        document.dispatchEvent(new Event('visibilitychange'));
    }""")
    expect(page.locator("#partner-content")).to_be_hidden()
    expect(page.locator("#partner-grade")).to_be_empty()
    expect(page.locator("#partner-achievements")).to_be_empty()
    expect(
        page.locator("#screen-manager-orders .umc-partner-level-name")
    ).to_have_count(0)
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "locale,name",
    [
        ("ru", "Бронза"),
        ("en", "Bronze"),
        ("kk", "Қола"),
        ("be", "Бронза"),
        ("uz", "Bronza"),
    ],
)
def test_levels_use_umc_design_on_narrow_screens_in_both_themes(
    page, platform, locale, name
):
    page.set_viewport_size({"width": 320, "height": 850})
    network = PartnerNetwork("manager", locale)
    set_verified_count(network, 137)
    errors = open_app(page, network, platform, native=True)
    page.locator("#btn-manager-role").click()
    home = page.locator("#screen-manager-orders [data-partner-home]")
    expect(home.locator(".umc-partner-level-name")).to_have_text(name)
    assert "umc-card--mint" in home.get_attribute("class")
    for theme in ("light", "dark"):
        page.evaluate(
            "theme => { window.__host.wa.colorScheme = theme; "
            "window.__host.events.themeChanged(); }",
            theme,
        )
        assert page.evaluate(
            "document.documentElement.scrollWidth <= innerWidth"
        )
        screenshot(page, f"manager-level-{platform}-{locale}-{theme}")
    home.locator("[data-partner-open]").click()
    expect(page.locator("#partner-achievements")).to_be_focused()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot(page, f"partner-level-{platform}-{locale}-dark")
    assert not errors

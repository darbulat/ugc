"""Manual supplements show their own source without an invented percentage."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import open_app
from tests.e2e.test_miniapp_partner_ui import SIGNED, PartnerNetwork

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "locale,label,rate",
    [
        ("ru", "Ручное доначисление", "Ставка не применяется"),
        ("en", "Manual grant", "Rate does not apply"),
        ("kk", "Қолмен қосымша есептеу", "Мөлшерлеме қолданылмайды"),
        ("be", "Ручное даналічэнне", "Стаўка не ўжываецца"),
        ("uz", "Qo‘lda qo‘shimcha hisoblash", "Stavka qo‘llanilmaydi"),
    ],
)
def test_manual_grant_group_translated_and_rate_not_applicable(
    page, platform, locale, label, rate
):
    network = PartnerNetwork(locale=locale)
    money = network.partner["financial"]
    manual = money["groups"][0] | {"kind": "manual_adjustment"}
    money["groups"].append(manual)
    money["history"]["entries"] = [
        money["history"]["entries"][0]
        | {
            "kind": "manual_adjustment",
            "rate_bps": None,
            "rate_source": "manual",
        }
    ]
    errors = open_app(
        page, network, platform, init_data=SIGNED, query="?view=partner"
    )
    expect(page.locator("#partner-balances")).to_contain_text(label)
    expect(page.locator("#partner-history")).to_contain_text(label)
    expect(page.locator("#partner-history")).to_contain_text(rate)
    expect(page.locator("#partner-history")).not_to_contain_text(
        "manual_adjustment"
    )
    assert not errors

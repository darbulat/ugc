"""Actual UMC templates with synthetic signed commercial HTTP boundaries."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import open_app
from tests.e2e.test_miniapp_partner_ui import SIGNED, PartnerNetwork
from tests.e2e.test_miniapp_selection_ui import SelectionNetwork, fill

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


class Network(PartnerNetwork):
    def __init__(self, admin=False):
        super().__init__()
        self.admin = admin
        self.commands = []

    def route(self, route):
        url = route.request.url
        if url.endswith("/me"):
            route.fulfill(
                json=dict(
                    user_id=self.partner["actor_id"],
                    locale="ru",
                    country="ru",
                    currency_symbol="₽",
                    has_advertiser_profile=True,
                    has_blogger_profile=False,
                    is_manager=True,
                )
            )
            return
        if url.endswith("/subscriptions/view"):
            route.fulfill(
                json=dict(
                    actor_id=self.partner["actor_id"],
                    can_admin=self.admin,
                    can_manage=True,
                    tariffs=[
                        dict(
                            version="v1",
                            title="Synthetic test tariff",
                            price_minor=10000,
                            currency="RUB",
                            duration_days=30,
                            campaign_limit=5,
                            recipient_limit=100,
                            terms_reference="synthetic terms",
                        )
                    ],
                    subscription=dict(
                        state="active", until="2026-12-01T00:00:00Z"
                    ),
                    automation_enabled=False,
                    paid_pilot_managers=0,
                    repeated_paid_use=False,
                )
            )
            return
        if "/subscriptions/" in url:
            self.commands.append(route.request.post_data_json)
            route.fulfill(json={"saved": True})
            return
        super().route(route)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_actual_subscription_owner_can_read_tariffs_and_cancel_with_reason(
    page, platform
):
    network = Network()
    errors = open_app(
        page, network, platform, init_data=SIGNED, query="?view=partner"
    )
    page.locator("#screen-partner [data-subscriptions-open]").click()
    screen = page.locator("#screen-subscriptions")
    expect(screen).to_contain_text("Synthetic test tariff")
    screen.locator("summary", has_text="Отменить доступ").click()
    screen.locator('input[name="reason"]').fill("Останавливаю доступ")
    screen.locator("button", has_text="Сохранить").click()
    expect(screen.locator("button", has_text="Обновить")).to_be_enabled()
    assert len(network.commands) == 1
    assert network.commands[0]["reason"] == "Останавливаю доступ"
    assert network.commands[0]["init_data"] == SIGNED
    assert "actor_id" not in network.commands[0]
    assert not errors


@pytest.mark.parametrize("price", ["12300", "9007199254740993"])
def test_published_tariff_admin_form_preserves_exact_price(page, price):
    network = Network(admin=True)
    errors = open_app(
        page, network, "telegram", init_data=SIGNED, query="?view=partner"
    )
    page.locator("#screen-partner [data-subscriptions-open]").click()
    screen = page.locator("#screen-subscriptions")
    expect(screen).to_contain_text("Оплаченные пилоты: 0")
    expect(
        screen.get_by_text("Разрешить автоматизацию после пилотов", exact=True)
    ).to_have_count(0)
    screen.locator("summary", has_text="Опубликовать тариф").click()
    form = (
        screen.locator("details")
        .filter(has=page.locator("summary", has_text="Опубликовать тариф"))
        .locator("form")
    )
    for name, value in dict(
        version="v2",
        title="New test tariff",
        price_minor=price,
        duration_days="30",
        campaign_limit="5",
        recipient_limit="100",
        terms_reference="published actual terms",
        reason="Agreed publication",
    ).items():
        form.locator(f'input[name="{name}"]').fill(value)
    form.locator("button").click()
    expect(screen.locator("button", has_text="Обновить")).to_be_enabled()
    assert len(network.commands) == 1
    assert network.commands[0]["price_minor"] == price
    assert "paid" not in network.commands[0]
    assert not errors


def test_intake_targeting_is_sent_in_actual_saved_command(page):
    network = SelectionNetwork()
    errors = open_app(page, network, "telegram", init_data=SIGNED)
    page.locator("#btn-umc-intake").click()
    fill(page)
    page.locator("#intake-min_followers").fill("1000")
    page.locator("#intake-max_followers").fill("20000")
    page.locator("#intake-gender").select_option("f")
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-result")).to_be_visible()
    assert network.creates[0]["targeting"] == dict(
        min_followers=1000,
        max_followers=20000,
        min_age=None,
        max_age=None,
        gender="f",
    )
    assert not errors


class FunnelNetwork(SelectionNetwork):
    def route(self, route):
        if route.request.url.endswith("/financial/orders/policies"):
            route.fulfill(
                json=dict(
                    currency="RUB",
                    writes_paused=False,
                    policies=self.policies,
                    funnel_tracking=True,
                )
            )
            return
        if route.request.url.endswith("/financial/orders/funnel/stage"):
            route.fulfill(json={"recorded": True})
            return
        super().route(route)


def test_intake_draft_survives_reload_without_submitting_or_repricing(page):
    network = FunnelNetwork()
    errors = open_app(page, network, "telegram", init_data=SIGNED)
    page.locator("#btn-umc-intake").click()
    fill(page)
    page.locator("#intake-min_followers").fill("1234")
    original = page.locator("#intake-brief").input_value()
    page.reload()
    page.locator("#btn-umc-intake").click()
    expect(page.locator("#intake-brief")).to_have_value(original)
    expect(page.locator("#intake-min_followers")).to_have_value("1234")
    assert network.creates == []
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-result")).to_be_visible()
    assert network.creates[0]["funnel_id"]
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("status", [409, 500])
def test_subscription_definitive_rejection_can_reset_but_unknown_retries_exact(
    page, platform, status
):
    network = Network()
    original = network.route
    attempts = []

    def route(intercept):
        if intercept.request.url.endswith("/subscriptions/cancel"):
            attempts.append(intercept.request.post_data_json)
            intercept.fulfill(
                status=status if len(attempts) == 1 else 200,
                json={"detail": "synthetic_rejection"}
                if len(attempts) == 1
                else {"saved": True},
            )
        else:
            original(intercept)

    network.route = route
    errors = open_app(
        page, network, platform, init_data=SIGNED, query="?view=partner"
    )
    page.locator("#screen-partner [data-subscriptions-open]").click()
    screen = page.locator("#screen-subscriptions")
    screen.locator("summary", has_text="Отменить доступ").click()
    screen.locator("input[name=reason]").fill("Synthetic cancellation")
    screen.get_by_role("button", name="Сохранить", exact=True).click()
    if status == 409:
        reset = screen.get_by_role(
            "button", name="Исправить отклонённый запрос"
        )
        expect(reset).to_be_visible()
        reset.click()
        expect(
            screen.locator("summary", has_text="Отменить доступ")
        ).to_be_visible()
        assert len(attempts) == 1
    else:
        expect(
            screen.get_by_role("button", name="Исправить отклонённый запрос")
        ).to_have_count(0)
        screen.get_by_role(
            "button",
            name="Операция не подтверждена. Повторите тот же запрос.",
            exact=True,
        ).click()
        expect(
            screen.locator("summary", has_text="Отменить доступ")
        ).to_be_visible()
        assert len(attempts) == 2 and attempts[0] == attempts[1]
    assert not errors

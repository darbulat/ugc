"""Manual contacts and registration links remain separate visible actions."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


def render_invite(**overrides):
    root = Path(__file__).resolve().parents[2] / "src/ugc_bot/admin"
    templates = Environment(
        loader=FileSystemLoader(root / "templates"),
        autoescape=select_autoescape(),
    )
    templates.globals.update(
        admin_asset=lambda request, name: f"http://invites.test/{name}",
        admin_action_token=lambda request: "synthetic-action-token",
    )
    request = SimpleNamespace(
        url=SimpleNamespace(path="/admin/orders/test/creator-invites"),
        query_params={},
        url_for=lambda name, **kwargs: (
            "http://invites.test/admin/orders/test/creator-invites"
            if name == "admin_creator_invites"
            else "http://invites.test/admin/orders/test"
        ),
    )
    data = dict(
        request=request,
        order_id=uuid4(),
        title="UMC-TEST",
        enabled=True,
        items=[SimpleNamespace(paid_item_id=uuid4(), ordinal=3)],
        managers=[],
        invites=[],
        availability=None,
        instagram="@manual_creator",
        telegram="@manual_creator",
        creator_name="Тестовый креатор",
        consent_source="",
        partners_enabled=True,
        referrers=[],
    )
    return root, templates.get_template("creator_invites.html").render(
        data | overrides
    )


def assets(page, root):

    def asset(route):
        name = route.request.url.rsplit("/", 1)[-1]
        route.fulfill(body=(root / "static" / name).read_bytes())

    page.route("http://invites.test/*.css", asset)


@pytest.mark.parametrize("availability", [None, "ready", "blocked", "external"])
def test_customer_send_requires_visible_consent_and_preserves_link_action(
    page, availability
):
    root, html = render_invite(availability=availability)
    assets(page, root)
    page.set_content(html)
    page.evaluate("""() => {
      window.submissions = [];
      document.querySelector('main form').addEventListener('submit', e => {
        if (e.defaultPrevented) return;
        e.preventDefault();
        window.submissions.push(Object.fromEntries(new FormData(
          e.target, e.submitter
        )));
      });
    }""")
    consent = page.get_by_role("checkbox")
    expect(consent).to_be_visible()
    customer = page.locator("#invite-customer-action")
    link = page.get_by_role("button", name="Создать ссылку", exact=True)
    expect(customer).to_be_disabled()
    expect(link).to_be_enabled()
    expect(
        page.get_by_label("Кто общается с креатором по заказу")
    ).to_have_value("")
    link.click()
    assert page.evaluate("submissions[0].operation") == "create"
    consent.check()
    expect(customer).to_be_enabled()
    if availability == "ready":
        expect(page.locator("#invite-creator-action")).to_be_hidden()
    customer.click()
    assert page.evaluate("submissions.length") == 1
    page.get_by_label("Где получено согласие").select_option("telegram")
    customer.click()
    assert page.evaluate("submissions[1].operation") == "send_customer"
    assert page.evaluate("submissions[1].record_consent") == "1"
    assert page.evaluate("submissions[1].manager_id") == ""
    expect(page.locator("#invite-submit-status")).to_contain_text("Отправляем")
    customer.click()
    assert page.evaluate("submissions.length") == 2
    consent.uncheck()
    expect(customer).to_be_disabled()
    expect(link).to_be_enabled()


@pytest.mark.parametrize("width", [1440, 390])
def test_success_receipt_prominently_shows_position_and_opens_clean_next_form(
    page, width
):
    next_item = SimpleNamespace(paid_item_id=uuid4(), ordinal=5)
    root, html = render_invite(
        handoff=dict(ordinal=4, creator_name="Мила Ужегова", instagram="mila"),
        needed=10,
        items=[next_item],
    )
    _, next_html = render_invite(
        items=[next_item], instagram="", telegram="", creator_name=""
    )
    assets(page, root)
    page.set_viewport_size({"width": width, "height": 900})
    page.set_content(html)
    receipt = page.locator("#invite-result")
    expect(receipt).to_be_visible()
    expect(receipt).to_contain_text("Контакт отправлен заказчице в Telegram")
    expect(receipt).to_contain_text("Позиция №4 из 10 · Мила Ужегова")
    expect(page.locator("#invite-creator-form")).to_have_count(0)
    page.route(
        "http://invites.test/admin/orders/test/creator-invites",
        lambda route: route.fulfill(body=next_html, content_type="text/html"),
    )
    page.get_by_role("link", name="Добавить следующего креатора · №5").click()
    expect(page.locator("#invite-instagram")).to_have_value("")
    expect(page.locator("#invite-telegram")).to_have_value("")
    expect(page.locator('[name="creator_name"]')).to_have_value("")
    expect(page.locator('[name="manager_id"]')).to_have_value("")
    expect(page.locator('[name="referrer_id"]')).to_have_value("")
    expect(page.get_by_role("checkbox")).not_to_be_checked()
    expect(page.locator("#invite-item")).to_contain_text(
        "Первая свободная · №5"
    )
    expect(page.locator("#invite-customer-action")).to_be_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_manager_and_partner_are_independent_and_existing_partner_is_locked(
    page,
):
    first, second = [
        SimpleNamespace(user_id=uuid4(), username=name, telegram=name)
        for name in ("Первый", "Второй")
    ]
    root, html = render_invite(
        managers=[first, second], referrers=[first, second]
    )
    assets(page, root)
    page.set_content(html)
    manager = page.get_by_label("Кто общается с креатором по заказу")
    partner = page.get_by_label("Кому принадлежит реферальная привязка")
    manager.select_option(str(first.user_id))
    partner.select_option(str(second.user_id))
    expect(manager).to_have_value(str(first.user_id))
    expect(partner).to_have_value(str(second.user_id))
    partner.select_option(str(first.user_id))
    expect(manager).to_have_value(str(first.user_id))
    manager.select_option("")
    expect(partner).to_have_value(str(first.user_id))
    _, locked = render_invite(
        managers=[second], referrers=[first, second], referrer=first
    )
    page.set_content(locked)
    expect(
        page.get_by_text("Существующая привязка сохраняется.", exact=False)
    ).to_be_visible()
    expect(page.locator('select[name="referrer_id"]')).to_have_count(0)
    expect(page.locator('input[name="referrer_id"]')).to_have_value(
        str(first.user_id)
    )
    page.get_by_label("Кто общается с креатором по заказу").select_option(
        str(second.user_id)
    )

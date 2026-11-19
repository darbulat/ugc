"""Manual contacts and registration links remain separate visible actions."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


@pytest.mark.parametrize("availability", [None, "ready", "blocked", "external"])
def test_customer_send_requires_visible_consent_and_preserves_link_action(
    page, availability
):
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
        url_for=lambda *args, **kwargs: "/admin/orders/test",
    )
    html = templates.get_template("creator_invites.html").render(
        request=request,
        order_id=uuid4(),
        title="UMC-TEST",
        enabled=True,
        items=[SimpleNamespace(paid_item_id=uuid4(), ordinal=3)],
        managers=[],
        invites=[],
        availability=availability,
        instagram="@manual_creator",
        telegram="@manual_creator",
        creator_name="Тестовый креатор",
        consent_source="",
    )

    def asset(route):
        name = route.request.url.rsplit("/", 1)[-1]
        route.fulfill(body=(root / "static" / name).read_bytes())

    page.route("http://invites.test/*.css", asset)
    page.set_content(html)
    page.evaluate("""() => {
      window.submissions = [];
      document.querySelector('main form').addEventListener('submit', e => {
        e.preventDefault();
        window.submissions.push(Object.fromEntries(new FormData(
          e.target, e.submitter
        )));
      });
    }""")
    consent = page.get_by_role("checkbox")
    expect(consent).to_be_visible()
    customer = page.get_by_role(
        "button", name="Отправить заказчику", exact=True
    )
    link = page.get_by_role("button", name="Создать ссылку", exact=True)
    expect(customer).to_be_disabled()
    expect(link).to_be_enabled()
    expect(page.get_by_label("Менеджер команды заказа")).to_have_value("")
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
    consent.uncheck()
    expect(customer).to_be_disabled()
    expect(link).to_be_enabled()

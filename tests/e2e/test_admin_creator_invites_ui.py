"""Searchable manual contacts, independent assignments and clear receipts."""

from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
BASE = "http://invites.test/admin/orders/test/creator-invites"


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
    routes = {
        "admin_creator_invites": BASE,
        "admin_invite_search": BASE + "/search",
        "admin_invite_profile": BASE + "/profile",
    }
    request = SimpleNamespace(
        url=SimpleNamespace(path=urlsplit(BASE).path),
        query_params={},
        url_for=lambda name, **kwargs: routes.get(
            name, "http://invites.test/admin/orders/test"
        ),
    )
    data = dict(
        request=request,
        order_id=uuid4(),
        title="UMC-TEST",
        enabled=True,
        needed=10,
        items=[SimpleNamespace(paid_item_id=uuid4(), ordinal=3)],
        manager=None,
        selected_referrer=None,
        invites=[],
        availability=None,
        instagram="@manual_creator",
        telegram="@manual_creator",
        creator_name="Тестовый креатор",
        consent_source="",
        partners_enabled=True,
    )
    return root, templates.get_template("creator_invites.html").render(
        data | overrides
    )


def assets(page, root):
    def asset(route):
        name = urlsplit(route.request.url).path.rsplit("/", 1)[-1]
        route.fulfill(
            body=(root / "static" / name).read_bytes(),
            content_type="text/javascript"
            if name.endswith(".js")
            else "text/css",
        )

    page.route("http://invites.test/*.css", asset)
    page.route("http://invites.test/*.js", asset)


def open_form(page, root, html):
    assets(page, root)
    page.route(
        BASE, lambda route: route.fulfill(body=html, content_type="text/html")
    )
    page.goto(BASE)


def person(name, handle):
    return dict(
        id=str(uuid4()),
        name=name,
        detail=f"Telegram · @{handle}",
        telegram=handle,
        instagram=handle + ".ig",
        creator_name=name,
    )


def directory(page, people, *, referrer=None):
    def search(route):
        query = parse_qs(urlsplit(route.request.url).query)
        rows = people.get(query["kind"][0], [])
        route.fulfill(json={"results": rows, "more": False})

    page.route(BASE + "/search?**", search)
    page.route(
        BASE + "/profile?**",
        lambda route: route.fulfill(
            json={"availability": "blocked", "referrer": referrer}
        ),
    )


@pytest.mark.parametrize("availability", [None, "ready", "blocked", "external"])
def test_customer_send_requires_visible_consent_and_preserves_link_action(
    page, availability
):
    root, html = render_invite(availability=availability)
    open_form(page, root, html)
    page.evaluate("""() => {
      window.submissions = [];
      const form = document.getElementById('invite-creator-form');
      form.addEventListener('submit', e => {
        if (e.defaultPrevented) return;
        e.preventDefault();
        const data = new FormData(e.target, e.submitter);
        window.submissions.push(Object.fromEntries(data));
      });
    }""")
    consent = page.get_by_role("checkbox")
    expect(consent).to_be_visible()
    customer = page.locator("#invite-customer-action")
    link = page.get_by_role("button", name="Создать ссылку", exact=True)
    expect(customer).to_be_disabled()
    expect(link).to_be_enabled()
    expect(page.locator('[name="manager_id"]')).to_have_value("")
    expect(page.locator("#invite-source-wrap")).to_be_hidden()
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
    expect(page.locator("#invite-submit-status")).to_contain_text("Отправляем")
    customer.click()
    assert page.evaluate("submissions.length") == 2


@pytest.mark.parametrize("width", [1440, 390])
def test_success_receipt_prominently_shows_position_and_opens_clean_next_form(
    page, width
):
    next_item = SimpleNamespace(paid_item_id=uuid4(), ordinal=5)
    root, html = render_invite(
        handoff=dict(ordinal=4, creator_name="Мила Ужегова", instagram="mila"),
        items=[next_item],
    )
    _, next_html = render_invite(
        items=[next_item], instagram="", telegram="", creator_name=""
    )
    page.set_viewport_size({"width": width, "height": 900})
    open_form(page, root, html)
    receipt = page.locator("#invite-result")
    expect(receipt).to_be_visible()
    expect(receipt).to_contain_text("Контакт отправлен заказчице в Telegram")
    expect(receipt).to_contain_text("Позиция №4 из 10 · Мила Ужегова")
    expect(page.locator("#invite-creator-form")).to_have_count(0)
    page.route(
        BASE,
        lambda route: route.fulfill(body=next_html, content_type="text/html"),
    )
    page.get_by_role("link", name="Добавить следующего креатора · №5").click()
    for selector in [
        "#invite-instagram",
        "#invite-telegram",
        '[name="creator_name"]',
        '[name="manager_id"]',
        '[name="referrer_id"]',
    ]:
        expect(page.locator(selector)).to_have_value("")
    expect(page.get_by_role("checkbox")).not_to_be_checked()
    expect(page.locator("#invite-item")).to_contain_text(
        "Первая свободная · №5"
    )
    expect(page.locator("#invite-customer-action")).to_be_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_search_selects_independent_people_and_typing_clears_stale_identity(
    page,
):
    first, second = (
        person("Анна Петрова", "anna_manager"),
        person("Олег Иванов", "oleg_partner"),
    )
    directory(page, {"manager": [first], "referrer": [second]})
    root, html = render_invite()
    open_form(page, root, html)
    manager = page.get_by_role("combobox", name="Рабочий менеджер", exact=True)
    manager.fill("Анна")
    option = page.get_by_role(
        "option", name="Анна Петрова Telegram · @anna_manager"
    )
    expect(option).to_be_visible()
    expect(option.locator("mark")).to_have_text("Анна")
    manager.press("ArrowDown")
    manager.press("Enter")
    expect(page.locator('[name="manager_id"]')).to_have_value(first["id"])
    partner = page.get_by_role("combobox", name="Реферер / партнёр", exact=True)
    partner.fill("oleg")
    page.locator('.invite-popup:not([hidden]) [role="option"]').click()
    expect(page.locator('[name="referrer_id"]')).to_have_value(second["id"])
    manager.fill("Другой")
    expect(page.locator('[name="manager_id"]')).to_have_value("")
    expect(page.locator('[name="referrer_id"]')).to_have_value(second["id"])
    manager.press("Escape")
    expect(page.get_by_role("listbox")).to_be_hidden()
    page.get_by_role("button", name="Снять выбор: Рабочий менеджер").click()
    expect(manager).to_have_value("")
    expect(page.locator('[name="referrer_id"]')).to_have_value(second["id"])


@pytest.mark.parametrize("width", [1440, 390])
def test_creator_search_autofills_contacts_and_preserves_existing_referrer(
    page, width
):
    creator = person("Таня Барская", "tt_barskaya")
    partner = person("Олег Иванов", "oleg_partner")
    directory(page, {"creator": [creator]}, referrer=partner)
    root, html = render_invite(instagram="", telegram="", creator_name="")
    page.set_viewport_size({"width": width, "height": 900})
    open_form(page, root, html)
    query = page.get_by_role("combobox", name="Найти креатора в базе")
    query.fill("Барская")
    option = page.locator('.invite-popup:not([hidden]) [role="option"]')
    expect(option).to_contain_text("Таня Барская")
    assert option.bounding_box()["width"] <= width
    option.click()
    expect(page.locator("#invite-instagram")).to_have_value("@tt_barskaya.ig")
    expect(page.locator("#invite-telegram")).to_have_value("@tt_barskaya")
    expect(page.locator("#invite-name")).to_have_value("Таня Барская")
    expect(page.locator("#invite-profile-status")).to_contain_text(
        "бот заблокирован"
    )
    expect(page.locator('[name="referrer_id"]')).to_have_value(partner["id"])
    expect(page.locator("#invite-referrer-search")).to_have_attribute(
        "readonly", ""
    )
    expect(page.get_by_text("Закреплён ранее")).to_be_visible()
    page.route(
        BASE + "/profile?**",
        lambda route: route.fulfill(
            json={"availability": "external", "referrer": None}
        ),
    )
    page.locator("#invite-instagram").fill("@new_person")
    expect(page.locator('[name="referrer_id"]')).to_have_value("")
    expect(page.locator("#invite-referrer-search")).not_to_have_attribute(
        "readonly", ""
    )
    expect(page.locator("#invite-profile-status")).to_contain_text(
        "Новый креатор"
    )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_no_matches_and_search_errors_allow_manual_contact_entry(page):
    directory(page, {})
    root, html = render_invite(instagram="", telegram="", creator_name="")
    open_form(page, root, html)
    query = page.get_by_role("combobox", name="Найти креатора в базе")
    query.fill("@new_creator")
    page.get_by_role("button", name="Ввести контакты вручную").click()
    expect(page.locator("#invite-instagram")).to_have_value("@new_creator")
    expect(page.locator("#invite-instagram")).to_be_focused()
    page.route(BASE + "/search?**", lambda route: route.fulfill(status=503))
    manager = page.get_by_role("combobox", name="Рабочий менеджер", exact=True)
    manager.fill("Анна")
    expect(
        page.get_by_text("Поиск недоступен. Попробуйте ещё раз.")
    ).to_be_visible()
    directory(page, {"manager": [person("Анна Петрова", "anna_manager")]})
    manager.fill("Петрова")
    expect(
        page.locator('.invite-popup:not([hidden]) [role="option"]')
    ).to_contain_text("Анна Петрова")


def test_search_labels_are_text_and_late_results_do_not_replace_current_query(
    page,
):
    directory(
        page,
        {"manager": [person('<img src=x onerror="alert(1)">', "safe_handle")]},
    )
    root, html = render_invite()
    open_form(page, root, html)
    manager = page.get_by_role("combobox", name="Рабочий менеджер", exact=True)
    pending = []
    page.route(BASE + "/search?**", lambda route: pending.append(route))
    manager.fill("old")
    page.wait_for_timeout(230)
    assert len(pending) == 1
    manager.fill("safe")
    page.wait_for_timeout(230)
    assert len(pending) == 2
    pending[1].fulfill(
        json={
            "results": [
                person('<img src=x onerror="alert(1)">', "safe_handle")
            ],
            "more": False,
        }
    )
    expect(
        page.locator('.invite-popup:not([hidden]) [role="option"]')
    ).to_contain_text("safe_handle")
    pending[0].fulfill(
        json={"results": [person("Старый результат", "old")], "more": False}
    )
    expect(
        page.locator('.invite-popup:not([hidden]) [role="option"]')
    ).to_contain_text("safe_handle")
    expect(
        page.locator('.invite-popup:not([hidden]) [role="option"]').locator(
            "img"
        )
    ).to_have_count(0)


def test_touch_selection_and_clearing_keep_manager_and_referrer_independent(
    browser,
):
    with browser.new_context(
        viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True
    ) as context:
        page = context.new_page()
        chosen = person("Анна Петрова", "anna_manager")
        directory(page, {"manager": [chosen], "referrer": [chosen]})
        root, html = render_invite()
        open_form(page, root, html)
        page.locator("#invite-manager-search").fill("Анна")
        page.locator('.invite-popup:not([hidden]) [role="option"]').tap()
        expect(page.locator('[name="manager_id"]')).to_have_value(chosen["id"])
        page.locator("#invite-referrer-search").fill("Анна")
        page.locator('.invite-popup:not([hidden]) [role="option"]').tap()
        expect(page.locator('[name="referrer_id"]')).to_have_value(chosen["id"])
        page.get_by_role("button", name="Снять выбор: Рабочий менеджер").tap()
        expect(page.locator('[name="manager_id"]')).to_have_value("")
        expect(page.locator('[name="referrer_id"]')).to_have_value(chosen["id"])

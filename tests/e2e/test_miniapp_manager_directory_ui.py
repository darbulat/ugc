"""Manager navigation and directory filtering in both Mini App hosts."""

import re
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import open_app
from tests.e2e.test_miniapp_partner_ui import PartnerNetwork

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
PATH = "/manager/invited-creators"
ACTIVE = {
    "creator_id": "9c84ce00-e8ba-4ccf-9831-10f1f54bff5f",
    "name": "Мария",
    "city": "",
    "status": "active",
    "instagram_verified": False,
    "telegram_url": "https://t.me/creator_maria",
    "followup_due": True,
    "remind_at": None,
}
BLOCKED = {
    "creator_id": "b1d4bc16-2955-4fda-a8d0-ddd9611b3618",
    "name": "Ирина",
    "city": "Казань",
    "status": "bot_blocked",
    "instagram_verified": True,
    "telegram_url": None,
    "followup_due": False,
    "remind_at": None,
}


class ManagerDirectoryNetwork(PartnerNetwork):
    def __init__(self):
        super().__init__(role="manager")
        self.creators = [dict(ACTIVE), dict(BLOCKED)]
        self.fail_followup = False

    def route(self, route):
        path = urlparse(route.request.url).path.removeprefix("/miniapp/api")
        if not path.startswith(PATH):
            super().route(route)
            return
        body = route.request.post_data_json
        self.requests.append((path, body))
        if path == PATH:
            creators = self.creators
            due_count = sum(creator["followup_due"] for creator in creators)
            instagram = body.get("instagram", "all")
            if instagram == "due":
                creators = [
                    creator for creator in creators if creator["followup_due"]
                ]
            elif instagram != "all":
                creators = [
                    creator
                    for creator in creators
                    if creator["instagram_verified"]
                    == (instagram == "verified")
                ]
            if body["bot_unavailable"]:
                creators = [
                    creator
                    for creator in creators
                    if creator["status"] == "bot_blocked"
                ]
            query = body.get("q", "").lower()
            creators = [
                creator
                for creator in creators
                if query in creator["name"].lower()
                or query in creator["city"].lower()
                or query.lstrip("@")
                in (creator["telegram_url"] or "").rsplit("/", 1)[-1].lower()
            ]
            route.fulfill(
                json={
                    "creators": creators,
                    "has_more": False,
                    "followup_count": due_count,
                }
            )
            return
        creator_id, _, action = path.removeprefix(f"{PATH}/").partition("/")
        creator = next(
            (row for row in self.creators if row["creator_id"] == creator_id),
            None,
        )
        if creator is None:
            route.fulfill(status=404, json={"detail": "creator_not_found"})
        elif action == "followup":
            if self.fail_followup:
                route.fulfill(status=503, json={"detail": "Unavailable"})
                return
            date = 25 if body["action"] == "contacted" else 24
            creator.update(
                followup_due=False, remind_at=f"2026-11-{date}T12:00:00Z"
            )
            route.fulfill(json={"remind_at": creator["remind_at"]})
        else:
            route.fulfill(
                json={
                    **creator,
                    "links": [
                        {
                            "label": "YouTube",
                            "url": "https://www.youtube.com/@synthetic",
                        }
                    ],
                }
            )


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("native", [True, False])
def test_invited_creator_filter_and_card_return(page, platform, native):
    network = ManagerDirectoryNetwork()
    errors = open_app(page, network, platform, native=native)
    page.get_by_role("button", name="Менеджер", exact=True).click()
    page.get_by_role("button", name="Моя база креаторов").click()

    listing = page.locator("#screen-invited-creators")
    active = listing.get_by_role("button", name="Мария", exact=True)
    expect(active).to_be_visible()
    blocked = listing.get_by_role("button", name="Ирина", exact=True)
    expect(blocked).to_be_visible()
    search = listing.get_by_role("searchbox", name="Имя, ник или город")
    search.fill("мар")
    expect(blocked).to_have_count(0)
    expect(active).to_be_visible()
    status_filter = listing.get_by_role("checkbox", name="Бот недоступен")
    status_filter.check()
    expect(
        listing.get_by_text("Креаторы по этому запросу не найдены.")
    ).to_be_visible()
    search.fill("  казань  ")
    expect(blocked).to_be_visible()
    expect(active).to_have_count(0)
    instagram = listing.get_by_role("combobox", name="Подтверждение Instagram")
    instagram.select_option("verified")
    expect(blocked).to_be_visible()
    blocked.click()

    card = page.locator("#screen-invited-creator-card")
    expect(card.get_by_role("heading", name="Ирина")).to_be_visible()
    expect(card.get_by_role("link", name="YouTube")).to_have_attribute(
        "href", "https://www.youtube.com/@synthetic"
    )
    if native:
        page.evaluate("window.__host.wa.BackButton.click()")
    else:
        card.get_by_role("button", name="К списку").click()
    expect(status_filter).to_be_checked()
    expect(instagram).to_have_value("verified")
    expect(search).to_have_value("  казань  ")
    expect(blocked).to_be_visible()
    expect(active).to_have_count(0)
    search.fill("@creator_maria")
    expect(listing.locator("#invited-creators-status")).to_have_text(
        "Креаторы по этому запросу не найдены."
    )
    expect(listing.get_by_role("button", name="К личной ссылке")).to_be_hidden()
    listing.get_by_role("button", name="Сбросить поиск и фильтры").click()
    expect(search).to_have_value("")
    expect(active).to_be_visible()
    if native:
        page.evaluate("window.__host.wa.BackButton.click()")
    else:
        listing.get_by_role("button", name="К кабинету менеджера").click()
    expect(page.get_by_role("heading", name="Мои заказы")).to_be_visible()
    directory_calls = [
        (path, body) for path, body in network.requests if path.startswith(PATH)
    ]
    assert all(body["platform"] == platform for _, body in directory_calls)
    assert any(
        body.get("q") == "казань" and body["bot_unavailable"]
        for _, body in directory_calls
    )
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("width", [320, 390])
def test_manager_instagram_queue_filters_and_schedules_contact(
    page, platform, width
):
    network = ManagerDirectoryNetwork()
    page.set_viewport_size({"width": width, "height": 740})
    errors = open_app(page, network, platform, native=True)
    page.get_by_role("button", name="Менеджер", exact=True).click()
    page.get_by_role("button", name="Моя база креаторов").click()

    listing = page.locator("#screen-invited-creators")
    filters = listing.get_by_role("combobox", name="Подтверждение Instagram")
    filters.select_option("verified")
    expect(
        listing.locator("#invited-creators-list").get_by_text(
            "Instagram подтверждён", exact=True
        )
    ).to_be_visible()
    expect(listing.get_by_text("Нет контакта в Telegram")).to_be_visible()
    expect(
        listing.get_by_role("link", name="Написать в Telegram")
    ).to_have_count(0)

    filters.select_option("unverified")
    contact = listing.get_by_role("link", name="Написать в Telegram")
    expect(contact).to_have_attribute("href", ACTIVE["telegram_url"])

    listing.get_by_role("button", name="Нужно связаться: 1").click()
    listing.get_by_role("button", name="Напомнить завтра").click()
    expect(
        listing.get_by_role("button", name="Нужно связаться: 0")
    ).to_be_visible()
    expect(listing.locator("#invited-creators-status")).to_have_text(
        "В этой группе пока никого нет."
    )
    expect(listing.locator("#invited-followup-notice")).to_contain_text(
        "24 нояб."
    )
    filters.select_option("unverified")
    search = listing.get_by_role("searchbox", name="Имя, ник или город")
    with page.expect_response(
        lambda response: (
            response.url.endswith(PATH)
            and response.request.post_data_json.get("q") == "@creator_maria"
        )
    ):
        search.fill("@creator_maria")
    expect(
        listing.get_by_text(re.compile(r"Связаться после 24 нояб\."))
    ).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth") == width
    listing.get_by_role("button", name="Мария", exact=True).click()

    card = page.locator("#screen-invited-creator-card")
    card_contact = card.get_by_role("link", name="Написать в Telegram")
    expect(card_contact).to_have_attribute("href", ACTIVE["telegram_url"])
    card_contact.click()
    expected_call = "telegram-link" if platform == "telegram" else "link"
    assert [expected_call, ACTIVE["telegram_url"]] in page.evaluate(
        "window.__host.calls"
    )
    contacted = card.get_by_role("button", name="Написал", exact=True)
    network.fail_followup = True
    contacted.click()
    expect(card.get_by_role("alert")).to_contain_text("Не удалось сохранить")
    expect(
        card.get_by_text(re.compile(r"Связаться после 24 нояб\."))
    ).to_be_visible()
    network.fail_followup = False
    contacted.click()
    expect(
        card.get_by_text(re.compile(r"Связаться после 25 нояб\."))
    ).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth") == width

    page.evaluate("window.__host.wa.BackButton.click()")
    expect(search).to_have_value("@creator_maria")
    expect(filters).to_have_value("unverified")
    expect(
        listing.get_by_text(re.compile(r"Связаться после 25 нояб\."))
    ).to_be_visible()
    assert [
        body["action"]
        for path, body in network.requests
        if path == f"{PATH}/{ACTIVE['creator_id']}/followup"
    ] == ["tomorrow", "contacted", "contacted"]
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_followup_refreshes_queue_if_manager_returns_before_save(
    page, platform
):
    network = ManagerDirectoryNetwork()
    errors = open_app(
        page, network, platform, query="?view=manager&section=creators"
    )
    pending = []
    followup = f"{PATH}/{ACTIVE['creator_id']}/followup"
    page.route(f"**{followup}", lambda route: pending.append(route))

    listing = page.locator("#screen-invited-creators")
    listing.get_by_role("button", name="Нужно связаться: 1").click()
    creator = listing.get_by_role("button", name="Мария", exact=True)
    creator.click()
    card = page.locator("#screen-invited-creator-card")
    with page.expect_request(lambda request: request.url.endswith(followup)):
        card.get_by_role("button", name="Написал", exact=True).click()
    card.get_by_role("button", name="К списку").click()
    expect(creator).to_be_visible()

    network.route(pending.pop())
    expect(
        listing.get_by_role("button", name="Нужно связаться: 0")
    ).to_have_attribute("aria-pressed", "true")
    expect(listing.locator("#invited-followup-notice")).to_contain_text(
        "25 нояб."
    )
    expect(creator).to_have_count(0)
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("approved", [True, False])
def test_manager_notification_opens_only_the_approved_managers_base(
    page, platform, approved
):
    network = ManagerDirectoryNetwork()
    network.manager = approved
    network.creators = []
    errors = open_app(
        page,
        network,
        platform,
        native=True,
        query="?view=manager&section=creators",
    )
    listing = page.locator("#screen-invited-creators")
    if approved:
        expect(
            listing.get_by_role("heading", name="Моя база креаторов")
        ).to_be_visible()
        expect(listing.locator("#invited-creators-status")).to_contain_text(
            "личной ссылкой"
        )
        assert any(path == PATH for path, _ in network.requests)
        page.evaluate("window.__host.wa.BackButton.click()")
        expect(page.locator("#screen-manager-orders")).to_be_visible()
        expect(
            page.get_by_role("button", name="Подписка менеджера")
        ).to_have_count(0)
    else:
        expect(page.locator("#screen-role-choice")).to_be_visible()
        expect(listing).to_be_hidden()
        assert not any(
            path.startswith("/manager/") for path, _ in network.requests
        )
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_empty_directory_leads_to_existing_personal_link(page, platform):
    network = ManagerDirectoryNetwork()
    network.creators = []
    page.set_viewport_size({"width": 320, "height": 740})
    page.add_init_script(
        """
        Object.defineProperty(navigator, 'clipboard', {
          value: { writeText: async (url) => { window.__copiedInvite = url; } }
        });
        """
    )
    errors = open_app(
        page, network, platform, query="?view=manager&section=creators"
    )
    listing = page.locator("#screen-invited-creators")
    listing.get_by_role("button", name="К личной ссылке").click()
    expect(listing).to_be_hidden()
    partner = page.locator("#screen-manager-orders [data-partner-home]")
    expect(partner).to_be_focused()
    partner.get_by_role("button", name="Пригласить автора").click()
    expect(partner.get_by_role("status")).to_have_text("Ссылка скопирована.")
    assert (
        page.evaluate("window.__copiedInvite")
        == network.partner["referral"]["link"]
    )
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("open_card", [False, True])
def test_revoked_creator_card_does_not_expose_contacts(
    page, platform, open_card
):
    network = ManagerDirectoryNetwork()
    errors = open_app(
        page, network, platform, query="?view=manager&section=creators"
    )
    listing = page.locator("#screen-invited-creators")
    creator = listing.get_by_role("button", name="Мария", exact=True)
    card = page.locator("#screen-invited-creator-card")
    expect(creator).to_be_visible()
    if open_card:
        creator.click()
        expect(
            card.get_by_role("link", name="Написать в Telegram")
        ).to_be_visible()
        network.creators = [dict(BLOCKED)]
        card.get_by_role("button", name="Написал").click()
    else:
        network.creators = [dict(BLOCKED)]
        creator.click()

    expect(card.get_by_role("status")).to_have_text(
        "Эта карточка больше недоступна."
    )
    expect(card.get_by_role("link")).to_have_count(0)
    expect(card.get_by_role("button", name="Написал")).to_have_count(0)
    card.get_by_role("button", name="К списку").click()
    expect(
        listing.get_by_role("button", name="Ирина", exact=True)
    ).to_be_visible()
    expect(creator).to_have_count(0)
    assert not errors

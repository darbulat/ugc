"""Manager navigation and directory filtering in both Mini App hosts."""

from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import MiniAppNetwork, open_app

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


class ManagerDirectoryNetwork(MiniAppNetwork):
    def __init__(self):
        super().__init__()
        self.manager = True
        self.creators = [dict(ACTIVE), dict(BLOCKED)]

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
                if any(
                    query in creator[field].lower()
                    for field in ("name", "city")
                )
            ]
            route.fulfill(
                json={
                    "creators": creators,
                    "has_more": False,
                    "followup_count": due_count,
                }
            )
        elif path == f"{PATH}/{ACTIVE['creator_id']}/followup":
            self.creators[0].update(
                followup_due=False, remind_at="2026-11-18T12:00:00Z"
            )
            route.fulfill(json={"remind_at": self.creators[0]["remind_at"]})
        elif path == PATH + "/" + BLOCKED["creator_id"]:
            route.fulfill(
                json={
                    **BLOCKED,
                    "instagram_verified": True,
                    "links": [
                        {
                            "label": "YouTube",
                            "url": "https://www.youtube.com/@synthetic",
                        }
                    ],
                }
            )
        else:
            route.fulfill(status=404, json={"detail": "creator_not_found"})


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
    blocked = listing.get_by_role(
        "button", name="Ирина · Казань · Бот недоступен"
    )
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
    expect(search).to_have_value("  казань  ")
    expect(blocked).to_be_visible()
    expect(active).to_have_count(0)
    search.clear()
    status_filter.uncheck()
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
def test_manager_instagram_queue_filters_and_schedules_contact(page, platform):
    network = ManagerDirectoryNetwork()
    page.set_viewport_size({"width": 320, "height": 740})
    errors = open_app(page, network, platform, native=True)
    page.get_by_role("button", name="Менеджер", exact=True).click()
    page.get_by_role("button", name="Моя база креаторов").click()

    listing = page.locator("#screen-invited-creators")
    filters = listing.get_by_role("group", name="Подтверждение Instagram")
    filters.get_by_role("button", name="Подтверждены", exact=True).click()
    expect(
        listing.get_by_text("Instagram подтверждён", exact=True)
    ).to_be_visible()
    expect(listing.get_by_text("Нет контакта в Telegram")).to_be_visible()
    expect(
        listing.get_by_role("link", name="Написать в Telegram")
    ).to_have_count(0)

    unverified = filters.get_by_role(
        "button", name="Не подтверждены", exact=True
    )
    unverified.click()
    contact = listing.get_by_role("link", name="Написать в Telegram")
    expect(contact).to_have_attribute("href", ACTIVE["telegram_url"])
    contact.click()
    expected_call = "telegram-link" if platform == "telegram" else "link"
    assert [expected_call, ACTIVE["telegram_url"]] in page.evaluate(
        "window.__host.calls"
    )

    listing.get_by_role("button", name="Нужно связаться: 1").click()
    listing.get_by_role("button", name="Напомнить завтра").click()
    expect(
        listing.get_by_role("button", name="Нужно связаться: 0")
    ).to_be_visible()
    expect(listing.get_by_role("status")).to_have_text(
        "В этой группе пока никого нет."
    )
    unverified.click()
    expect(listing.get_by_text("Связаться после", exact=False)).to_be_visible()
    with page.expect_response(
        lambda response: response.url.endswith("/followup")
    ):
        listing.get_by_role("button", name="Написал", exact=True).click()
    assert any(
        path.endswith("/followup") and body.get("action") == "tomorrow"
        for path, body in network.requests
    )
    expect(listing.get_by_text("Связаться после", exact=False)).to_be_visible()
    assert any(
        path.endswith("/followup") and body.get("action") == "contacted"
        for path, body in network.requests
    )
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
        expect(listing.get_by_role("status")).to_contain_text("личной ссылкой")
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

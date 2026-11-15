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
}
BLOCKED = {
    "creator_id": "b1d4bc16-2955-4fda-a8d0-ddd9611b3618",
    "name": "Ирина",
    "city": "Казань",
    "status": "bot_blocked",
}


class ManagerDirectoryNetwork(MiniAppNetwork):
    def __init__(self):
        super().__init__()
        self.manager = True

    def route(self, route):
        path = urlparse(route.request.url).path.removeprefix("/miniapp/api")
        if not path.startswith(PATH):
            super().route(route)
            return
        body = route.request.post_data_json
        self.requests.append((path, body))
        if path == PATH:
            creators = (
                [BLOCKED] if body["bot_unavailable"] else [ACTIVE, BLOCKED]
            )
            query = body.get("q", "").lower()
            creators = [
                creator
                for creator in creators
                if any(
                    query in creator[field].lower()
                    for field in ("name", "city")
                )
            ]
            route.fulfill(json={"creators": creators, "has_more": False})
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
    page.get_by_role("button", name="Приглашённые креаторы").click()

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

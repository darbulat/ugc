"""Exercise manager and customer handoff controls on the local Mini App."""

from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import MiniAppNetwork, open_app

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]

ORDER = "1b1386a1-5bd4-4bbe-9ac0-de4b35c4b063"
ITEM = "2b1386a1-5bd4-4bbe-9ac0-de4b35c4b063"
INVITE = "3b1386a1-5bd4-4bbe-9ac0-de4b35c4b063"


class InviteNetwork(MiniAppNetwork):
    def __init__(self):
        super().__init__(registered=True)
        self.manager = True
        self.shared = False
        self.order = {
            "order_id": ORDER,
            "status": "active",
            "currency_symbol": "₽",
            "brand_name": "Тест приглашений",
            "price": 0,
        }

    def route(self, route):
        path = urlparse(route.request.url).path
        if path.endswith("/creator-invites"):
            payload = route.request.post_data_json
            self.requests.append((path, payload))
            response = {
                "positions": [{"ordinal": 3, "id": ITEM}],
                "invites": [],
            }
            operation = payload.get("operation")
            if operation == "lookup":
                response["availability"] = (
                    "ready" if payload["instagram"] == "@known" else "external"
                )
            elif operation == "send":
                response.update({"notice_state": "sent", "link": None})
            elif operation == "create":
                response["link"] = "https://t.me/test_bot?start=oi_test"
            route.fulfill(json=response)
        elif path.endswith("/selection"):
            route.fulfill(
                json={"order_id": ORDER, "positions": [], "waitlist_count": 0}
            )
        elif path.endswith("/invite-handoff"):
            payload = route.request.post_data_json
            self.requests.append((path, payload))
            action = payload["action"]
            if action in ("share", "hide"):
                self.shared = action == "share"
            if action == "open":
                route.fulfill(json={"contact": "@shared_creator"})
            elif action == "ack":
                route.fulfill(json={"acknowledged": True})
            else:
                route.fulfill(
                    json={
                        "enabled": self.shared,
                        "telegram": "@order_owner",
                        "staff": [
                            {"id": INVITE, "ordinal": 3, "accepted_at": None}
                        ],
                        "open_url": "https://t.me/test_bot?start=ir_test",
                    }
                )
        else:
            super().route(route)


def test_manager_action_follows_lookup_and_defaults_to_next_position(page):
    network = InviteNetwork()
    network.registered = False
    errors = open_app(page, network)
    page.get_by_role("button", name="Менеджер", exact=True).click()
    page.get_by_text("Тест приглашений", exact=True).click()
    page.get_by_role("button", name="Добавить креатора").click()
    form = page.locator("#mgr-invite-form")
    expect(form.locator("select[name=item_id]")).to_have_value("")
    expect(form.locator("select[name=item_id] option").first).to_have_text(
        "Первая свободная · №3"
    )
    form.locator("[name=instagram]").fill("@known")
    form.get_by_role("button", name="Проверить в базе").click()
    form.get_by_role("button", name="Отправить приглашение в бот").click()
    expect(
        page.get_by_text("Приглашение отправлено в Telegram.")
    ).to_be_visible()
    assert "item_id" not in network.requests[-1][1]
    expect(page.get_by_label("Ссылка для креатора")).to_be_hidden()

    form.locator("[name=telegram]").fill("@known_creator")
    form.get_by_role("button", name="Проверить в базе").click()
    form.locator("[name=consent_source]").select_option("telegram")
    form.get_by_role(
        "button", name="Сохранить контакт и получить ссылку"
    ).click()
    expect(page.get_by_text("Контакт сохранён.", exact=False)).to_be_visible()
    assert network.requests[-1][1]["operation"] == "create"
    form.locator("[name=consent_source]").select_option("")
    form.locator("[name=instagram]").fill("@external")
    form.get_by_role("button", name="Проверить в базе").click()
    form.get_by_role("button", name="Создать ссылку").click()
    expect(page.get_by_label("Ссылка для креатора")).to_have_value(
        "https://t.me/test_bot?start=oi_test"
    )
    assert not errors


def test_client_can_share_and_acknowledge_contact_without_leaving_miniapp(page):
    network = InviteNetwork()
    errors = open_app(page, network, query=f"?selection={ORDER}")
    page.get_by_role("button", name="Разрешить передачу моего Telegram").click()
    expect(
        page.get_by_text("Подтвердившие участие креаторы увидят @order_owner.")
    ).to_be_visible()
    page.get_by_role("button", name="Скрыть мой Telegram").click()
    expect(page.get_by_text("Ваш Telegram скрыт.")).to_be_visible()
    page.get_by_role("button", name="Контакт №3").click()
    expect(page.get_by_text("@shared_creator")).to_be_visible()
    page.get_by_role("button", name="Подтвердить получение контакта").click()
    expect(page.get_by_text("Получение подтверждено")).to_be_visible()
    expect(
        page.get_by_role("button", name="Подтвердить получение контакта")
    ).to_be_hidden()
    assert network.requests[-1][1]["invitation"] == INVITE
    assert not errors

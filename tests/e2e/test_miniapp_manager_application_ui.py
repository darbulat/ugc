"""Production manager form and API with synthetic storage and host."""

from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import open_app, screenshot
from tests.e2e.test_miniapp_partner_ui import SIGNED, PartnerNetwork
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.domain.manager_application import (
    missing_application_fields,
    validate_application_answer,
)
from ugc_bot.miniapp.manager_application_api import (
    create_manager_application_router,
)

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
ACTOR = UUID("10000000-0000-4000-8000-000000000002")


class ApplicationNetwork(PartnerNetwork):
    def __init__(self):
        super().__init__(role="unregistered")
        self.manager_app_enabled = True
        self.row = {
            "user_id": ACTOR,
            "state": "draft",
            "answers": {},
            "instagram_verified_at": None,
        }
        self.fail_answer = False
        self.saves = []

        async def resolve(request, init_data, *, platform):
            assert init_data == SIGNED and platform == "telegram"
            return AuthenticatedMessengerPrincipal(ACTOR, platform, "101")

        async def city(query):
            return "Казань", "Татарстан", "Россия"

        app = FastAPI()
        app.include_router(create_manager_application_router(resolve))
        app.state.config = SimpleNamespace(
            instagram=SimpleNamespace(admin_instagram_username="umc.test")
        )
        app.state.dispatcher = {
            "manager_applications": self,
            "blogger_registration_service": SimpleNamespace(
                resolve_city_identity=city
            ),
        }
        self.api = TestClient(app)

    async def open(self, user_id):
        assert user_id == ACTOR
        return self.row

    async def answer(self, user_id, field, value, *, location_context=None):
        assert user_id == ACTOR
        if self.fail_answer:
            raise HTTPException(503, "Synthetic temporary failure")
        value = validate_application_answer(field, value)
        self.saves.append((field, value))
        self.row["answers"][field] = value
        if location_context:
            self.row["answers"].update(
                location_region=location_context[0],
                location_country=location_context[1],
            )
        if not missing_application_fields(self.row["answers"]):
            self.row["state"] = "submitted"
        return self.row

    async def instagram_challenge(self, user_id):
        return "UMCM-000000000001"

    def route(self, route):
        path = urlparse(route.request.url).path
        if path.startswith("/miniapp/api/manager/application/"):
            body = route.request.post_data_json
            self.requests.append((path.removeprefix("/miniapp/api"), body))
            result = self.api.post(path.removeprefix("/miniapp/api"), json=body)
            route.fulfill(status=result.status_code, json=result.json())
            return
        super().route(route)


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("size", [(320, 568), (390, 667)])
def test_small_home_starts_with_visible_role_buttons(page, platform, size):
    network = ApplicationNetwork()
    page.set_viewport_size({"width": size[0], "height": size[1]})
    errors = open_app(page, network, platform, native=True, init_data=SIGNED)
    expect(page.locator("#screen-role-choice")).to_be_visible()
    for role in ("advertiser", "blogger"):
        expect(page.locator(f'[data-role="{role}"]')).to_be_in_viewport(ratio=1)
    roles = page.locator(".role-btns").bounding_box()
    partner = page.locator("#screen-role-choice [data-partner-home]")
    expect(partner).to_contain_text("Партнёрская программа")
    assert partner.bounding_box()["y"] >= roles["y"] + roles["height"]
    expect(page.locator("#role-choice-hint")).not_to_contain_text("чате")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot(page, f"roles-first-{platform}-{size[0]}")
    assert not errors


def test_native_application_saves_resumes_and_submits_without_bot_chat(page):
    network = ApplicationNetwork()
    page.set_viewport_size({"width": 320, "height": 568})
    page.add_init_script("""
        window.managerCopies = [];
        Object.defineProperty(navigator, 'clipboard', {value: {
          writeText(value) {
            window.managerCopies.push(value);
            return Promise.resolve();
          }
        }});
    """)
    errors = open_app(page, network, native=True, init_data=SIGNED)
    page.locator("#link-manager-application").click()
    screen = page.locator("#screen-manager-application")
    expect(screen).to_be_visible()
    answer = page.locator("#manager-answer")
    expect(answer).to_have_attribute("name", "name")
    answer.fill("Анна")
    page.evaluate("window.__host.wa.MainButton.click()")
    expect(answer).to_have_attribute("name", "rate")
    page.reload()
    page.locator("#link-manager-application").click()
    expect(answer).to_have_attribute("name", "rate")
    assert network.row["answers"]["name"] == "Анна"

    values = [
        ("rate", "1500–2000"),
        ("work_format", "Другое"),
        ("work_format_details", "Работаю самостоятельно"),
        ("weekly_capacity", "11–30"),
        ("location", "Казань"),
        ("phone", "+79991234567"),
        ("instagram", "native_candidate"),
        ("settlement", "Самозанятый"),
        ("case", "Организовала съёмку для бренда с десятью авторами."),
        (
            "shortfall_plan",
            "Найду авторов по геометкам и проверю их аудиторию.",
        ),
    ]
    for field, value in values:
        expect(answer).to_have_attribute("name", field)
        expect(answer).to_be_enabled()
        if field in {"work_format", "weekly_capacity", "settlement"}:
            answer.select_option(value)
        else:
            answer.fill(value)
        if field == "rate":
            network.fail_answer = True
            page.evaluate("window.__host.wa.MainButton.click()")
            expect(screen.get_by_role("alert")).to_contain_text(
                "Не удалось сохранить"
            )
            expect(answer).to_have_value(value)
            network.fail_answer = False
        page.evaluate("window.__host.wa.MainButton.click()")
        if field == "location":
            expect(screen).to_contain_text("Казань, Татарстан, Россия")
            page.get_by_role("button", name="Да, выбрать город").click()

    expect(screen).to_contain_text("Заявка получена")
    expect(page.locator("#manager-instagram-code")).to_have_value(
        "UMCM-000000000001"
    )
    expect(screen.get_by_role("link", name="Открыть Direct")).to_have_attribute(
        "href", "https://ig.me/m/umc.test"
    )
    screen.get_by_role("button", name="Скопировать код").click()
    expect(screen.get_by_role("status")).to_have_text("Код скопирован.")
    assert page.evaluate("window.managerCopies") == ["UMCM-000000000001"]
    assert network.row["state"] == "submitted"
    assert len(network.saves) == 11
    assert not any(
        call[0] == "telegram-link"
        for call in page.evaluate("window.__host.calls")
    )
    screenshot(page, "manager-native-submitted-small")
    page.evaluate("window.__host.wa.BackButton.click()")
    assert not page.locator("#manager-instagram-code").count()
    assert not errors


def test_application_clears_private_answers_when_signed_session_changes(page):
    network = ApplicationNetwork()
    network.row["answers"]["name"] = "Private name"
    errors = open_app(page, network, init_data=SIGNED)
    page.locator("#link-manager-application").click()
    expect(page.locator("#manager-answer")).to_have_attribute("name", "rate")
    page.get_by_role("button", name="Предыдущий вопрос").click()
    expect(page.locator("#manager-answer")).to_have_value("Private name")
    before = len(network.requests)
    page.evaluate("""() => {
      window.__host.wa.initData = 'changed-session';
      document.dispatchEvent(new Event('visibilitychange'));
    }""")
    expect(page.locator("#screen-manager-application")).to_contain_text(
        "Сессия изменилась"
    )
    assert not page.locator("#manager-answer").count()
    assert len(network.requests) == before
    assert not errors

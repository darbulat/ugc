"""Manager review UI using real admin routes and a synthetic application."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import expect
from starlette.middleware.sessions import SessionMiddleware

from tests.admin.test_manager_onboarding_routes import StubAdminSession
from ugc_bot.admin.app import _build_templates
from ugc_bot.admin.managers import register_managers
from ugc_bot.domain.manager_application import application_version

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(45)]


def test_manager_card_actions_and_feedback(page, monkeypatch):
    user_id = uuid4()
    submitted_at = datetime(2026, 11, 18, tzinfo=UTC)
    row = dict(
        user_id=user_id,
        state="submitted",
        submitted_at=submitted_at,
        telegram="synthetic_manager",
        instagram_verified_at=None,
        decision_note="",
        answers={"name": "Анна Соколова", "instagram": "synthetic_manager"},
    )

    class ManagerSession(StubAdminSession):
        def execute(self, _statement):
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(one_or_none=lambda: row)
            )

    review = Mock(
        side_effect=ValueError("Анкета изменилась. Проверьте данные.")
    )
    monkeypatch.setattr("ugc_bot.admin.managers.Session", ManagerSession)
    monkeypatch.setattr(
        "ugc_bot.admin.managers.review_manager_application", review
    )
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="synthetic-secret")
    templates = _build_templates(app, ZoneInfo("Europe/Moscow"))
    templates.env.globals["admin_action_token"] = lambda request: "synthetic"
    auth = SimpleNamespace(authenticate=AsyncMock(return_value=True))
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    register_managers(app, auth, engine, templates, AsyncMock())
    client = TestClient(app, follow_redirects=False)
    base = "http://manager-card.test"

    def bridge(route):
        request = route.request
        if not request.url.startswith(base + "/"):
            route.abort()
            return
        response = client.request(
            request.method,
            request.url,
            headers=dict(request.headers),
            content=request.post_data,
            follow_redirects=request.method == "POST",
        )
        route.fulfill(
            status=response.status_code,
            headers=dict(response.headers),
            body=response.content,
        )

    page.route("**/*", bridge)
    page.goto(f"{base}/admin/managers/{user_id}")
    page.evaluate("document.fonts.ready")
    assert page.evaluate(
        """[...document.fonts].some(
            font => font.family.includes('IBM Plex Sans')
                && font.status === 'loaded'
        )"""
    )
    approve = page.get_by_role("button", name="Принять менеджера")
    note = page.get_by_role("textbox", name="Внутренняя заметка")
    expect(approve).to_be_disabled()
    expect(approve).to_have_accessible_description(
        "Принятие доступно после подтверждения Instagram."
    )
    expect(note).to_have_accessible_description("До 300 символов")
    expect(note).to_have_attribute("maxlength", "300")
    for width in (1440, 390, 320):
        page.set_viewport_size({"width": width, "height": 844})
        assert page.evaluate(
            "document.documentElement.scrollWidth == innerWidth"
        )
        assert approve.bounding_box()["height"] >= 44

    save = page.get_by_role("button", name="Сохранить заметку")
    note.fill("Проверить рекомендации.")
    note.press("Tab")
    expect(save).to_be_focused()
    save.press("Enter")
    expect(page.get_by_role("alert")).to_have_text(
        "Анкета изменилась. Проверьте данные."
    )
    assert review.call_args.args[1:] == (
        user_id,
        "note",
        "Проверить рекомендации.",
    )
    assert review.call_args.kwargs == {
        "version": application_version(submitted_at)
    }

    review.side_effect = None
    row["instagram_verified_at"] = submitted_at
    save.click()
    expect(page.get_by_role("status")).to_have_text("Изменение сохранено.")
    expect(page.get_by_role("alert")).to_have_count(0)
    expect(approve).to_be_enabled()

"""Admin review and Telegram Mini App authorization for manager onboarding."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from ugc_bot.admin import creator_invites, managers
from ugc_bot.miniapp import manager_invites


class StubAdminSession:
    def __init__(self, engine):
        self.engine = engine

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def begin(self):
        return self

    def get_bind(self):
        return self.engine


def test_review_actions_require_admin_and_csrf(monkeypatch):
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="synthetic-secret")
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    auth = SimpleNamespace(authenticate=AsyncMock(return_value=False))
    templates = SimpleNamespace(
        TemplateResponse=lambda _request, _name, data, headers: JSONResponse(
            {"message": data["message"], "has_more": data["has_more"]},
            headers=headers,
        )
    )

    async def require_token(request):
        if request.headers.get("X-Test-CSRF") != "valid":
            raise HTTPException(403)

    directory = Mock(return_value=[{}] * 31)
    review = Mock(return_value="Изменение сохранено.")
    monkeypatch.setattr(managers, "Session", StubAdminSession)
    monkeypatch.setattr(managers, "_directory", directory)
    monkeypatch.setattr(managers, "_review", review)
    managers.register_managers(app, auth, engine, templates, require_token)
    client = TestClient(app, follow_redirects=False)
    url = "/admin/managers"
    valid = {"X-Test-CSRF": "valid"}
    uid = str(uuid4())
    decision = {"command": "approved", "identity": uid, "note": "  Проверено  "}
    assert client.get(url).status_code in {302, 303, 307}
    assert client.post(url, data=decision).status_code in {302, 303, 307}
    auth.authenticate.return_value = True
    engine.dialect.name = "sqlite"
    assert client.get(url).status_code == 503
    assert client.post(url, data=decision).status_code == 503
    engine.dialect.name = "postgresql"
    assert client.post(url, data=decision).status_code == 403
    assert (
        client.post(url, data={"command": "invalid"}, headers=valid).status_code
        == 422
    )
    assert (
        client.post(
            url, data=decision | {"note": "x" * 301}, headers=valid
        ).status_code
        == 422
    )
    review.assert_not_called()

    response = client.post(url, data=decision, headers=valid)
    assert response.status_code == 303
    review.assert_called_once()
    assert review.call_args.args[1:] == ("approved", uid, "Проверено")
    response = client.get(
        url, params={"q": " @name ", "status": "submitted", "page": 2}
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "message": "Изменение сохранено.",
        "has_more": True,
    }
    assert directory.call_args.args[1:] == ("@name", "submitted", 30)
    assert client.get(url).json()["message"] is None

    review.side_effect = ValueError("Кандидату нужно подтвердить Instagram.")
    assert client.post(url, data=decision, headers=valid).status_code == 303
    assert "подтвердить Instagram" in client.get(url).json()["message"]


def test_manager_invite_remains_private_to_assigned_telegram_manager(
    monkeypatch,
):
    app = FastAPI()
    router = APIRouter()
    actor, order, item = uuid4(), uuid4(), uuid4()
    auth = AsyncMock(return_value=actor)
    engine = object()
    app.state.dispatcher = {
        "container": SimpleNamespace(get_admin_engine=lambda: engine)
    }
    app.state.config = SimpleNamespace(
        bot=SimpleNamespace(bot_username="@example_bot"),
        db=SimpleNamespace(database_url="postgresql://example"),
        financial=SimpleNamespace(core_enabled=True),
        order=SimpleNamespace(customer_workflows_enabled=False),
    )
    expected = {
        "positions": [],
        "link": "https://t.me/example_bot?start=oi_test",
        "invites": [],
    }
    load = Mock(return_value=expected)
    monkeypatch.setattr(manager_invites, "manager_invite_data", load)
    manager_invites.register_manager_invites(router, auth)
    app.include_router(router)
    client = TestClient(app)
    url = f"/manager/orders/{order}/creator-invites"
    payload = {
        "init_data": "signed data",
        "item_id": str(item),
        "instagram": "@external",
    }
    assert client.post(url, json=payload).status_code == 503
    app.state.config.order.customer_workflows_enabled = True
    assert (
        client.post(
            url, json=payload | {"consent_source": "unknown"}
        ).status_code
        == 422
    )
    load.assert_not_called()
    result = client.post(url, json=payload)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json() == expected
    assert auth.call_args.args[1] == "signed data"
    assert auth.call_args.kwargs == {"platform": "telegram"}
    args = load.call_args.args
    assert args[:3] == (engine, actor, order)
    assert args[3].item_id == item
    assert args[4] == "example_bot"

    load.side_effect = PermissionError
    assert client.post(url, json=payload).status_code == 403
    load.side_effect = ValueError("Позиция занята.")
    assert client.post(url, json=payload).json()["detail"] == "Позиция занята."


def test_admin_creator_invite_reports_form_errors_and_checks_order(monkeypatch):
    app = FastAPI()
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    auth = SimpleNamespace(authenticate=AsyncMock(return_value=True))
    csrf = AsyncMock()
    config = SimpleNamespace(
        bot=SimpleNamespace(bot_username="example_bot"),
        financial=SimpleNamespace(core_enabled=True),
        order=SimpleNamespace(customer_workflows_enabled=False),
    )
    order_for_invite = Mock(return_value=None)
    monkeypatch.setattr(creator_invites, "Session", StubAdminSession)
    monkeypatch.setattr(creator_invites, "order_for_invite", order_for_invite)
    creator_invites.register_creator_invites(
        app, auth, engine, None, csrf, config
    )
    client = TestClient(app)
    order = uuid4()
    url = f"/admin/orders/{order}/creator-invites"
    fields = {
        "item_id": str(uuid4()),
        "manager_id": str(uuid4()),
        "instagram": "@creator",
        "telegram": "@external",
        "creator_name": "Мурат",
        "record_consent": "1",
        "operation": "create",
    }
    assert client.post(url, data=fields).status_code == 503
    csrf.assert_awaited_once()
    config.order.customer_workflows_enabled = True
    assert client.post(url, data=fields).status_code == 422
    assert (
        client.post(url, data=fields | {"item_id": "invalid"}).status_code
        == 422
    )
    order_for_invite.assert_not_called()
    response = client.post(url, data=fields | {"consent_source": "instagram"})
    assert response.status_code == 404
    assert "активный оплаченный заказ" in response.json()["detail"]
    assert order_for_invite.call_args.args[1] == order
    assert (
        client.get(
            url, params={"instagram": "@creator", "telegram": "@external"}
        ).status_code
        == 404
    )
    engine.dialect.name = "sqlite"
    order_for_invite.reset_mock()
    assert client.get(url).status_code == 404
    order_for_invite.assert_not_called()

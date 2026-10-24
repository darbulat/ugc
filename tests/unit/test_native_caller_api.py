"""Four signed routes: synthetic HMAC, memory state and private errors."""

from dataclasses import asdict, replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from tests.application.services.test_native_collaboration import (
    setup as work_setup,
)
from tests.application.services.test_native_intake import (
    ready as intake_ready,
)
from tests.application.services.test_native_intake import (
    setup as intake_setup,
)
from tests.e2e.miniapp_helpers import generate_init_data
from tests.unit.test_financial_native_principal import Roles
from ugc_bot.miniapp.collaboration_api import create_collaboration_router
from ugc_bot.miniapp.financial_principal import resolve_financial_principal
from ugc_bot.miniapp.order_intake_api import create_order_intake_router


def application(platform, kind, *, resolver=None, bound=False):
    if kind == "intake":
        service, facts, command, principal = (
            intake_ready if bound else intake_setup
        )(platform)
        if bound:
            facts.client = replace(
                facts.client, telegram_id="123", max_id="123"
            )
        uid = command.client_id
        path = "/financial/orders"
        body = asdict(command)
        body.pop("client_id")
        body.update(
            honorarium=str(command.honorarium),
            selection_due_at=command.selection_due_at.isoformat(),
            accompaniment_ordinals=[],
        )
        paths = ((path + "/policies", {}), (path, body))
    else:
        service, facts, scope, command, principal, _ = work_setup(platform)
        if bound:
            facts.actors[principal.user_id] = replace(
                facts.actors[principal.user_id], telegram_id="123", max_id="123"
            )
        uid = principal.user_id
        path = f"/collaborations/{scope.assignment_id}"
        paths = (
            (path + "/status", {}),
            (
                path + "/command",
                dict(
                    action="assign",
                    operation_key="native",
                    expected_version=0,
                    due_at=command.due_at.isoformat(),
                    terms_reference="synthetic terms",
                ),
            ),
        )
    roles = Roles(
        SimpleNamespace(
            user_id=uid, telegram_id="123", max_id="123", country=None
        )
    )
    app = FastAPI()
    app.include_router(
        (
            create_order_intake_router
            if kind == "intake"
            else create_collaboration_router
        )(resolver or resolve_financial_principal)
    )
    app.state.config = SimpleNamespace(
        bot=SimpleNamespace(bot_token="synthetic-tg"),
        max_bot=SimpleNamespace(token="synthetic-max"),
        financial=SimpleNamespace(core_enabled=True),
    )
    app.state.dispatcher = dict(
        user_role_service=roles,
        order_intake_service=service,
        collaboration_service=service,
        transaction_manager=facts,
    )
    auth = dict(
        platform=platform,
        init_data=generate_init_data(
            "synthetic-tg" if platform == "telegram" else "synthetic-max",
            123,
            "Synthetic",
        ),
    )
    return app, facts, auth, paths


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("kind", ["intake", "work"])
async def test_each_native_signed_route_denies_changed_binding(platform, kind):
    app, facts, auth, paths = application(platform, kind)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        for path, body in paths:
            response = await client.post(path, json=auth | body)
            assert response.status_code == 403, response.text
            assert response.json() == {"detail": "financial_principal_changed"}
            assert response.headers["cache-control"] == "no-store"
    if kind == "work":
        assert not facts.events and not facts.outbox
    else:
        assert facts.calls == ["client", "client"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["intake", "work"])
async def test_native_http_requires_typed_proof(kind):
    async def legacy(*args, **kwargs):
        return uuid4()

    app, _, auth, paths = application("telegram", kind, resolver=legacy)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        for path, body in paths:
            response = await client.post(path, json=auth | body)
            assert response.status_code == 401
            assert response.json() == {"detail": "financial_session_invalid"}
            assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["intake", "work"])
@pytest.mark.parametrize(
    "exception", [ValueError, PermissionError, RuntimeError, HTTPException]
)
async def test_native_context_errors_are_constant_and_uncacheable(
    kind, exception, caplog
):
    private = "SYNTHETIC_PRIVATE_NATIVE_FAILURE"

    async def broken(*args, **kwargs):
        raise (
            exception(400, private)
            if exception is HTTPException
            else exception(private)
        )

    app, _, auth, paths = application("telegram", kind, resolver=broken)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        for path, body in paths:
            response = await client.post(path, json=auth | body)
            assert response.status_code == 503
            assert response.json() == {
                "detail": "intake_unavailable"
                if kind == "intake"
                else "collaboration_unavailable"
            }
            assert response.headers["cache-control"] == "no-store"
            assert private not in response.text + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["intake", "work"])
async def test_native_validation_never_echoes_input(kind):
    app, _, auth, paths = application("telegram", kind)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        for path, body in paths:
            response = await client.post(
                path,
                json=auth | body | {"system_actor": "SYNTHETIC_PRIVATE_BODY"},
            )
            assert response.status_code == 422
            assert response.json() == {
                "detail": "intake_request_invalid"
                if kind == "intake"
                else "collaboration_request_invalid"
            }
            assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("kind", ["intake", "work"])
async def test_native_unknown_actor_creates_nothing(platform, kind):
    app, _, auth, paths = application(platform, kind)
    roles = app.state.dispatcher["user_role_service"]
    roles.user = None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        for path, body in paths:
            response = await client.post(path, json=auth | body)
            assert response.status_code == 404
            assert response.json() == {
                "detail": "existing_financial_account_required"
            }
            assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("kind", ["intake", "work"])
async def test_current_native_routes_succeed_without_country_fill(
    platform, kind
):
    app, facts, auth, paths = application(platform, kind, bound=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        for path, body in reversed(paths):
            response = await client.post(path, json=auth | body)
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "no-store"
    assert app.state.dispatcher["user_role_service"].user.country is None
    if kind == "work":
        assert len(facts.events) == 1
    else:
        assert len(facts.orders) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["intake", "work"])
@pytest.mark.parametrize(
    "stage", ["service", "construct", "response", "serialize"]
)
async def test_native_all_execution_stages_sanitize_private_failure(
    kind, stage, monkeypatch, caplog
):
    import ugc_bot.miniapp.collaboration_api as work_api
    import ugc_bot.miniapp.order_intake_api as intake_api

    app, _, auth, paths = application("telegram", kind, bound=True)
    private = "SYNTHETIC_PRIVATE_EXECUTION"

    def fail(*args, **kwargs):
        raise ValueError(private)

    async def fail_async(*args, **kwargs):
        fail()

    if stage == "service":
        service = app.state.dispatcher[
            "order_intake_service"
            if kind == "intake"
            else "collaboration_service"
        ]
        monkeypatch.setattr(
            service,
            "create" if kind == "intake" else "execute_authenticated",
            fail_async,
        )
    elif stage == "construct":
        monkeypatch.setattr(
            intake_api if kind == "intake" else work_api,
            "OrderIntakeCommand"
            if kind == "intake"
            else "CollaborationCommand",
            fail,
        )
    elif stage == "serialize":

        def invalid_response(*args, **kwargs):
            return {"private": private}

        if kind == "intake":
            monkeypatch.setattr(
                intake_api, "OrderIntakeResponse", invalid_response
            )
        else:
            monkeypatch.setattr(
                work_api.WorkResponse, "from_record", invalid_response
            )
    elif kind == "intake":
        monkeypatch.setattr(intake_api, "OrderIntakeResponse", fail)
    else:
        monkeypatch.setattr(work_api.WorkResponse, "from_record", fail)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        path, body = paths[1]
        response = await client.post(path, json=auth | body)
    assert response.status_code == 503
    assert response.json() == {
        "detail": "intake_unavailable"
        if kind == "intake"
        else "collaboration_unavailable"
    }
    assert response.headers["cache-control"] == "no-store"
    assert private not in response.text + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,method",
    [("intake", "eligible_policies"), ("work", "get_authenticated")],
)
@pytest.mark.parametrize(
    "code,status",
    [
        ("idempotency_payload_conflict", 409),
        ("financial_principal_changed", 403),
        ("collaboration_private_failure", 503),
        ("intake_private_failure", 503),
    ],
)
async def test_native_error_allowlist_is_exact(kind, method, code, status):
    app, _, auth, paths = application("telegram", kind)

    async def fail(*args, **kwargs):
        raise ValueError(code)

    setattr(
        app.state.dispatcher[
            "order_intake_service"
            if kind == "intake"
            else "collaboration_service"
        ],
        method,
        fail,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(paths[0][0], json=auth)
    assert response.status_code == status
    assert response.json() == {
        "detail": code
        if status != 503
        else "intake_unavailable"
        if kind == "intake"
        else "collaboration_unavailable"
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["intake", "work"])
async def test_native_query_and_unavailable_context_are_constant(kind):
    app, _, auth, paths = application("telegram", kind)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        for path, body in paths:
            response = await client.post(
                path + "?private=SECRET", json=auth | body
            )
            assert response.status_code == 422
            assert response.json() == {
                "detail": "intake_request_invalid"
                if kind == "intake"
                else "collaboration_request_invalid"
            }
            del app.state.dispatcher[
                "order_intake_service"
                if kind == "intake"
                else "collaboration_service"
            ]
            response = await client.post(path, json=auth | body)
            assert response.status_code == 503
            assert response.headers["cache-control"] == "no-store"
            app.state.dispatcher[
                "order_intake_service"
                if kind == "intake"
                else "collaboration_service"
            ] = None


@pytest.mark.asyncio
async def test_max_missing_country_is_unpublished_without_identity_writes():
    app, facts, auth, paths = application("max", "intake", bound=True)
    facts.client = replace(facts.client, currency="")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        policies = await client.post(paths[0][0], json=auth)
        assert policies.status_code == 200
        assert policies.json() == {
            "currency": "",
            "writes_paused": False,
            "policies": [],
        }
        created = await client.post(paths[1][0], json=auth | paths[1][1])
        assert created.status_code == 400
        assert created.json() == {"detail": "unpublished_currency"}
    assert (
        not facts.orders
        and not facts.quotes
        and not facts.leads
        and not facts.receipt
    )
    assert app.state.dispatcher["user_role_service"].user.country is None


@pytest.mark.asyncio
async def test_work_absent_status_and_missing_work_command_keep_status_codes():
    app, facts, auth, paths = application("telegram", "work", bound=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        status = await client.post(paths[0][0], json=auth)
        assert status.status_code == 404
        assert status.json() == {"detail": "collaboration_not_found"}
        body = paths[1][1] | {"action": "start"}
        command = await client.post(paths[1][0], json=auth | body)
        assert command.status_code == 409
        assert command.json() == {"detail": "collaboration_not_found"}
    assert not facts.records and not facts.events


@pytest.mark.asyncio
async def test_intake_duplicate_positions_have_constant_validation_response():
    app, facts, auth, paths = application("telegram", "intake", bound=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            paths[1][0],
            json=auth
            | paths[1][1]
            | {
                "service_mode": "with_manager",
                "accompaniment_ordinals": [1, 1],
            },
        )
    assert response.status_code == 422
    assert response.json() == {"detail": "intake_request_invalid"}
    assert response.headers["cache-control"] == "no-store"
    assert not facts.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["intake", "work"])
@pytest.mark.parametrize("route_index", [0, 1])
@pytest.mark.parametrize(
    "case,injected_status",
    [
        ("native", 200),
        ("native", 418),
        ("native", 500),
        ("native", 403),
        ("request_invalid", 200),
        ("request_invalid", 418),
        ("request_invalid", 500),
    ],
)
async def test_native_http_known_codes_use_explicit_status_pairs(
    kind, route_index, case, injected_status
):
    """Recognized detail cannot grant an arbitrary successful/error status."""
    prefix = "intake" if kind == "intake" else "collaboration"
    code = (
        "financial_principal_changed"
        if case == "native"
        else f"{prefix}_request_invalid"
    )

    async def fail(*args, **kwargs):
        raise HTTPException(injected_status, code)

    app, _, auth, paths = application("telegram", kind, resolver=fail)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        path, body = paths[route_index]
        response = await client.post(path, json=auth | body)
        assert response.status_code == (403 if case == "native" else 422)
        assert response.json() == {"detail": code}
        assert response.headers["cache-control"] == "no-store"

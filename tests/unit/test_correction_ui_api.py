"""Signed correction UI ingress over real authority and synthetic facts."""

import importlib
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.correction_commands import HASH, NOW, Proofs, Repository, U
from ugc_bot.application.correction_ports import CorrectionScope
from ugc_bot.application.services.correction_service import CorrectionService


class ReadRepository(Repository):
    async def order_positions(self, order_id, *, session):
        assert order_id == U[3]
        return (
            await self.orders_page(U[0], limit=20, after=None, session=session)
        )[0]["items"]

    async def discover_case_scope(self, actor_id, case_id, *, session):
        if case_id is None:
            return CorrectionScope(
                actor_id=actor_id,
                prospective_user_ids=(actor_id,),
                wallet_user_ids=(),
                source_hash=None,
                unavailable_reason="correction_order_missing",
            )
        return await super().discover_case_scope(
            actor_id, case_id, session=session
        )

    async def discover_preview(
        self, actor_id, order_id, paid_item_ids, *, existing_case_id, session
    ):
        assert order_id == U[3] and paid_item_ids == (U[5],)
        assert session is self.session
        return replace(
            self.scope,
            actor_id=actor_id,
            case_id=existing_case_id,
            selected_paid_item_ids=paid_item_ids,
        )

    async def cases_page(self, actor_id, *, admin, limit, after, session):
        assert session is self.session
        rows = []
        for row in sorted(self.rows["cases"], key=lambda c: c["case_id"]):
            if after is not None and row["case_id"] <= after:
                continue
            if not admin and row["client_id"] != actor_id:
                continue
            requests = [
                r
                for r in self.rows["requests"]
                if r["case_id"] == row["case_id"]
            ]
            rows.append(row | dict(request=requests[0] if requests else None))
        return rows[: limit + 1]

    async def orders_page(self, actor_id, *, limit, after, session):
        assert session is self.session
        if actor_id != U[0] or (after and after >= U[3]):
            return []
        return [
            dict(
                order_id=U[3],
                title="Synthetic owned order",
                items=[
                    dict(
                        paid_item_id=U[5],
                        ordinal=1,
                        selection_state="paid",
                        selection_due_at=NOW,
                    )
                ],
            )
        ]


def application(actor=0, platform="telegram", *, enabled=True):
    module = importlib.import_module("ugc_bot.miniapp.correction_api")
    views = importlib.import_module(
        "ugc_bot.application.services.correction_view_service"
    )
    repo, proofs = ReadRepository(), Proofs()
    clock = SimpleNamespace(now=lambda: NOW)
    service = CorrectionService(repo, proofs, clock)
    financial = SimpleNamespace(core_enabled=enabled)
    reader = views.CorrectionViewService(repo, service, clock, financial)

    @asynccontextmanager
    async def transaction():
        yield repo.session

    class Roles:
        async def get_user(self, external_id, messenger):
            key = "telegram_id" if messenger.value == "telegram" else "max_id"
            return next(
                (
                    SimpleNamespace(**row)
                    for row in repo.actors.values()
                    if row[key] == external_id
                ),
                None,
            )

    config = SimpleNamespace(
        financial=financial,
        bot=SimpleNamespace(bot_token="synthetic-telegram-token"),
        max_bot=SimpleNamespace(token="synthetic-max-token"),
    )
    app = FastAPI()
    app.state.config = config
    app.state.dispatcher = dict(
        correction_service=service,
        correction_view_service=reader,
        transaction_manager=SimpleNamespace(transaction=transaction),
        user_role_service=Roles(),
    )
    from ugc_bot.miniapp.financial_principal import resolve_financial_principal

    app.include_router(
        module.create_correction_router(resolve_financial_principal),
        prefix="/miniapp/api",
    )
    auth = dict(
        platform=platform,
        init_data=generate_init_data(
            "synthetic-telegram-token"
            if platform == "telegram"
            else "synthetic-max-token",
            int(
                repo.actors[U[actor]][
                    "telegram_id" if platform == "telegram" else "max_id"
                ]
            ),
            "Synthetic",
        ),
    )
    return app, repo, auth


def auth_for(repo, actor, platform="telegram"):
    return dict(
        platform=platform,
        init_data=generate_init_data(
            "synthetic-telegram-token"
            if platform == "telegram"
            else "synthetic-max-token",
            int(
                repo.actors[U[actor]][
                    "telegram_id" if platform == "telegram" else "max_id"
                ]
            ),
            "Synthetic",
        ),
    )


async def request_ui(app, auth, **changes):
    values = dict(
        operation_key="ui-request",
        reason="Actual own request",
        order_id=str(U[3]),
        paid_item_ids=[str(U[5])],
        expected_source_hash=HASH,
    )
    response = await post(app, auth, "request", **(values | changes))
    assert response.status_code == 200, response.text
    return response.json()


async def review_ui(app, auth, state, **changes):
    values = dict(
        operation_key="ui-review",
        reason="PRIVATE ADMIN REASON",
        case_id=state["case_id"],
        expected_version=state["version"],
        expected_source_hash=state["source_hash"],
        decision="approve",
        evidence_reference="PRIVATE ADMIN EVIDENCE",
        evidence_hash=HASH,
    )
    return await post(app, auth, "admin/review", **(values | changes))


async def observe_ui(app, auth, state=None, **changes):
    values = dict(
        operation_key="ui-observe",
        reason="PRIVATE BANK REASON",
        case_id=state["case_id"] if state else None,
        known_order_id=str(U[3]),
        known_capture_intent_id=str(U[4]),
        original_payment_reference="synthetic-payment",
        bank_account_label="synthetic-bank",
        bank_reference="PRIVATE BANK REFERENCE",
        amount_minor="50000",
        currency="RUB",
        occurred_at=NOW.isoformat(),
        reported_component="selection",
        evidence_reference="PRIVATE BANK EVIDENCE",
        evidence_hash=HASH,
        expected_version=state["version"] if state else None,
    )
    return await post(app, auth, "admin/observation", **(values | changes))


async def post(app, auth, path, **values):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.post(
            "/miniapp/api/financial/corrections/" + path,
            json=auth | values,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_signed_preview_is_exact_without_creating_command(platform):
    app, repo, auth = application(platform=platform)
    response = await post(
        app,
        auth,
        "preview",
        order_id=str(U[3]),
        paid_item_ids=[str(U[5])],
    )
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["total_minor"] == "50000"
    assert value["components"][0]["gross_minor"] == "50000"
    assert value["source_hash"] == HASH and value["can_request"]
    assert value["can_approve"] is False
    assert not repo.rows["commands"] and not repo.rows["cases"]
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_ui_receipt_and_current_state_are_separate():
    app, repo, auth = application()
    result = await post(
        app,
        auth,
        "request",
        operation_key="ui-request",
        reason="Actual own request",
        order_id=str(U[3]),
        paid_item_ids=[str(U[5])],
        expected_source_hash=HASH,
    )
    assert result.status_code == 200, result.text
    receipt = result.json()
    status = await post(
        app, auth, "operations/status", operation_key="ui-request"
    )
    assert status.status_code == 200, status.text
    assert status.json()["original_result"] == receipt
    assert status.json()["current"]["version"] == 1
    assert len(repo.rows["commands"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_complete_ui_evidence_flow_never_claims_money_applied(platform):
    app, repo, own = application(platform=platform)
    admin = auth_for(repo, 1, platform)
    requested = await request_ui(app, own)
    approved_reply = await review_ui(app, admin, requested)
    assert approved_reply.status_code == 200, approved_reply.text
    approved = approved_reply.json()
    observed_reply = await observe_ui(app, admin, approved)
    assert observed_reply.status_code == 200, observed_reply.text
    observed = observed_reply.json()
    result = await post(
        app,
        admin,
        "admin/match",
        operation_key="ui-match",
        reason="PRIVATE MATCH REASON",
        case_id=requested["case_id"],
        intent_id=approved["intent_id"],
        observation_id=observed["observation_id"],
        expected_version=observed["version"],
        expected_source_hash=observed["source_hash"],
        evidence_reference="PRIVATE MATCH EVIDENCE",
        evidence_hash=HASH,
    )
    assert result.status_code == 200, result.text
    assert result.json()["application_status"] == "awaiting_assessment"
    assert result.json()["applied"] is False
    assert len(repo.rows["matches"]) == 1
    detail = await post(app, own, requested["case_id"] + "/detail")
    assert detail.status_code == 200, detail.text
    assert detail.json()["current"]["version"] == 4
    assert "PRIVATE" not in detail.text
    assert "observations" not in detail.json()
    private = await post(app, admin, requested["case_id"] + "/detail")
    assert private.status_code == 200, private.text
    assert private.json()["total_minor"] == "50000"
    assert private.json()["observations"][0]["amount_minor"] == "50000"
    assert private.json()["intents"][0]["intent_id"] == approved["intent_id"]
    assert "PRIVATE BANK EVIDENCE" in private.text
    assert private.json()["allowed_actions"] == [
        "record_observation",
        "review",
        "match",
    ]
    status = await post(
        app, own, "operations/status", operation_key="ui-request"
    )
    assert status.json()["original_result"] == requested
    assert status.json()["current"]["version"] == 4


@pytest.mark.asyncio
async def test_context_orders_lists_and_exact_case_preview():
    app, repo, own = application()
    admin = auth_for(repo, 1)
    context = await post(app, own, "context")
    assert context.status_code == 200 and context.json()["admin"] is False
    assert context.json()["capabilities"]["record_observation"] is False
    orders = await post(app, own, "orders")
    assert orders.json()["entries"][0]["items"][0]["paid_item_id"] == str(U[5])
    requested = await request_ui(app, own)
    entries = await post(app, own, "list")
    assert entries.json()["entries"][0]["case_id"] == requested["case_id"]
    assert entries.json()["entries"][0]["total_minor"] == "50000"
    queue = await post(app, admin, "admin/queue")
    assert queue.status_code == 200 and len(queue.json()["entries"]) == 1
    preview = await post(
        app,
        admin,
        "preview",
        order_id=str(U[3]),
        paid_item_ids=[str(U[5])],
        existing_case_id=requested["case_id"],
    )
    assert preview.json()["can_approve"] is True
    assert preview.json()["can_request"] is False
    absent = await post(
        app, own, "operations/status", operation_key="never-sent"
    )
    assert absent.json() == {
        "recorded": False,
        "original_result": None,
        "current": None,
    }


@pytest.mark.asyncio
async def test_core_pause_keeps_actual_manual_fact_and_protected_reads():
    app, repo, own = application(enabled=False)
    admin = auth_for(repo, 1)
    context = await post(app, admin, "context")
    assert context.json()["writes_paused"] is True
    assert context.json()["capabilities"]["record_observation"] is True
    preview = await post(
        app, own, "preview", order_id=str(U[3]), paid_item_ids=[str(U[5])]
    )
    assert preview.json()["can_request"] is False
    assert preview.json()["blockers"] == ["financial_corrections_disabled"]
    refused = await post(
        app,
        own,
        "request",
        operation_key="paused-request",
        reason="request",
        order_id=str(U[3]),
        paid_item_ids=[str(U[5])],
        expected_source_hash=HASH,
    )
    assert refused.status_code == 503
    report = await observe_ui(app, admin, amount_minor="-9223372036854775808")
    assert report.status_code == 200, report.text
    assert report.json()["applied"] is False
    assert len(repo.rows["observations"]) == 1
    assert repo.rows["observations"][0]["amount_minor"] == -9223372036854775808
    detail = await post(app, admin, report.json()["case_id"] + "/detail")
    assert (
        detail.json()["observations"][0]["amount_minor"]
        == "-9223372036854775808"
    )
    assert detail.json()["allowed_actions"] == ["record_observation"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value", [1, True, 1.25, "01", "-0", "+1", "1.0", " 1", "9" * 20]
)
async def test_observation_rejects_inexact_numeric_or_noncanonical_wire(value):
    app, repo, admin = application(actor=1)
    response = await observe_ui(app, admin, amount_minor=value)
    assert response.status_code == 422, response.text
    assert response.json() == {"detail": "correction_request_invalid"}
    assert response.headers["cache-control"] == "no-store"
    assert not repo.rows["observations"] and not repo.rows["commands"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value", [None, "0", "9007199254740993", "9223372036854775807"]
)
async def test_observation_keeps_exact_unknown_or_large_reported_amount(value):
    app, repo, admin = application(actor=1)
    response = await observe_ui(app, admin, amount_minor=value, currency=None)
    assert response.status_code == 200, response.text
    stored = repo.rows["observations"][0]["amount_minor"]
    assert stored is None if value is None else str(stored) == value
    assert response.json()["applied"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "kind", ["wrong_token", "unknown", "query", "selector"]
)
async def test_forged_identity_has_no_private_echo(platform, kind):
    app, repo, auth = application(platform=platform)
    path = "context"
    values = {}
    if kind == "wrong_token":
        auth["init_data"] = generate_init_data("wrong", 101, "PRIVATE")
    elif kind == "unknown":
        repo.actors.clear()
    elif kind == "query":
        path += "?admin=true"
    else:
        values["actor_id"] = "PRIVATE_SELECTOR"
    response = await post(app, auth, path, **values)
    assert (
        response.status_code
        == {"wrong_token": 401, "unknown": 404, "query": 422, "selector": 422}[
            kind
        ]
    )
    assert (
        "PRIVATE" not in response.text
        and auth["init_data"] not in response.text
    )
    assert response.headers["cache-control"] == "no-store"
    assert "facts" not in repo.trace


@pytest.mark.asyncio
async def test_admin_permission_is_rechecked_for_queue_and_old_operation():
    app, repo, own = application()
    requested = await request_ui(app, own)
    admin = auth_for(repo, 1)
    assert (await review_ui(app, admin, requested)).status_code == 200
    repo.actors[U[1]]["admin"] = False
    for path, body in (
        ("admin/queue", {}),
        ("operations/status", {"operation_key": "ui-review"}),
        (requested["case_id"] + "/detail", {}),
    ):
        response = await post(app, admin, path, **body)
        assert response.status_code == 403, response.text
        assert "PRIVATE" not in response.text


@pytest.mark.asyncio
async def test_foreign_preview_and_idempotency_conflict_cannot_reveal_source():
    app, repo, own = application()
    foreign = auth_for(repo, 2)
    response = await post(
        app, foreign, "preview", order_id=str(U[3]), paid_item_ids=[str(U[5])]
    )
    assert response.status_code == 403
    assert "facts" not in repo.trace
    await request_ui(app, own)
    conflict = await post(
        app,
        own,
        "request",
        operation_key="ui-request",
        reason="Different economic intent",
        order_id=str(U[3]),
        paid_item_ids=[str(U[5])],
        expected_source_hash=HASH,
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "idempotency_payload_conflict"
    assert len(repo.rows["requests"]) == 1


@pytest.mark.asyncio
async def test_admin_early_case_read_and_rejection_keep_observation_history():
    app, repo, own = application()
    admin = auth_for(repo, 1)
    observed = await observe_ui(app, admin)
    case_id = observed.json()["case_id"]
    early = await post(app, admin, case_id + "/detail")
    assert (
        early.json()["request"] is None and early.json()["total_minor"] is None
    )
    assert "request" not in early.json()["allowed_actions"]
    own_early = await post(app, own, case_id + "/detail")
    assert own_early.json()["allowed_actions"] == ["request"]
    requested = await request_ui(app, own, existing_case_id=case_id)
    rejected = await review_ui(app, admin, requested, decision="reject")
    assert rejected.status_code == 200
    assert rejected.json()["review_status"] == "rejected"
    assert len(repo.rows["observations"]) == 1
    repo.consistent = False
    invalid = await post(app, admin, case_id + "/detail")
    assert invalid.json()["current"] is None
    assert invalid.json()["state_unavailable"] is True
    assert invalid.json()["allowed_actions"] == ["record_observation"]
    retained = await observe_ui(
        app, admin, operation_key="second-actual", case_id=case_id
    )
    assert retained.status_code == 200
    assert (
        retained.json()["state_unavailable"]
        and retained.json()["applied"] is False
    )


@pytest.mark.asyncio
async def test_case_pagination_is_bounded_and_invalid_cursors_fail_closed():
    app, repo, own = application()
    await request_ui(app, own)
    await observe_ui(app, auth_for(repo, 1))
    first = await post(app, own, "list", limit=1)
    assert len(first.json()["entries"]) == 1 and first.json()["has_more"]
    second = await post(
        app, own, "list", limit=1, cursor=first.json()["next_cursor"]
    )
    assert len(second.json()["entries"]) == 1 and not second.json()["has_more"]
    assert (
        first.json()["entries"][0]["case_id"]
        != second.json()["entries"][0]["case_id"]
    )
    for cursor in ("bad", "00000000-0000-0000-0000-000000000000"):
        result = await post(app, own, "list", cursor=cursor)
        assert result.status_code == 409
    orders = await post(app, own, "orders", cursor=str(U[3]))
    assert orders.json()["entries"] == []


@pytest.mark.asyncio
async def test_source_blocker_is_not_a_fabricated_zero_preview():
    app, repo, own = application()
    repo.scope = replace(
        repo.scope,
        bundle=None,
        unavailable_reason="correction_capture_unavailable",
    )
    result = await post(
        app, own, "preview", order_id=str(U[3]), paid_item_ids=[str(U[5])]
    )
    assert result.status_code == 200, result.text
    assert result.json()["total_minor"] is None
    assert result.json()["components"] == []
    assert result.json()["blockers"] == ["correction_capture_unavailable"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dependency",
    ["correction_service", "correction_view_service", "transaction_manager"],
)
async def test_missing_runtime_dependency_is_safe_unavailable(dependency):
    app, _, auth = application()
    app.state.dispatcher[dependency] = None
    path = (
        "operations/status" if dependency == "correction_service" else "context"
    )
    response = await post(
        app,
        auth,
        path,
        **({"operation_key": "x"} if path.startswith("operations") else {}),
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "correction_unavailable"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["private_value", "private_lookup", "private_runtime", "bad_money"]
)
async def test_unexpected_read_failures_never_escape_or_commit(kind):
    app, _, auth = application()
    service = app.state.dispatcher["correction_view_service"]
    original = service.context
    outcome = []

    @asynccontextmanager
    async def transaction():
        try:
            yield object()
        except Exception:
            outcome.append("rollback")
            raise
        else:
            outcome.append("commit")

    async def malformed(*args, **kwargs):
        if kind == "bad_money":
            return {"nested": [{"amount_minor": 0.1}]}
        error = {
            "private_value": ValueError,
            "private_lookup": LookupError,
            "private_runtime": RuntimeError,
        }[kind]
        raise error("PRIVATE_BACKEND_FAILURE")

    service.context = malformed
    app.state.dispatcher["transaction_manager"] = SimpleNamespace(
        transaction=transaction
    )
    response = await post(app, auth, "context")
    service.context = original
    assert response.status_code in (409, 503)
    assert "PRIVATE" not in response.text
    assert outcome == ["rollback"]


@pytest.mark.asyncio
async def test_missing_admin_case_is_not_found():
    app, _, admin = application(actor=1)
    response = await post(app, admin, str(U[29]) + "/detail")
    assert response.status_code == 404
    assert response.json() == {"detail": "correction_not_found"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["nonprincipal", "wrong_platform", "private_http"]
)
async def test_invalid_principal_resolver_result_has_no_financial_authority(
    kind,
):
    from fastapi import HTTPException

    from ugc_bot.application.native_principal_ports import (
        AuthenticatedMessengerPrincipal,
    )

    app, repo, auth = application()

    async def invalid_resolver(*args, **kwargs):
        if kind == "private_http":
            raise HTTPException(403, {"PRIVATE": "INIT_DATA"})
        if kind == "nonprincipal":
            return U[0]
        return AuthenticatedMessengerPrincipal(U[0], "max", "201")

    for route in app.routes:
        if route.path.endswith("/context"):
            route.endpoint.__self__.resolve = invalid_resolver
    response = await post(app, auth, "context")
    assert response.status_code == (503 if kind == "private_http" else 401)
    assert "PRIVATE" not in response.text and not repo.trace


@pytest.mark.asyncio
@pytest.mark.parametrize("ids", [[], [str(U[5]), str(U[5])]])
async def test_empty_or_duplicate_preview_subset_has_no_command(ids):
    app, repo, auth = application()
    response = await post(
        app, auth, "preview", order_id=str(U[3]), paid_item_ids=ids
    )
    assert response.status_code in (409, 422)
    assert not repo.rows["commands"]

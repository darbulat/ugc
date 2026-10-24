"""Unmounted HTTP with actual dormant services and synthetic source/TM facts."""

from contextlib import asynccontextmanager
from dataclasses import replace
from time import time
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from tests.unit.test_campaign_submission_service import (
    ADMIN,
    OWNER,
    SESSION,
    add_member,
    command,
    environment,
)
from tests.unit.test_miniapp_session_freshness import signed
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)

PRIVATE = "SYNTHETIC_PRIVATE_HTTP_VALUE"
PATHS = {
    "submit": "/campaigns/owned/submit",
    "cancel": "/campaigns/owned/cancel",
    "queue": "/campaigns/admin/queue",
    "review": "/campaigns/admin/review",
    "approve": "/campaigns/admin/approve",
    "reject": "/campaigns/admin/reject",
    "settle": "/campaigns/admin/settle-expiry",
}


class ExistingRoles:
    def __init__(self):
        self.user = SimpleNamespace(
            user_id=OWNER, telegram_id="101", max_id="101", country=None
        )

    async def get_user(self, external, messenger):
        assert external == "101"
        return self.user

    async def set_user(self, *args, **kwargs):
        pytest.fail("moderation HTTP cannot create an account")

    async def set_country(self, *args, **kwargs):
        pytest.fail("moderation HTTP cannot fill country")


class SyntheticTransactions:
    """Counts Python context exits; this proves no SQL transaction behavior."""

    def __init__(self):
        self.entries = self.commits = self.rollbacks = 0
        self.enter_error = self.exit_error = None
        self.session = SESSION

    @asynccontextmanager
    async def transaction(self):
        self.entries += 1
        if self.enter_error:
            raise self.enter_error
        try:
            yield self.session
            if self.exit_error:
                raise self.exit_error
        except Exception:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1


def application(platform="telegram", *, resolver=None):
    from ugc_bot.application.services.campaign_moderation_service import (
        CampaignModerationService,
    )
    from ugc_bot.miniapp.campaign_moderation_api import (
        create_campaign_moderation_router,
    )
    from ugc_bot.miniapp.campaign_principal import resolve_campaign_principal

    repository, submitter, capacity = environment()

    def current_actor(*args):
        actor = repository.actor_type_original(*args)
        return (
            replace(actor, telegram_id="changed", max_id="changed")
            if repository.native_changed
            else actor
        )

    repository.actor_type_original = repository.actor_type
    repository.actor_type = current_actor
    roles, transactions = ExistingRoles(), SyntheticTransactions()
    app = FastAPI()
    app.include_router(
        create_campaign_moderation_router(
            resolver or resolve_campaign_principal
        )
    )
    app.state.config = SimpleNamespace(
        bot=SimpleNamespace(bot_token="synthetic-tg"),
        max_bot=SimpleNamespace(token="synthetic-max"),
    )
    app.state.dispatcher = {
        "user_role_service": roles,
        "transaction_manager": transactions,
        "campaign_submission_service": submitter,
        "campaign_moderation_service": CampaignModerationService(
            repository, capacity, capacity.clock
        ),
        "campaign_capacity_service": capacity,
    }
    auth = {
        "platform": platform,
        "init_data": signed(
            str(int(time())),
            bot_token="synthetic-tg"
            if platform == "telegram"
            else "synthetic-max",
        ),
    }
    return app, repository, roles, transactions, auth


def body_for(action, auth):
    submit = {
        key: value
        for key, value in command().payload.items()
        if key != "action"
    }
    if action == "submit":
        return {**auth, **submit}
    if action == "queue":
        return {**auth, "page": 0}
    if action == "review":
        return {**auth, "submission_id": str(UUID(int=13))}
    if action == "settle":
        return {
            **auth,
            "operation_key": "settle",
            "expected_policy_version": 2,
            "reason": "Synthetic cleanup",
        }
    result = {
        **auth,
        "operation_key": action,
        "campaign_id": submit["campaign_id"],
        "expected_version": 4,
        "reason": "Synthetic reason",
    }
    if action != "cancel":
        result.update(
            submission_id=str(UUID(int=13)),
            revision_digest=submit["revision_digest"],
            review_context="c" * 64,
        )
    return result


async def post(app, path, body, **kwargs):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(path, json=body, **kwargs)


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json() == {"detail": code}
    assert response.headers["cache-control"] == "no-store"
    assert PRIVATE not in response.text


async def prepared(action, platform="telegram"):
    app, repository, roles, transactions, auth = application(platform)
    body = body_for(action, auth)
    if action in ("submit", "settle"):
        if action == "settle":
            roles.user.user_id = ADMIN
        return app, repository, roles, transactions, body
    accepted = await post(app, PATHS["submit"], body_for("submit", auth))
    assert accepted.status_code == 200, accepted.text
    submission_id = accepted.json()["submission_id"]
    if action != "cancel":
        roles.user.user_id = ADMIN
        if action != "queue":
            body["submission_id"] = submission_id
        if action in ("approve", "reject"):
            detail = await post(
                app,
                PATHS["review"],
                {**auth, "submission_id": submission_id},
            )
            assert detail.status_code == 200, detail.text
            body["review_context"] = detail.json()["review_context"]
    return app, repository, roles, transactions, body


@pytest.mark.asyncio
@pytest.mark.parametrize("action", PATHS)
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_signed_endpoints_use_actual_dormant_services(action, platform):
    app, repository, roles, transactions, body = await prepared(
        action, platform
    )
    before = len(repository.writes)
    response = await post(app, PATHS[action], body)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert body["init_data"] not in response.text
    assert roles.user.country is None
    assert transactions.entries == transactions.commits
    assert transactions.rollbacks == 0
    result = response.json()
    if action in ("queue", "review"):
        assert len(repository.writes) == before
        assert (
            "submissions" in result
            if action == "queue"
            else "envelope" in result
        )
    else:
        assert len(repository.writes) == before + 1
        receipt = repository.writes[-1].receipt
        assert receipt.operation_key == body["operation_key"]
        assert receipt.actor_id == roles.user.user_id
    if action == "approve":
        assert result["state"] == "approved_waiting"
        assert result["delivery_state"] == "waiting_delivery_implementation"
        assert len(repository.jobs) == 1
    elif action == "reject":
        assert result["state"] == "rejected" and not repository.jobs
    elif action == "settle":
        assert result == {"settled_count": 0, "has_more": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("action", PATHS)
@pytest.mark.parametrize(
    "extra",
    [
        "actor_id",
        "owner_id",
        "is_admin",
        "principal",
        "recipient_ids",
        "sources",
        "destination",
        "decision",
        "capacity",
    ],
)
async def test_strict_bodies_reject_every_authority_source_and_action_override(
    action, extra
):
    app, repository, _, transactions, auth = application()
    response = await post(
        app, PATHS[action], {**body_for(action, auth), extra: PRIVATE}
    )
    assert_error(response, 422, "campaign_request_invalid")
    assert transactions.entries == 0 and not repository.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("action", PATHS)
async def test_query_and_wrong_primitive_types_are_constant_invalid(action):
    app, repository, _, transactions, auth = application()
    body = body_for(action, auth)
    assert_error(
        await post(app, PATHS[action] + "?owner_id=" + PRIVATE, body),
        422,
        "campaign_request_invalid",
    )
    field = {
        "queue": "page",
        "review": "submission_id",
        "settle": "expected_policy_version",
    }.get(action, "expected_version")
    for invalid in (True, None, "not-a-version-or-uuid"):
        assert_error(
            await post(app, PATHS[action], {**body, field: invalid}),
            422,
            "campaign_request_invalid",
        )
    assert transactions.entries == 0 and not repository.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_native_remap_over_cap_hides_private_counters(
    platform,
):
    app, repository, _, _, auth = application(platform)
    for number in range(500, 506):
        add_member(repository, number)
    assert (
        len(repository.members)
        > repository.policy.limits["recipients_per_campaign"]
    )
    repository.native_changed = True
    response = await post(app, PATHS["submit"], body_for("submit", auth))
    assert_error(response, 403, "campaign_principal_changed")
    assert "receipt" not in repository.trace
    assert (
        "candidates" not in repository.trace
        and "capacity" not in repository.trace
    )
    assert not repository.writes and not repository.receipts


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_http_replay_after_growth_retains_result_and_fresh_state(
    platform,
):
    app, repository, _, _, auth = application(platform)
    original_body = body_for("submit", auth)
    accepted = await post(app, PATHS["submit"], original_body)
    assert accepted.status_code == 200, accepted.text
    for number in range(500, 506):
        add_member(repository, number)
    cancellation = await post(app, PATHS["cancel"], body_for("cancel", auth))
    assert cancellation.status_code == 200, cancellation.text
    before = (
        len(repository.writes),
        len(repository.receipts),
        repository.facts,
    )
    repository.trace.clear()
    replay = await post(app, PATHS["submit"], original_body)
    assert replay.status_code == 200, replay.text
    for key, value in accepted.json().items():
        assert replay.json()[key] == value
    assert replay.json()["current_state"] == "cancelled"
    assert (
        replay.json()["current_version"] == 5
        and not replay.json()["is_current"]
    )
    assert before == (
        len(repository.writes),
        len(repository.receipts),
        repository.facts,
    )
    assert (
        "candidates" not in repository.trace and "due" not in repository.trace
    )
    assert "capacity" not in repository.trace
    assert_error(
        await post(
            app, PATHS["submit"], {**original_body, "terms_hash": "a" * 64}
        ),
        409,
        "campaign_operation_conflict",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", PATHS)
async def test_every_service_receives_typed_native_proof(action):
    app, repository, _, _, body = await prepared(action)
    before = len(repository.writes)
    repository.native_changed = True
    repository.trace.clear()
    assert_error(
        await post(app, PATHS[action], body), 403, "campaign_principal_changed"
    )
    assert (
        "receipt" not in repository.trace
        and "candidates" not in repository.trace
    )
    assert len(repository.writes) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["submit", "approve", "reject", "settle"])
async def test_current_action_authority_also_protects_accepted_replay(action):
    app, repository, _, _, body = await prepared(action)
    response = await post(app, PATHS[action], body)
    assert response.status_code == 200, response.text
    before = len(repository.writes)
    if action == "submit":
        repository.grant = None
        code = "campaign_current_publisher_required"
    else:
        repository.admins.clear()
        code = "campaign_current_admin_required"
    repository.trace.clear()
    assert_error(await post(app, PATHS[action], body), 403, code)
    assert (
        "receipt" not in repository.trace and len(repository.writes) == before
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_signed_existing_only_identity_and_session_privacy(
    platform, caplog
):
    app, repository, roles, transactions, auth = application(platform)
    roles.user = None
    assert_error(
        await post(app, PATHS["submit"], body_for("submit", auth)),
        404,
        "existing_campaign_account_required",
    )
    token = "synthetic-tg" if platform == "telegram" else "synthetic-max"
    for raw in (
        signed("1", bot_token=token),
        auth["init_data"] + "&user=%7B%7D",
        signed(str(int(time())), bot_token=PRIVATE),
    ):
        assert_error(
            await post(
                app,
                PATHS["submit"],
                {**body_for("submit", auth), "init_data": raw},
            ),
            401,
            "campaign_session_invalid",
        )
    assert transactions.entries == 0 and not repository.writes
    assert PRIVATE not in caplog.text and auth["init_data"] not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "returned",
    [None, OWNER, AuthenticatedMessengerPrincipal(OWNER, "max", "101")],
)
async def test_uuid_only_missing_or_wrong_host_principal_is_denied(returned):
    async def resolver(*args, **kwargs):
        return returned

    app, repository, _, transactions, auth = application(resolver=resolver)
    assert_error(
        await post(app, PATHS["submit"], body_for("submit", auth)),
        401,
        "campaign_session_invalid",
    )
    assert transactions.entries == 0 and not repository.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 418])
@pytest.mark.parametrize(
    "code,canonical",
    [
        ("campaign_session_invalid", 401),
        ("campaign_principal_changed", 403),
        ("existing_campaign_account_required", 404),
        ("campaign_version_conflict", 409),
        ("campaign_review_context_changed", 409),
        ("campaign_capacity_settlement_required", 409),
        ("campaign_request_invalid", 422),
        ("campaign_capacity_unavailable", 503),
    ],
)
@pytest.mark.parametrize("stage", ["resolver", "service"])
async def test_known_http_codes_have_canonical_status_across_boundary(
    stage, code, canonical, status
):
    async def refused(*args, **kwargs):
        raise HTTPException(status, code, headers={"Private": PRIVATE})

    app, _, _, _, auth = application(
        resolver=refused if stage == "resolver" else None
    )
    if stage == "service":
        app.state.dispatcher["campaign_submission_service"] = SimpleNamespace(
            submit=refused
        )
    response = await post(app, PATHS["submit"], body_for("submit", auth))
    assert_error(response, canonical, code)
    assert "private" not in response.headers


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        HTTPException(401, PRIVATE),
        HTTPException(422, {"private": PRIVATE}),
        ValueError(PRIVATE),
        LookupError(PRIVATE),
        PermissionError(PRIVATE),
        RuntimeError(PRIVATE),
    ],
)
@pytest.mark.parametrize("stage", ["resolver", "enter", "service", "exit"])
async def test_unexpected_errors_are_constant_and_logs_are_private(
    stage, error, caplog
):
    async def refused(*args, **kwargs):
        raise error

    async def valid(*args, **kwargs):
        return {"state": "synthetic"}

    app, _, _, transactions, auth = application(
        resolver=refused if stage == "resolver" else None
    )
    if stage == "enter":
        transactions.enter_error = error
    elif stage == "exit":
        transactions.exit_error = error
        app.state.dispatcher["campaign_submission_service"] = SimpleNamespace(
            submit=valid
        )
    elif stage == "service":
        app.state.dispatcher["campaign_submission_service"] = SimpleNamespace(
            submit=refused
        )
    assert_error(
        await post(app, PATHS["submit"], body_for("submit", auth)),
        503,
        "campaign_moderation_unavailable",
    )
    assert PRIVATE not in caplog.text and auth["init_data"] not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing",
    [
        "dispatcher",
        "transactions",
        "method",
        "service",
        "session",
        "capability",
    ],
)
async def test_missing_uninstalled_capability_never_becomes_positive_noop(
    missing,
):
    from ugc_bot.application.campaign_moderation_ports import (
        CampaignCapabilities,
    )

    async def resolved(*args, **kwargs):
        return AuthenticatedMessengerPrincipal(OWNER, "telegram", "101")

    app, repository, _, transactions, auth = application(resolver=resolved)
    if missing == "dispatcher":
        del app.state.dispatcher
    elif missing == "transactions":
        del app.state.dispatcher["transaction_manager"]
    elif missing == "method":
        app.state.dispatcher["campaign_submission_service"] = object()
    elif missing == "service":
        del app.state.dispatcher["campaign_submission_service"]
    elif missing == "session":
        transactions.session = None
    else:
        repository.ready = CampaignCapabilities(False, False, False)
    assert_error(
        await post(app, PATHS["submit"], body_for("submit", auth)),
        503,
        "campaign_moderation_unavailable",
    )
    assert not repository.writes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result", [None, PRIVATE, {"value": float("nan")}, {"private": object()}]
)
async def test_encoding_and_result_failures_stay_inside_transaction(
    result, caplog
):
    async def malformed(*args, **kwargs):
        return result

    app, _, _, transactions, auth = application()
    app.state.dispatcher["campaign_submission_service"] = SimpleNamespace(
        submit=malformed
    )
    assert_error(
        await post(app, PATHS["submit"], body_for("submit", auth)),
        503,
        "campaign_moderation_unavailable",
    )
    assert transactions.rollbacks == 1 and transactions.commits == 0
    assert PRIVATE not in caplog.text


@pytest.mark.asyncio
async def test_exact_operation_key_and_endpoint_decision_reach_service():
    from ugc_bot.domain.campaign_moderation import SubmitCampaign

    app, repository, _, _, auth = application()
    body = {**body_for("submit", auth), "operation_key": " exact key "}
    expected = SubmitCampaign.parse(
        OWNER,
        {k: v for k, v in body.items() if k not in ("init_data", "platform")},
    )
    response = await post(app, PATHS["submit"], body)
    assert response.status_code == 200, response.text
    assert repository.writes[-1].receipt.payload_hash == expected.payload_hash
    assert repository.writes[-1].receipt.operation_key == " exact key "
    assert not repository.jobs
    paths = {route.path for route in app.routes}
    assert paths.intersection(PATHS.values()) == set(PATHS.values())
    for suffix in ("send", "export", "claim", "retry", "draft"):
        assert (
            await post(app, "/campaigns/owned/" + suffix, auth)
        ).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,field,value",
    [
        ("submit", "campaign_id", str(UUID(int=0))),
        ("submit", "operation_key", "   "),
        ("cancel", "reason", "   "),
        ("approve", "reason", "   "),
        ("reject", "submission_id", str(UUID(int=0))),
        ("settle", "reason", "   "),
    ],
)
async def test_domain_intent_validation_is_private_before_transaction(
    action, field, value
):
    app, repository, _, transactions, auth = application()
    response = await post(
        app, PATHS[action], {**body_for(action, auth), field: value}
    )
    assert_error(response, 422, "campaign_request_invalid")
    assert not repository.writes and transactions.entries == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ['{"init_data":', "null", "[]"])
async def test_malformed_json_is_constant_without_rejected_body(raw, caplog):
    app, repository, _, transactions, _ = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            PATHS["submit"],
            content=raw,
            headers={"content-type": "application/json"},
        )
    assert_error(response, 422, "campaign_request_invalid")
    assert not repository.writes and transactions.entries == 0
    assert PRIVATE not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["owner", "admin", "self", "missing"])
async def test_foreign_scoped_absence_and_current_review_authority(failure):
    app, repository, roles, _, body = await prepared("approve")
    before = len(repository.writes)
    if failure == "owner":
        path = PATHS["cancel"]
        body = body_for(
            "cancel", {key: body[key] for key in ("init_data", "platform")}
        )
        code, status = "campaign_owner_required", 403
    else:
        path = PATHS["review"]
        body = {
            "init_data": body["init_data"],
            "platform": body["platform"],
            "submission_id": body["submission_id"],
        }
        if failure == "missing":
            body["submission_id"] = str(UUID(int=991))
            code, status = "campaign_submission_not_found", 404
        else:
            roles.user.user_id = OWNER
            if failure == "self":
                repository.admins.add(OWNER)
                code = "campaign_distinct_admin_required"
            else:
                code = "campaign_current_admin_required"
            status = 403
    repository.trace.clear()
    assert_error(await post(app, path, body), status, code)
    assert len(repository.writes) == before
    assert "candidates" not in repository.trace


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked", ["policy", "grant"])
async def test_http_rejection_requires_fresh_context_after_authority_change(
    revoked,
):
    app, repository, _, _, body = await prepared("reject")
    if revoked == "policy":
        repository.policy = replace(
            repository.policy, stream_version=3, enabled=False
        )
    else:
        repository.grant = replace(repository.grant, version=5, active=False)
    assert_error(
        await post(app, PATHS["reject"], body),
        409,
        "campaign_review_context_changed",
    )
    detail = await post(
        app,
        PATHS["review"],
        {key: body[key] for key in ("init_data", "platform", "submission_id")},
    )
    assert detail.status_code == 200, detail.text
    body["review_context"] = detail.json()["review_context"]
    assert_error(
        await post(app, PATHS["approve"], body),
        409,
        "campaign_terms_changed"
        if revoked == "policy"
        else "campaign_publisher_changed",
    )
    rejected = await post(app, PATHS["reject"], body)
    assert (
        rejected.status_code == 200 and rejected.json()["state"] == "rejected"
    )
    assert not repository.jobs and not repository.facts.reservations
    assert not repository.facts.occupations and len(repository.facts.usage) == 1

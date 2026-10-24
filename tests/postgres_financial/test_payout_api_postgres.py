"""Signed TG/MAX runtime requirements, reservation and actual outcome proof."""

from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.orm import Session

from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.payout_contracts import acceptance_json, publication_json
from tests.postgres_financial.conftest import (
    financial_pg_engine as _financial_pg_engine,
)
from tests.postgres_financial.test_payout_runtime import (
    capture_env as capture_env,
)
from tests.postgres_financial.test_payout_runtime import (
    payout_env as payout_env,
)
from ugc_bot.config import MaxBotConfig
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.miniapp.api import router

__all__ = ["capture_env", "payout_env"]

PATH = "/miniapp/api/payouts"


@pytest.fixture(scope="module")
def financial_pg_engine(request):
    """Legacy first-100 queue assertions require their own actual schema.

    Other real reader tests intentionally produce over 100 retained requests.
    Keep those facts and production pagination intact; use the existing exact
    URL checks, migration graph and teardown for this module's private schema.
    """
    yield from _financial_pg_engine.__wrapped__(request)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_signed_runtime_publication_owner_reserve_admin_prepare_and_paid(
    payout_env, platform
):
    env = payout_env
    config = env["config"]
    config.max_bot = MaxBotConfig(MAX_BOT_TOKEN="synthetic-max-token")
    identities = {
        uid: str(uuid4().int % 10**12 + 1)
        for uid in (
            env["client"],
            env["flow"]["manager"],
            env["flow"]["creator"],
        )
    }
    with Session(env["pg"]) as db, db.begin():
        for uid, external in identities.items():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == uid)
                .values(telegram_id=external, max_id=external)
            )

    def auth(uid):
        return {
            "platform": platform,
            "init_data": generate_init_data(
                "test-token"
                if platform == "telegram"
                else "synthetic-max-token",
                int(identities[uid]),
                "synthetic",
            ),
        }

    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    app.state.config = config
    app.state.dispatcher = env["flow"]["container"].build_bot_services()
    admin = auth(env["client"])
    owner = auth(env["flow"]["manager"])
    stranger = auth(env["flow"]["creator"])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        publication = await client.post(
            PATH + "/admin/requirements/publish",
            json=admin
            | dict(
                operation_key="api:publish",
                expected_version=env["requirements"]["version"],
                effective_from=env["flow"]["clock"].at.isoformat(),
                legal_reference="synthetic:legal-policy-api",
                terms_reference="synthetic:payout-api-terms",
                evidence_reference="synthetic:actual-api-publication-proof",
                reason="Synthetic current admin published payout requirements",
                required_fields=[
                    "recipient_name",
                    "bank_account",
                    "legal_status",
                ],
                enabled=True,
                **publication_json(),
            ),
        )
        assert publication.status_code == 200, publication.text
        requirements = publication.json()
        details = await client.post(
            PATH + "/requisites",
            json=owner
            | dict(
                operation_key="api:details",
                requirements_id=requirements["requirements_id"],
                accepted_terms_reference="synthetic:payout-api-terms",
                details=env["details"],
                **acceptance_json(requirements),
            ),
        )
        assert details.status_code == 200, details.text
        payload = owner | dict(
            operation_key="api:request",
            requisites_id=details.json()["requisites_id"],
            amount_minor=60000,
            currency="RUB",
        )
        created = await client.post(PATH + "/request", json=payload)
        assert created.status_code == 200, created.text
        state = created.json()
        assert state["state"] == "reserved"
        assert (
            await client.post(PATH + "/request", json=payload)
        ).json() == state
        assert env["details"]["bank_account"] not in created.text
        assert "recipient_name" not in created.text
        request_id = state["request_id"]
        assert (
            await client.post(PATH + f"/{request_id}/status", json=stranger)
        ).status_code == 403
        assert (
            await client.post(
                PATH + "/request",
                json=payload | {"actor_id": str(env["client"])},
            )
        ).status_code == 422
        assert (
            await client.post(
                PATH + f"/admin/{request_id}/requisites",
                json=owner
                | dict(
                    operation_key="own-reveal", reason="forged admin access"
                ),
            )
        ).status_code == 403
        revealed = await client.post(
            PATH + f"/admin/{request_id}/requisites",
            json=admin
            | dict(
                operation_key="api:reveal",
                reason="Review actual frozen beneficiary",
            ),
        )
        assert revealed.status_code == 200 and revealed.json() == env["details"]
        assert revealed.headers["cache-control"] == "no-store"
        for action in ("review", "start"):
            response = await client.post(
                PATH + "/admin/command",
                json=admin
                | dict(
                    operation_key="api:" + action,
                    request_id=request_id,
                    expected_version=state["version"],
                    action=action,
                    reason="Reviewed synthetic payout scope",
                    evidence_reference="synthetic:review-proof",
                ),
            )
            assert response.status_code == 200, response.text
            state = response.json()
        paid = await client.post(
            PATH + "/admin/result",
            json=admin
            | dict(
                operation_key="api:paid",
                request_id=request_id,
                execution_id=state["execution_id"],
                fence=state["fence"],
                expected_version=state["version"],
                status="paid",
                reason="Actual synthetic settled bank record",
                evidence_reference="synthetic:bank-evidence",
                evidence_hash="b" * 64,
                bank_account="synthetic-origin-account",
                bank_reference=str(uuid4()),
                amount_minor=60000,
                currency="RUB",
                settled_at=env["flow"]["clock"].at.isoformat(),
                recipient_details=env["details"],
            ),
        )
        assert paid.status_code == 200, paid.text
        assert paid.json()["state"] == "paid"
        assert (await client.post(PATH + "/list", json=owner)).json()[0][
            "state"
        ] == "paid"


def own_api(env):
    config = env["config"]
    identities = {
        uid: str(uuid4().int % 10**12 + 1)
        for uid in (
            env["client"],
            env["flow"]["manager"],
            env["flow"]["creator"],
        )
    }
    with Session(env["pg"]) as db, db.begin():
        for uid, external in identities.items():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == uid)
                .values(telegram_id=external)
            )

    def auth(uid):
        return {
            "init_data": generate_init_data(
                "test-token", int(identities[uid]), "synthetic"
            )
        }

    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    app.state.config = config
    app.state.dispatcher = env["flow"]["container"].build_bot_services()
    return app, auth


@pytest.mark.asyncio
async def test_protected_operational_reads_queue_and_inflight_emergency_stop(
    payout_env,
):
    from datetime import timedelta

    from tests.postgres_financial.test_payout_runtime import request_command

    env = payout_env
    state = await env["execute"](request_command(env))
    app, auth = own_api(env)
    admin, owner = auth(env["client"]), auth(env["flow"]["manager"])
    ref = state["request_id"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        public = await client.post(PATH + "/requirements", json=owner)
        assert (
            public.status_code == 200
            and "evidence_reference" not in public.json()
        )
        policy = await client.post(PATH + "/admin/requirements", json=admin)
        assert (
            policy.status_code == 200
            and policy.json()[0]["version"] == env["requirements"]["version"]
        )
        assert (
            await client.post(PATH + "/admin/requirements", json=owner)
        ).status_code == 403
        assert (
            await client.post(PATH + f"/{ref}/status", json=owner)
        ).status_code == 200
        assert (
            await client.post(PATH + f"/{uuid4()}/status", json=owner)
        ).status_code == 404
        assert (
            await client.post(PATH + "/list?recipient=forged", json=owner)
        ).status_code == 422
        assert (
            await client.post(PATH + "/list", json={"init_data": "forged"})
        ).status_code == 401
        stored = app.state.dispatcher.pop("payout_service")
        assert (
            await client.post(PATH + "/list", json=owner)
        ).status_code == 503
        app.state.dispatcher["payout_service"] = stored
        queue = await client.post(PATH + "/admin/queue", json=admin)
        own = next(r for r in queue.json() if r["request_id"] == ref)
        assert not own["overdue"]
        assert (
            await client.post(PATH + "/admin/queue", json=owner)
        ).status_code == 403
        env["flow"]["clock"].at += timedelta(hours=72)
        queue = await client.post(PATH + "/admin/queue", json=admin)
        assert next(r for r in queue.json() if r["request_id"] == ref)[
            "overdue"
        ]
        for action in ("review", "start"):
            response = await client.post(
                PATH + "/admin/command",
                json=admin
                | dict(
                    operation_key="queue-api:" + action,
                    request_id=ref,
                    expected_version=state["version"],
                    action=action,
                    reason="Review actual queued payout",
                    evidence_reference="synthetic:review-proof",
                ),
            )
            assert response.status_code == 200, response.text
            state = response.json()
        env["config"].financial.payouts_enabled = False
        assert (
            await client.post(
                PATH + "/request",
                json=owner
                | dict(
                    operation_key="off",
                    requisites_id=env["requisites"]["requisites_id"],
                    amount_minor=1,
                ),
            )
        ).status_code == 503
        observed = await client.post(
            PATH + "/admin/result",
            json=admin
            | dict(
                operation_key="inflight-off",
                request_id=ref,
                execution_id=state["execution_id"],
                fence=state["fence"],
                expected_version=state["version"],
                status="paid",
                reason="Observed actual synthetic bank result after stop",
                evidence_reference="synthetic:after-stop-bank-statement",
                evidence_hash="c" * 64,
                bank_account="synthetic-origin-account",
                bank_reference=str(uuid4()),
                amount_minor=60000,
                currency="RUB",
                settled_at=env["flow"]["clock"].at.isoformat(),
                recipient_details=env["details"],
            ),
        )
        assert observed.status_code == 200, observed.text
        assert observed.json()["state"] == "unknown"
        history = await client.post(PATH + f"/admin/{ref}/history", json=admin)
        assert history.status_code == 200, history.text
        assert history.json()["outcomes"][0]["status"] == "paid"
        assert not history.json()["outcomes"][0]["applied"]
        assert (
            "ciphertext" not in history.text
            and env["details"]["bank_account"] not in history.text
        )
        assert (
            await client.post(PATH + f"/admin/{ref}/history", json=owner)
        ).status_code == 403
        assert (
            await client.post(PATH + f"/admin/{uuid4()}/history", json=admin)
        ).status_code == 404
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == env["client"])
                .values(admin=False)
            )
        assert (
            await client.post(PATH + f"/admin/{ref}/history", json=admin)
        ).status_code == 403

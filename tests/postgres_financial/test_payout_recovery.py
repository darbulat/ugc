"""Signed own recovery does not resend secrets or misclassify in-flight work."""

import asyncio
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.payout_contracts import acceptance_json
from tests.postgres_financial.test_payout_runtime import (
    capture_env as capture_env,
)
from tests.postgres_financial.test_payout_runtime import (
    payout_env as payout_env,
)
from tests.postgres_financial.test_payout_runtime import rows
from ugc_bot.config import MaxBotConfig
from ugc_bot.domain.financial import MAX_MINOR
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.miniapp.api import router

__all__ = ["capture_env", "payout_env"]
PATH = "/miniapp/api/payouts"


def signed_app(env, platform):
    identities = {
        u: str(uuid4().int % 10**12 + 1)
        for u in (env["client"], env["flow"]["manager"], env["flow"]["creator"])
    }
    token = "test-token" if platform == "telegram" else "synthetic-max-token"
    env["config"].max_bot = MaxBotConfig(MAX_BOT_TOKEN="synthetic-max-token")
    with Session(env["pg"]) as db, db.begin():
        for actor, external in identities.items():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == actor)
                .values(telegram_id=external, max_id=external)
            )
    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    app.state.config = env["config"]
    app.state.dispatcher = env["flow"]["container"].build_bot_services()

    def auth(actor):
        return dict(
            platform=platform,
            init_data=generate_init_data(
                token, int(identities[actor]), "synthetic"
            ),
        )

    return app, auth


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_safe_recovery_masked_reads_and_legacy_integer_string_replay(
    payout_env, platform
):
    env = payout_env
    app, auth = signed_app(env, platform)
    owner, stranger = auth(env["flow"]["manager"]), auth(env["flow"]["creator"])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        payload = owner | dict(
            operation_key="integer-retained-request",
            requisites_id=env["requisites"]["requisites_id"],
            amount_minor=30000,
            currency="RUB",
        )
        first = await client.post(PATH + "/request", json=payload)
        assert first.status_code == 200, first.text
        assert first.json()["amount_minor"] == "30000"
        replay = await client.post(
            PATH + "/request", json=payload | {"amount_minor": "30000"}
        )
        assert replay.json() == first.json()
        receipt = next(
            r
            for r in rows(env, "commands")
            if r["actor_id"] == env["flow"]["manager"]
            and r["operation_key"] == payload["operation_key"]
        )
        assert receipt["result"]["amount_minor"] == 30000
        result = await client.post(
            PATH + "/operations/status",
            json=owner | {"operation_key": payload["operation_key"]},
        )
        assert result.status_code == 200 and result.json()["recorded"] is True
        assert result.json()["result"]["amount_minor"] == "30000"
        assert "payload_hash" not in result.text and "fence" not in result.text
        assert (
            await client.post(
                PATH + "/operations/status",
                json=stranger | {"operation_key": payload["operation_key"]},
            )
        ).json()["recorded"] is False
        assert (
            await client.post(
                PATH + "/operations/status",
                json=owner
                | {"operation_key": "missing", "actor_id": str(env["client"])},
            )
        ).status_code == 422
        assert (
            await client.post(
                PATH + "/requisites/list?recipient=forged", json=owner
            )
        ).status_code == 422
        masked = await client.post(PATH + "/requisites/list", json=owner)
        assert masked.status_code == 200 and masked.json()[0]["usable"]
        for secret in env["details"].values():
            assert secret not in masked.text and secret not in result.text
        service = app.state.dispatcher["payout_service"]
        service.crypto = None
        env["config"].financial.payouts_enabled = False
        masked = await client.post(PATH + "/requisites/list", json=owner)
        assert masked.status_code == 200 and not masked.json()[0]["usable"]
        stored = await client.post(
            PATH + "/operations/status",
            json=owner | {"operation_key": "details:test"},
        )
        assert stored.status_code == 200 and stored.json()["recorded"]
        assert (
            stored.json()["result"]["requisites_id"]
            == env["requisites"]["requisites_id"]
        )
        assert stored.headers["cache-control"] == "no-store"
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == env["client"])
                .values(admin=False)
            )
        hidden = await client.post(
            PATH + "/operations/status",
            json=auth(env["client"]) | {"operation_key": "publish:test"},
        )
        assert (
            hidden.status_code == 409
            and hidden.json()["detail"] == "payout_operation_unavailable"
        )
        assert (
            "evidence_reference" not in hidden.text
            and "content_text" not in hidden.text
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_actual_max_observations_round_trip_without_fabricated_funds(
    payout_env, platform
):
    from tests.postgres_financial.test_payout_runtime import prepare

    env = payout_env
    state = await prepare(env)
    app, auth = signed_app(env, platform)
    owner, admin = auth(env["flow"]["manager"]), auth(env["client"])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        insufficient = await client.post(
            PATH + "/request",
            json=owner
            | dict(
                operation_key="max-insufficient",
                requisites_id=env["requisites"]["requisites_id"],
                amount_minor=str(MAX_MINOR),
            ),
        )
        assert (
            insufficient.status_code == 409
            and insufficient.json()["detail"] == "payout_available_insufficient"
        )
        for i, amount in enumerate(
            [MAX_MINOR, -MAX_MINOR, 0, None, 2**53 - 1, 2**53, 2**53 + 1]
        ):
            observed = await client.post(
                PATH + "/admin/result",
                json=admin
                | dict(
                    operation_key=f"observed-wire-{i}",
                    request_id=state["request_id"],
                    execution_id=state["execution_id"],
                    fence=state["fence"],
                    expected_version=state["version"],
                    status="paid",
                    reason="Synthetic exceptional observed amount",
                    evidence_reference="synthetic:observed-wire",
                    evidence_hash="d" * 64,
                    amount_minor=None if amount is None else str(amount),
                    currency="RUB",
                    bank_account="synthetic-origin-account",
                    bank_reference=str(uuid4()),
                    settled_at=env["flow"]["clock"].at.isoformat(),
                    recipient_details=env["details"],
                ),
            )
            assert observed.status_code == 200, observed.text
            assert observed.json()["state"] == "unknown"
            state = observed.json() | {"fence": state["fence"]}
        history = (
            await client.post(
                PATH + f"/admin/{state['request_id']}/history", json=admin
            )
        ).json()
        amounts = [r["amount_minor"] for r in history["outcomes"]]
        assert {
            None,
            str(MAX_MINOR),
            str(-MAX_MINOR),
            "0",
            str(2**53 - 1),
            str(2**53),
            str(2**53 + 1),
        } == set(amounts)
        for invalid in [
            "01",
            "-0",
            "+1",
            "1e3",
            "1.0",
            " 1",
            "١",
            True,
            1.1,
            str(MAX_MINOR + 1),
        ]:
            rejected = await client.post(
                PATH + "/request",
                json=owner
                | dict(
                    operation_key="invalid-wire",
                    requisites_id=env["requisites"]["requisites_id"],
                    amount_minor=invalid,
                ),
            )
            assert rejected.status_code == 422
            invalid_observation = await client.post(
                PATH + "/admin/result",
                json=admin
                | dict(
                    operation_key="invalid-observation",
                    request_id=state["request_id"],
                    execution_id=state["execution_id"],
                    fence=state["fence"],
                    expected_version=state["version"],
                    status="paid",
                    reason="Synthetic invalid grammar",
                    evidence_reference="synthetic:observed-wire",
                    evidence_hash="d" * 64,
                    amount_minor=invalid,
                ),
            )
            assert invalid_observation.status_code == 422


@pytest.mark.asyncio
async def test_lost_secret_commit_response_is_recovered_without_resubmission(
    payout_env,
):
    env = payout_env
    app, auth = signed_app(env, "telegram")
    real = httpx.ASGITransport(app=app)

    class LostResponse(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            response = await real.handle_async_request(request)
            await response.aclose()
            raise httpx.ReadError("Synthetic response lost after commit")

    payload = auth(env["flow"]["manager"]) | dict(
        operation_key="secret-response-lost",
        requirements_id=env["requirements"]["requirements_id"],
        accepted_terms_reference=env["publication"].terms_reference,
        details=env["details"],
        **acceptance_json(env["requirements"]),
    )
    before = len(rows(env, "requisites"))
    async with httpx.AsyncClient(
        transport=LostResponse(), base_url="http://testserver"
    ) as client:
        with pytest.raises(httpx.ReadError):
            await client.post(PATH + "/requisites", json=payload)
    assert len(rows(env, "requisites")) == before + 1
    async with httpx.AsyncClient(
        transport=real, base_url="http://testserver"
    ) as client:
        lookup = await client.post(
            PATH + "/operations/status",
            json=auth(env["flow"]["manager"])
            | {"operation_key": "secret-response-lost"},
        )
    assert lookup.json()["recorded"] and lookup.status_code == 200
    assert len(rows(env, "requisites")) == before + 1
    assert all(secret not in lookup.text for secret in env["details"].values())


@pytest.mark.asyncio
@pytest.mark.parametrize("commit", [True, False])
async def test_operation_lookup_waits_for_actor_barrier_and_fresh_commit(
    payout_env, monkeypatch, commit
):
    from dataclasses import replace

    env = payout_env
    writer = env["service"]
    reader = env["flow"]["container"].build_bot_services()["payout_service"]
    actor = env["flow"]["manager"]
    started = asyncio.Event()
    pids = []
    original = reader.repository.lock_users

    async def observe(users, *, session):
        pids.append(await session.scalar(text("SELECT pg_backend_pid()")))
        started.set()
        await original(users, session=session)

    monkeypatch.setattr(reader.repository, "lock_users", observe)

    async def lookup():
        async with env["flow"][
            "container"
        ].transaction_manager.transaction() as db:
            return await reader.operation_for_actor(
                actor, "inflight-secret", session=db
            )

    class Rollback(Exception):
        pass

    task = None
    try:
        async with env["flow"][
            "container"
        ].transaction_manager.transaction() as db:
            await writer.execute(
                replace(env["store"], operation_key="inflight-secret"),
                session=db,
            )
            task = asyncio.create_task(lookup())
            await started.wait()
            for _ in range(100):
                with Session(env["pg"]) as probe:
                    waiting = probe.scalar(
                        text(
                            "SELECT wait_event_type='Lock' "
                            "FROM pg_stat_activity "
                            "WHERE pid=:pid"
                        ),
                        {"pid": pids[0]},
                    )
                if waiting:
                    break
                await asyncio.sleep(0.01)
            assert waiting and not task.done()
            if not commit:
                raise Rollback()
    except Rollback:
        pass
    result = await asyncio.wait_for(task, 5)
    assert result["recorded"] is commit
    if not commit:
        # Absence does not reserve the key; an original can arrive later.
        await env["execute"](
            replace(env["store"], operation_key="inflight-secret")
        )
        async with env["flow"][
            "container"
        ].transaction_manager.transaction() as db:
            assert (
                await reader.operation_for_actor(
                    actor, "inflight-secret", session=db
                )
            )["recorded"]


@pytest.mark.asyncio
async def test_lookup_whitelist_and_wrong_key_readability(payout_env):
    import base64
    import os

    from sqlalchemy import insert

    from ugc_bot.infrastructure.db.payout_models import TABLE_MAP
    from ugc_bot.infrastructure.secure_requisites import PayoutRequisitesCrypto

    env = payout_env
    owner = env["flow"]["manager"]
    stored = env["requisites"]
    # Synthetic legacy retained JSON may include unrelated private fields;
    # lookup emits only the known typed receipt and verifies actual ownership.
    with Session(env["pg"]) as db, db.begin():
        for key, result in (
            (
                "poisoned-extras",
                stored
                | {
                    "fence": "private-fence",
                    "reason": "private reason",
                    "recipient_details": env["details"],
                    "payload_hash": "private-hash",
                },
            ),
            ("foreign-resource", stored | {"requisites_id": str(uuid4())}),
        ):
            db.execute(
                insert(TABLE_MAP["commands"]).values(
                    command_id=uuid4(),
                    actor_id=owner,
                    operation_key=key,
                    action="StorePayoutRequisites",
                    payload_hash="a" * 64,
                    recorded_at=env["flow"]["clock"].at,
                    result=result,
                )
            )
    service = env["service"]
    service.crypto = PayoutRequisitesCrypto(
        base64.urlsafe_b64encode(os.urandom(32)).decode(), service.crypto.key_id
    )
    async with env["flow"]["container"].transaction_manager.transaction() as db:
        recovered = await service.operation_for_actor(
            owner, "poisoned-extras", session=db
        )
        masked = await service.requisites_for_actor(owner, session=db)
    assert recovered["result"] == stored
    assert not masked[0]["usable"]
    assert (
        "payout_requisites_authentication_failed"
        in masked[0]["unusable_reasons"]
    )
    assert all(
        v not in str(recovered) + str(masked) for v in env["details"].values()
    )
    async with env["flow"]["container"].transaction_manager.transaction() as db:
        with pytest.raises(ValueError, match="payout_operation_unavailable"):
            await service.operation_for_actor(
                owner, "foreign-resource", session=db
            )
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == owner)
            .values(status="blocked")
        )
    async with env["flow"]["container"].transaction_manager.transaction() as db:
        for method, args in (
            (service.operation_for_actor, (owner, "poisoned-extras")),
            (service.requisites_for_actor, (owner,)),
        ):
            with pytest.raises(ValueError, match="active_actor_required"):
                await method(*args, session=db)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_validation_errors_never_echo_private_input_or_auth(
    payout_env, platform
):
    env = payout_env
    app, auth = signed_app(env, platform)
    owner, admin = auth(env["flow"]["manager"]), auth(env["client"])
    secret = "SYNTHETIC-PRIVATE-VALIDATION-SECRET"
    cases = [
        (
            "/requisites",
            owner
            | dict(
                operation_key="invalid-private-shape",
                requirements_id=env["requirements"]["requirements_id"],
                accepted_terms_reference="synthetic:payout-terms",
                details={"bank_account": {"private": secret}},
            ),
        ),
        (
            "/admin/result",
            admin
            | dict(
                operation_key="invalid-bank-shape",
                recipient_details={"bank_account": {"private": secret}},
            ),
        ),
        (
            "/admin/requirements/publish",
            admin
            | dict(
                operation_key="invalid-document-shape",
                document={"content_text": {"private": secret}},
            ),
        ),
        (
            "/operations/status",
            owner
            | dict(
                operation_key="invalid-auth-shape",
                init_data={"private": secret},
            ),
        ),
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        for path, payload in cases:
            response = await client.post(PATH + path, json=payload)
            assert response.status_code == 422
            assert (
                secret not in response.text
                and owner["init_data"] not in response.text
                and admin["init_data"] not in response.text
            )
            assert response.json() == {"detail": "payout_request_invalid"}
            assert response.headers["cache-control"] == "no-store"
        denied = await client.post(
            PATH + "/operations/status",
            json=owner
            | {"operation_key": "missing", "init_data": "invalid-auth"},
        )
        assert (
            denied.status_code == 401
            and denied.headers["cache-control"] == "no-store"
        )

"""The selector lists actual published policies for this signed client only."""

from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.orm import Session

from tests.postgres_financial.test_order_intake import intake_env as _intake_env
from tests.postgres_financial.test_order_intake_api import app, body
from ugc_bot.infrastructure.db.models import (
    FinancialPolicyVersionModel,
    UserModel,
)


@pytest_asyncio.fixture
async def intake_env(financial_pg_engine):
    async for env in _intake_env.__wrapped__(financial_pg_engine):
        yield env


@pytest.mark.asyncio
async def test_signed_policy_list_filters_foreign_future_unpublished_versions(
    intake_env,
):
    env = intake_env
    at = env["clock"].at
    with Session(env["pg"]) as db, db.begin():
        for label, allowed, effective, terms in (
            (
                "foreign",
                [str(uuid4())],
                at - timedelta(days=1),
                "foreign-terms",
            ),
            (
                "future",
                [str(env["user"].user_id)],
                at + timedelta(days=10),
                "future-terms",
            ),
            (
                "unpublished",
                [str(env["user"].user_id)],
                at - timedelta(days=1),
                "",
            ),
        ):
            db.add(
                FinancialPolicyVersionModel(
                    version=label + uuid4().hex,
                    approved_by=env["admin"].user_id,
                    approved_at=at - timedelta(days=2),
                    effective_from=effective,
                    refund_window_seconds=86400,
                    rules={
                        "allowed_clients": allowed,
                        "terms_reference": terms,
                    },
                )
            )
    auth = {
        key: value
        for key, value in body(env).items()
        if key in ("init_data", "platform")
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(env, env["container"])),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/miniapp/api/financial/orders/policies", json=auth
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["writes_paused"] is False
        assert data["currency"] == "RUB"
        assert [p["version"] for p in data["policies"]] == [env["policy"]]
        policy = data["policies"][0]
        assert policy["terms_reference"] == "synthetic-approved-terms"
        assert policy["refund_window_seconds"] == 3600
        assert policy["selection_minor"] == 50000
        assert policy["accompaniment_minor"] == 120000
        assert policy["position_count"] == 30
        assert not {"allowed_clients", "approved_by", "rules"} & policy.keys()
        foreign = await client.post(
            "/miniapp/api/financial/orders/policies",
            json={**auth, "client_id": str(uuid4())},
        )
        assert foreign.status_code == 422
        query = await client.post(
            "/miniapp/api/financial/orders/policies?client_id=other", json=auth
        )
        assert query.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("gate", ["core_enabled", "new_orders_enabled"])
async def test_policy_selector_reports_paused_without_inventing_versions(
    intake_env, gate
):
    env = intake_env
    setattr(env["config"].financial, gate, False)
    auth = {
        key: value
        for key, value in body(env).items()
        if key in ("init_data", "platform")
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(env, env["container"])),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/miniapp/api/financial/orders/policies", json=auth
        )
        assert response.status_code == 200, response.text
        assert response.json()["writes_paused"] is True
        assert response.json()["policies"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,country,code",
    [
        ("blocked", "ru", 403),
        ("active", "unpublished", 200),
        ("active", None, 200),
    ],
)
async def test_policy_selector_checks_current_client_and_actual_currency(
    intake_env, status, country, code
):
    env = intake_env
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["user"].user_id)
            .values(status=status, country=country)
        )
    auth = {
        key: value
        for key, value in body(env).items()
        if key in ("init_data", "platform")
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(env, env["container"])),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/miniapp/api/financial/orders/policies", json=auth
        )
        assert response.status_code == code
        if code == 200:
            assert response.json()["policies"] == []
            assert response.json()["currency"] != "RUB"

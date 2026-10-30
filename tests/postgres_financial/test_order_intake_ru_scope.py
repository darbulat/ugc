"""New ordering requires Russia and the country's RUB currency."""

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.orm import Session

from tests.postgres_financial.test_order_intake import (
    command,
    scoped_rows,
    service,
)
from tests.postgres_financial.test_order_intake import (
    intake_env as _intake_env,
)
from tests.postgres_financial.test_order_intake_api import app, body
from ugc_bot.config import MaxBotConfig
from ugc_bot.container import Container
from ugc_bot.infrastructure.db.models import CountryModel, UserModel


@pytest_asyncio.fixture
async def intake_env(financial_pg_engine):
    async for env in _intake_env.__wrapped__(financial_pg_engine):
        yield env


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "country,currency",
    [("xxrub", "RUB"), ("ru", "KZT"), (None, None), ("missing", None)],
)
async def test_new_orders_require_ru_and_rub(intake_env, country, currency):
    env = intake_env
    with Session(env["pg"]) as db, db.begin():
        if country == "ru":
            db.execute(
                update(CountryModel)
                .where(CountryModel.code == "ru")
                .values(currency_code=currency)
            )
        elif currency is not None:
            db.add(
                CountryModel(
                    code=country,
                    name_native="Synthetic",
                    currency_code=currency,
                    currency_symbol="R",
                )
            )
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["user"].user_id)
            .values(country=country)
        )
    request = command(env)
    assert (
        await service(env).eligible_policies(env["user"].user_id)
    ).policies == ()
    with pytest.raises(ValueError, match="unpublished_currency"):
        await service(env).create(request)
    assert scoped_rows(env, "order_intake_receipts", request.order_id) == []
    if country == "ru":
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(CountryModel)
                .where(CountryModel.code == "ru")
                .values(currency_code="RUB")
            )


@pytest.mark.asyncio
async def test_existing_intake_retry_survives_country_change(intake_env):
    env = intake_env
    request = command(env)
    original = await service(env).create(request)
    with Session(env["pg"]) as db, db.begin():
        db.add(
            CountryModel(
                code="xretry",
                name_native="Synthetic",
                currency_code="RUB",
                currency_symbol="R",
            )
        )
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["user"].user_id)
            .values(country="xretry")
        )
    assert await service(env).create(request) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("country", [None, "missing", "xother"])
async def test_direct_order_creation_rejects_missing_or_foreign_country(
    intake_env, country
):
    env = intake_env
    with Session(env["pg"]) as db, db.begin():
        if country == "xother":
            db.add(
                CountryModel(
                    code=country,
                    name_native="Synthetic",
                    currency_code="RUB",
                    currency_symbol="R",
                )
            )
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["user"].user_id)
            .values(country=country)
        )

    request = command(env)
    orders = env["container"].build_bot_services()["order_service"]
    policy = await orders.paid_item_service.policy_service.load_policy(
        env["policy"]
    )
    with pytest.raises(ValueError, match="unpublished_currency"):
        await orders.create_financial_order(
            order_id=request.order_id,
            advertiser_id=request.client_id,
            order_type=request.order_type,
            product_link=request.product_link,
            offer_text=request.offer_text,
            barter_description=request.barter_description,
            price=float(request.honorarium),
            policy=policy,
            order_created_at=env["clock"].at,
            now=env["clock"].at,
            selection_due_at=request.selection_due_at,
            currency="RUB",
            accompaniment_ordinals=frozenset(),
            client_contact_reference=request.contact_reference,
            idempotency_key=request.operation_key,
        )


@pytest.mark.asyncio
async def test_direct_order_creation_rejects_russia_without_rub(intake_env):
    env = intake_env
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(CountryModel)
            .where(CountryModel.code == "ru")
            .values(currency_code="KZT")
        )
    try:
        request = command(env)
        orders = env["container"].build_bot_services()["order_service"]
        policy = await orders.paid_item_service.policy_service.load_policy(
            env["policy"]
        )
        with pytest.raises(ValueError, match="unpublished_currency"):
            await orders.create_financial_order(
                order_id=request.order_id,
                advertiser_id=request.client_id,
                order_type=request.order_type,
                product_link=request.product_link,
                offer_text=request.offer_text,
                barter_description=request.barter_description,
                price=float(request.honorarium),
                policy=policy,
                order_created_at=env["clock"].at,
                now=env["clock"].at,
                selection_due_at=request.selection_due_at,
                currency="RUB",
                accompaniment_ordinals=frozenset(),
                client_contact_reference=request.contact_reference,
                idempotency_key=request.operation_key,
            )
    finally:
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(CountryModel)
                .where(CountryModel.code == "ru")
                .values(currency_code="RUB")
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_signed_api_cannot_create_for_foreign_rub_account(
    intake_env, platform
):
    env = intake_env
    with Session(env["pg"]) as db, db.begin():
        db.merge(
            CountryModel(
                code="xapi",
                name_native="Synthetic",
                currency_code="RUB",
                currency_symbol="R",
            )
        )
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["user"].user_id)
            .values(country="xapi", max_id=env["user"].telegram_id)
        )
    config = env["config"].model_copy(
        update={"max_bot": MaxBotConfig(MAX_BOT_TOKEN="max-test-token")}
    )
    container = Container(config)
    try:
        payload = body(env, platform)
        auth = {k: payload[k] for k in ("init_data", "platform")}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app(env, container)),
            base_url="http://test",
        ) as client:
            policies = await client.post(
                "/miniapp/api/financial/orders/policies", json=auth
            )
            assert policies.status_code == 200
            assert policies.json()["policies"] == []
            response = await client.post(
                "/miniapp/api/financial/orders", json=payload
            )
            assert response.status_code == 400
            assert response.json()["detail"] == "unpublished_currency"
    finally:
        await container.dispose()

"""Customer pages use real ownership, payments and completion snapshots."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.orm import Session

from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.factories import (
    create_test_advertiser_profile,
    create_test_user,
)
from tests.postgres_financial.test_order_intake import intake_env as _intake_env
from tests.postgres_financial.test_order_intake_api import app, body
from ugc_bot.application.services.client_order_view_service import (
    ClientOrderViewService,
)
from ugc_bot.container import Container
from ugc_bot.domain.enums import InteractionStatus, OrderStatus
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.models import InteractionModel, OrderModel
from ugc_bot.infrastructure.db.repositories.client_order_views import (
    SqlAlchemyClientOrderViewRepository,
)
from ugc_bot.infrastructure.db.repositories.customer_workflows import (
    SqlAlchemyCustomerWorkflowRepository,
)


@pytest_asyncio.fixture
async def intake_env(financial_pg_engine):
    async for value in _intake_env.__wrapped__(financial_pg_engine):
        yield value


@pytest.mark.asyncio
async def test_order_pages_are_owned_and_have_actual_progress(intake_env):
    env = intake_env
    container = Container(env["config"])
    views = ClientOrderViewService(
        SqlAlchemyCustomerWorkflowRepository(),
        container.transaction_manager,
        SystemClock(),
        SqlAlchemyClientOrderViewRepository(),
    )
    creator = await create_test_user(
        container.build_repos()["user_repo"],
        external_id=str(uuid4().int % 10**12 + 1),
        country="ru",
    )
    outsider = await create_test_user(
        container.build_repos()["user_repo"],
        external_id=str(uuid4().int % 10**12 + 1),
        country="ru",
    )
    await create_test_advertiser_profile(
        container.build_repos()["advertiser_repo"], outsider.user_id
    )
    ids = [uuid4() for _ in range(12)]
    now = datetime.now(timezone.utc)
    with Session(env["pg"]) as db, db.begin():
        for n, oid in enumerate(ids):
            db.add(
                OrderModel(
                    order_id=oid,
                    advertiser_id=env["user"].user_id,
                    product_link="https://example.test/same",
                    offer_text=f"Campaign {n}",
                    price=1000,
                    bloggers_needed=10,
                    status=(
                        OrderStatus.ACTIVE
                        if n == 11
                        else OrderStatus.CLOSED
                        if n == 0
                        else OrderStatus.NEW
                    ),
                    created_at=now + timedelta(seconds=n),
                )
            )
        db.add(
            OrderModel(
                order_id=uuid4(),
                advertiser_id=outsider.user_id,
                product_link="https://example.test/private",
                offer_text="Private campaign",
                price=1000,
                bloggers_needed=10,
                status=OrderStatus.NEW,
                created_at=now,
            )
        )
        db.flush()
        db.add(
            InteractionModel(
                interaction_id=uuid4(),
                order_id=ids[-1],
                blogger_id=creator.user_id,
                advertiser_id=env["user"].user_id,
                status=InteractionStatus.OK,
                created_at=now,
                updated_at=now,
            )
        )
    first = await views.list(env["user"].user_id, page=0, limit=10)
    assert first["total"] == 12 and first["has_more"]
    assert len(first["orders"]) == 10
    assert first["orders"][0]["public_title"] == "Campaign 11"
    assert first["orders"][0]["public_number"].startswith("UMC-")
    assert first["orders"][0]["progress"] == {
        "assigned": 1,
        "completed": 1,
        "total": 10,
    }
    second = await views.list(env["user"].user_id, page=1, limit=10)
    assert len(second["orders"]) == 2 and not second["has_more"]
    assert {o["order_id"] for o in first["orders"]}.isdisjoint(
        o["order_id"] for o in second["orders"]
    )
    assert (await views.list(outsider.user_id))["total"] == 1
    assert (await views.list(env["user"].user_id, status="active"))[
        "total"
    ] == 1
    for invalid in ({"page": -1}, {"limit": 0}, {"status": "invalid"}):
        with pytest.raises(ValueError):
            await views.list(env["user"].user_id, **invalid)
    application = app(env, container)
    application.state.dispatcher["client_order_view_service"] = views
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        legacy_create = await client.post(
            "/miniapp/api/orders",
            json={
                "init_data": body(env)["init_data"],
                "product_link": "https://example.test/product",
                "offer_text": "Campaign",
                "price": 1000,
                "bloggers_needed": 30,
            },
        )
        assert legacy_create.status_code == 409, legacy_create.text
        assert legacy_create.json()["detail"] == "use_canonical_order_intake"
        response = await client.post(
            "/miniapp/api/orders/list",
            json={"init_data": body(env)["init_data"], "limit": 10, "page": 1},
        )
        assert response.status_code == 200, response.text
        assert (
            response.json()["total"] == 12
            and len(response.json()["orders"]) == 2
        )
        for score in (True, 2.5, "5", 0, 6):
            bad = await client.post(
                "/miniapp/api/ratings",
                json={
                    "init_data": "bad",
                    "order_id": str(ids[0]),
                    "blogger_id": str(creator.user_id),
                    "score": score,
                },
            )
            assert bad.status_code == 422
        ratings = await client.post(
            "/miniapp/api/customer/orders/ratings",
            json={
                "init_data": body(env)["init_data"],
                "order_id": str(ids[-1]),
            },
        )
        assert ratings.status_code == 200, ratings.text
        author = next(
            a
            for a in ratings.json()["authors"]
            if a["blogger_id"] == str(creator.user_id)
        )
        assert author["rating_eligible"]
        completed = await client.post(
            "/miniapp/api/customer/orders/completion",
            json={
                "init_data": body(env)["init_data"],
                "order_id": str(ids[-1]),
            },
        )
        assert completed.status_code == 200, completed.text
        assert completed.json() == {"has_completed_work": True}
        empty = await client.post(
            "/miniapp/api/customer/orders/completion",
            json={"init_data": body(env)["init_data"], "order_id": str(ids[0])},
        )
        assert empty.status_code == 200, empty.text
        assert empty.json() == {"has_completed_work": False}
        rated = await client.post(
            "/miniapp/api/ratings",
            json={
                "init_data": body(env)["init_data"],
                "order_id": str(ids[-1]),
                "blogger_id": str(creator.user_id),
                "score": 5,
            },
        )
        assert rated.status_code == 200, rated.text
        other_signed = generate_init_data(
            "test-token", int(outsider.telegram_id), "outsider"
        )
        denied = await client.post(
            "/miniapp/api/customer/orders/ratings",
            json={"init_data": other_signed, "order_id": str(ids[-1])},
        )
        assert denied.status_code == 403
        denied_completion = await client.post(
            "/miniapp/api/customer/orders/completion",
            json={"init_data": other_signed, "order_id": str(ids[-1])},
        )
        assert denied_completion.status_code == 403
        unknown = await client.post(
            "/miniapp/api/customer/orders/ratings",
            json={"init_data": "bad", "order_id": str(uuid4())},
        )
        assert unknown.status_code == 401
    await container.dispose()

"""Operator API and rollback checks against private migrated PostgreSQL."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.postgres_financial.test_legacy_financial_cases import (
    review_setup,
)
from tests.unit.test_miniapp_auth import _make_valid_init_data
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.enums import InteractionStatus
from ugc_bot.infrastructure.db.models import (
    LegacyFinancialCaseEventModel,
    LegacyFinancialCaseModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.interactions import (
    _to_interaction_model,
)
from ugc_bot.infrastructure.db.repositories.user import SqlAlchemyUserRepository
from ugc_bot.miniapp.api import router


@pytest_asyncio.fixture
async def cases_factory(financial_pg_engine):
    engine = create_async_engine(financial_pg_engine.url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_keyset_reaches_over_200_old_issues_and_filters(
    cases_factory,
):
    _, interaction, service = await review_setup(cases_factory)
    ids = [uuid4() for _ in range(205)]
    async with cases_factory.begin() as db:
        for case_id in ids:
            db.add(
                _to_interaction_model(
                    replace(
                        interaction,
                        interaction_id=case_id,
                        status=InteractionStatus.ISSUE,
                    )
                )
            )
    first = await service.list_cases(interaction.advertiser_id, limit=200)
    second = await service.list_cases(
        interaction.advertiser_id,
        after=UUID(first[-1]["interaction_id"]),
        limit=200,
    )
    assert len(first) == 200
    assert len(second) >= 6
    assert {row["interaction_id"] for row in first + second} >= {
        str(value) for value in [interaction.interaction_id, *ids]
    }
    async with cases_factory.begin() as db:
        await db.execute(
            update(LegacyFinancialCaseModel)
            .where(
                LegacyFinancialCaseModel.interaction_id
                == interaction.interaction_id
            )
            .values(released=True)
        )
    released = await service.list_cases(
        interaction.advertiser_id, interaction.interaction_id, released=True
    )
    assert [row["interaction_id"] for row in released] == [
        str(interaction.interaction_id)
    ]
    assert await service.list_cases(
        interaction.advertiser_id, limit=1, released=False
    )
    for invalid in (0, 201):
        with pytest.raises(ValueError):
            await service.list_cases(interaction.advertiser_id, limit=invalid)


@pytest.mark.asyncio
async def test_real_signed_api_to_pg_review_and_rejections(cases_factory):
    recipient, interaction, service = await review_setup(cases_factory)
    admin_external, user_external = str(uuid4().int), str(uuid4().int)
    async with cases_factory.begin() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == interaction.advertiser_id)
            .values(telegram_id=admin_external)
        )
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == recipient)
            .values(telegram_id=user_external)
        )
    users = SqlAlchemyUserRepository(cases_factory)
    app = FastAPI()
    app.include_router(router)
    app.state.config = SimpleNamespace(
        bot=SimpleNamespace(bot_token="test-token"), max_bot=None
    )
    app.state.dispatcher = {
        "user_repo": users,
        "user_role_service": UserRoleService(users),
        "legacy_financial_case_service": service,
    }
    auth = {
        "init_data": _make_valid_init_data("test-token", int(admin_external))
    }
    body = {
        **auth,
        "expected_version": 1,
        "command_id": str(uuid4()),
        "decision": "release_no_adjustment",
        "reason": "Verified unchanged legacy delivery",
        "confirmed_result": True,
    }
    url = f"/api/finance/legacy-cases/{interaction.interaction_id}/review"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        assert (
            await client.post(
                "/api/finance/legacy-cases", json={"init_data": "forged"}
            )
        ).status_code == 401
        unauthorized = {
            **body,
            "init_data": _make_valid_init_data(
                "test-token", int(user_external)
            ),
        }
        assert (await client.post(url, json=unauthorized)).status_code == 403
        for extra in (
            {"actor_id": str(interaction.advertiser_id)},
            {"admin": True},
        ):
            assert (
                await client.post(url, json={**body, **extra})
            ).status_code == 422
        assert (
            await client.post(url, json={**body, "expected_version": 999})
        ).status_code == 409
        assert (
            await client.post(url, json={**body, "reason": ""})
        ).status_code == 422
        assert (
            await client.post(url, json={**body, "reason": "   "})
        ).status_code == 409
        for invalid in ({"limit": 201}, {"limit": 0}, {"after": "bad"}):
            assert (
                await client.post(
                    "/api/finance/legacy-cases", json={**auth, **invalid}
                )
            ).status_code == 422
        visible = await client.post(
            "/api/finance/legacy-cases",
            json={
                **auth,
                "interaction_id": str(interaction.interaction_id),
                "limit": 1,
                "released": False,
            },
        )
        assert visible.status_code == 200
        assert visible.json()[0]["version"] == 1
        result = await client.post(url, json=body)
        assert result.status_code == 200
        assert result.json()["released"] is True
        assert (await client.post(url, json=body)).json() == result.json()
        assert (
            await client.post(url, json={**body, "reason": "Changed request"})
        ).status_code == 409
    async with cases_factory() as db:
        events = (
            await db.scalars(
                select(LegacyFinancialCaseEventModel)
                .where(
                    LegacyFinancialCaseEventModel.interaction_id
                    == interaction.interaction_id
                )
                .order_by(LegacyFinancialCaseEventModel.version)
            )
        ).all()
        assert len(events) == 2
        assert events[-1].actor_id == interaction.advertiser_id
        assert events[-1].command_id == UUID(body["command_id"])


@pytest.mark.asyncio
async def test_downgrade_refuses_released_case_history_in_private_schema(
    cases_factory,
):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from tests.postgres_financial.test_legacy_financial_cases import release
    from ugc_bot.infrastructure.db.migrations.versions import (
        legacy_financial_guard,
    )

    _, interaction, service = await review_setup(cases_factory)
    await release(service, interaction)
    async with cases_factory() as db:
        schema = await db.scalar(text("SELECT current_schema()"))
        assert schema.startswith("financial_test_")
        before = (
            await db.execute(
                text(
                    "SELECT * FROM legacy_financial_case_events "
                    "ORDER BY event_id"
                )
            )
        ).all()

    def downgrade(connection):
        with Operations.context(
            MigrationContext.configure(connection.connection())
        ):
            legacy_financial_guard.downgrade()

    with pytest.raises(RuntimeError, match="case history"):
        async with cases_factory.begin() as db:
            await db.run_sync(downgrade)
    async with cases_factory() as db:
        assert (
            await db.execute(
                text(
                    "SELECT * FROM legacy_financial_case_events "
                    "ORDER BY event_id"
                )
            )
        ).all() == before
        assert (
            await db.scalar(
                select(LegacyFinancialCaseModel.released).where(
                    LegacyFinancialCaseModel.interaction_id
                    == interaction.interaction_id
                )
            )
            is True
        )
        assert (
            await db.scalar(text("SELECT version_num FROM alembic_version"))
            == "legacy_financial_guard"
        )

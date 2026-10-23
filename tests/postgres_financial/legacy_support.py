"""Private, schema-isolated PostgreSQL fixtures for the legacy regressions.

Only the explicit financial-test URL is accepted. Never use DATABASE_URL.
"""

import os
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ugc_bot.infrastructure.db.models import (
    AuditLogModel,
    InteractionModel,
    OrderModel,
    PaymentModel,
    ReferralIncomeEntryModel,
    UserModel,
    UserReferralBindingModel,
    UserReferralPendingModel,
)


@pytest_asyncio.fixture
async def legacy_pg():
    import pytest

    raw = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not raw:
        pytest.skip(
            "FINANCIAL_TEST_DATABASE_URL is required for PostgreSQL regressions"
        )
    from tests.helpers.financial_environment import require_test_database

    url = make_url(require_test_database(raw))
    schema = "legacy_regression_" + uuid4().hex
    admin = create_async_engine(url.set(drivername="postgresql+psycopg"))
    async with admin.begin() as conn:
        await conn.execute(
            text(
                'CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public'
            )
        )
        await conn.execute(
            text("CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public")
        )
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        url.set(drivername="postgresql+psycopg"),
        connect_args={"options": f"-csearch_path={schema},public"},
    )
    try:
        async with engine.begin() as conn:
            # Only existing tables needed by these regressions, on real PG.
            for model in (
                UserModel,
                OrderModel,
                PaymentModel,
                InteractionModel,
                UserReferralBindingModel,
                UserReferralPendingModel,
                ReferralIncomeEntryModel,
                AuditLogModel,
            ):
                from sqlalchemy import Enum
                from sqlalchemy.schema import CreateTable

                for column in model.__table__.columns:
                    if isinstance(column.type, Enum):
                        await conn.run_sync(
                            lambda c, enum=column.type: enum.create(
                                c, checkfirst=True
                            )
                        )
                await conn.execute(CreateTable(model.__table__))
        yield engine, async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()

"""Load approved policy from migrated PostgreSQL, never request data."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.postgres_financial import test_financial_items_schema as schema_tests
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicy,
)
from ugc_bot.infrastructure.db.models import FinancialPolicyVersionModel
from ugc_bot.infrastructure.db.repositories.financial_policy import (
    SqlAlchemyFinancialPolicyRepository,
)


@pytest.fixture
def seed(financial_pg_engine, request):
    return schema_tests.seed.__wrapped__(financial_pg_engine, request)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [None, "clients-string", "client-zero", "terms-int", "rules-list"],
)
async def test_policy_reader_loads_only_explicit_typed_approved_values(
    financial_pg_engine, seed, invalid
):
    repo = SqlAlchemyFinancialPolicyRepository()
    assert hasattr(repo, "load"), "Typed approved-policy reader is missing"
    version, client = str(uuid4()), uuid4()
    rules = {
        "allowed_clients": [str(client)],
        "terms_reference": "terms:synthetic:v1",
    }
    if invalid == "clients-string":
        rules["allowed_clients"] = str(client)
    elif invalid == "client-zero":
        rules["allowed_clients"] = ["00000000-0000-0000-0000-000000000000"]
    elif invalid == "terms-int":
        rules["terms_reference"] = 123
    elif invalid == "rules-list":
        rules = []
    with Session(financial_pg_engine) as db, db.begin():
        db.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=seed["user"],
                approved_at=seed["now"],
                effective_from=seed["now"],
                refund_window_seconds=3600,
                rules=rules,
            )
        )
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory.begin() as session:
            if invalid:
                with pytest.raises(ValueError, match="invalid_policy_document"):
                    await repo.load(version, session=session)
            else:
                assert await repo.load(
                    version, session=session
                ) == FinancialPolicy(
                    version=version,
                    approved_by=seed["user"],
                    approved_at=seed["now"],
                    effective_from=seed["now"],
                    selection_refund_window=timedelta(seconds=3600),
                    allowed_clients=frozenset({client}),
                    terms_reference="terms:synthetic:v1",
                )
                assert await repo.load("absent-policy", session=session) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_actual_container_loads_approval_using_its_transaction_manager(
    financial_pg_engine, seed
):
    from ugc_bot.config import AppConfig, FinancialConfig
    from ugc_bot.container import Container
    from ugc_bot.domain.enums import OrderType
    from ugc_bot.infrastructure.db.models import AdvertiserProfileModel

    version = str(uuid4())
    with Session(financial_pg_engine) as db, db.begin():
        db.add(
            AdvertiserProfileModel(
                user_id=seed["user"], contact="synthetic-test-contact"
            )
        )
        db.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=seed["user"],
                approved_at=seed["now"],
                effective_from=seed["now"],
                refund_window_seconds=3600,
                rules={
                    "allowed_clients": [str(seed["user"])],
                    "terms_reference": "terms:synthetic:v1",
                },
            )
        )
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "KAFKA_ENABLED": False,
            "REDIS_URL": "",
            "DATABASE_URL": financial_pg_engine.url.render_as_string(
                hide_password=False
            ),
        }
    ).model_copy(
        update={
            "financial": FinancialConfig(
                FINANCIAL_CORE_ENABLED=True,
                FINANCIAL_NEW_ORDERS_ENABLED=True,
            )
        }
    )
    container = Container(config)
    try:
        orders = container.build_bot_services()["order_service"]
        policy_service = orders.paid_item_service.policy_service
        loaded = await policy_service.load_policy(version)
        assert loaded.version == version
        assert loaded.allowed_clients == frozenset({seed["user"]})
        assert loaded.approved_by == seed["user"]
        assert loaded.selection_refund_window == timedelta(hours=1)
        command = dict(
            order_id=uuid4(),
            advertiser_id=seed["user"],
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.test/ugc",
            offer_text="Synthetic offer",
            barter_description=None,
            price=100,
            policy=loaded,
            order_created_at=seed["now"],
            now=seed["now"],
            selection_due_at=seed["now"] + timedelta(days=1),
            currency="RUB",
            accompaniment_ordinals=frozenset({1}),
            client_contact_reference="test-agreed-contact-v1",
            idempotency_key="real-di-quote",
        )
        order, quote = await orders.create_financial_order(**command)
        replay_order, replay_quote = await orders.create_financial_order(
            **command
        )
        assert order == replay_order
        assert quote == replay_quote
        assert len(quote.items) == 30
        assert quote.total_minor == 30 * 50_000 + 120_000
        with pytest.raises(ValueError, match="approved_policy_required"):
            await policy_service.load_policy("unknown-policy")
        # Stop takes effect on the same wired config, before another read.
        config.financial.new_orders_enabled = False
        with pytest.raises(ValueError, match="financial_disabled"):
            await policy_service.load_policy(version)
    finally:
        await container.dispose()

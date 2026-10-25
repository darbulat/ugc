"""Environment rules survive real publication, quotes and invoice validation."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.application.services.test_refund_policy_publication import config
from tests.postgres_financial import test_financial_items_schema as schema_tests
from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.services.financial_policy_publication import (
    FinancialPolicyDraft,
    FinancialPolicyPublicationService,
)
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.domain.enums import OrderType
from ugc_bot.financial_policy_config import _publish
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    FinancialPolicyVersionModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.financial_capture import (
    SqlAlchemyFinancialCaptureRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_policy import (
    SqlAlchemyFinancialPolicyRepository,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager


@pytest.fixture
def seed(financial_pg_engine, request):
    data = schema_tests.seed.__wrapped__(financial_pg_engine, request)
    with Session(financial_pg_engine) as db, db.begin():
        db.get(UserModel, data["user"]).admin = True
        db.add(AdvertiserProfileModel(user_id=data["user"], contact="test"))
    return data


def app_config(engine):
    cfg = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": engine.url.render_as_string(hide_password=False),
            "KAFKA_ENABLED": False,
            "REDIS_URL": "",
        }
    )
    cfg.financial = config()
    cfg.financial.core_enabled = cfg.financial.new_orders_enabled = True
    return cfg


def draft(cfg, seed, **changes):
    return FinancialPolicyDraft.from_environment(
        cfg.financial,
        **(
            dict(
                version=str(uuid4()),
                effective_from=seed["now"] + timedelta(minutes=1),
                allowed_clients=frozenset({seed["user"]}),
                terms_reference="terms:synthetic:refund-policy",
            )
            | changes
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", [None, "missing", "changed"])
async def test_real_publication_to_order_and_issued_invoice_ignores_new_env(
    financial_pg_engine, seed, tamper
):
    cfg = app_config(financial_pg_engine)
    chosen = draft(cfg, seed)
    published = await _publish(cfg, chosen, seed["user"])
    assert published.refund_rules == chosen.refund_rules
    # The application's configuration changes after approval, before quote.
    cfg.financial.selection_refund_window_seconds = 86400
    cfg.financial.accompaniment_refund_rates_bps = {"assigned": 0}
    container = Container(cfg)
    try:
        orders = container.build_bot_services()["order_service"]
        loaded = await orders.paid_item_service.policy_service.load_policy(
            chosen.version
        )
        now = chosen.effective_from + timedelta(seconds=1)
        args = dict(
            order_id=uuid4(),
            advertiser_id=seed["user"],
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.test/refund-policy",
            offer_text="Synthetic policy snapshot",
            barter_description=None,
            price=100,
            policy=loaded,
            order_created_at=now,
            now=now,
            selection_due_at=now + timedelta(days=1),
            currency="RUB",
            accompaniment_ordinals=frozenset({1}),
            client_contact_reference="test-contact-ref",
            idempotency_key="immutable-refund-quote",
        )
        _, quote = await orders.create_financial_order(**args)
        _, replay = await orders.create_financial_order(**args)
        assert replay == quote and quote.refund_rules == chosen.refund_rules
        capture = SqlAlchemyFinancialCaptureRepository(
            orders.paid_item_service.policy_service
        )
        async with container.transaction_manager.transaction() as session:
            db, order, items = await capture._locked(
                quote.order_id, seed["user"], session
            )
            await capture._policy(db, order, items, now, issuing=True)
            assert all(
                row.quote_payload["refund_rules"]
                == chosen.refund_rules.to_document()
                for row in items
            )
            if tamper is not None:
                original = dict(items[0].quote_payload)
                changed = dict(original)
                if tamper == "missing":
                    del changed["refund_rules"]
                else:
                    changed["refund_rules"] = (
                        cfg.financial.refund_rules().to_document()
                    )
                items[0].quote_payload = changed
                try:
                    with pytest.raises(
                        OrderCreationError, match="quote_policy_mismatch"
                    ):
                        await capture._policy(
                            db, order, items, now, issuing=True
                        )
                finally:
                    items[0].quote_payload = original
        # Issued invoices still validate after new sales are paused.
        cfg.financial.new_orders_enabled = False
        async with container.transaction_manager.transaction() as session:
            db, order, items = await capture._locked(
                quote.order_id, seed["user"], session
            )
            await capture._policy(db, order, items, now, issuing=False)
    finally:
        await container.dispose()


@pytest.mark.asyncio
async def test_concurrent_publication_and_revoked_admin_retry(
    financial_pg_engine, seed
):
    cfg, repo = (
        app_config(financial_pg_engine),
        SqlAlchemyFinancialPolicyRepository(),
    )
    chosen = draft(cfg, seed)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class Clock:
        def now(self):
            return seed["now"]

    service = FinancialPolicyPublicationService(
        repo, SessionTransactionManager(factory), Clock()
    )
    try:
        first, second = await asyncio.gather(
            service.publish(chosen, actor_id=seed["user"]),
            service.publish(chosen, actor_id=seed["user"]),
        )
        assert first == second
        with Session(financial_pg_engine) as db, db.begin():
            count = db.scalar(
                select(func.count())
                .select_from(FinancialPolicyVersionModel)
                .where(FinancialPolicyVersionModel.version == chosen.version)
            )
            assert count == 1
            db.get(UserModel, seed["user"]).admin = False
        with pytest.raises(PermissionError, match="active_admin_required"):
            await service.publish(chosen, actor_id=seed["user"])
        with pytest.raises(PermissionError, match="active_admin_required"):
            await service.publish(chosen, actor_id=uuid4())
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [None, "window_mismatch", "unknown_schema"])
async def test_reader_and_capture_reject_present_invalid_persisted_rules(
    financial_pg_engine, seed, invalid
):
    cfg, version = app_config(financial_pg_engine), str(uuid4())
    rules = cfg.financial.refund_rules().to_document()
    if invalid is None:
        rules = None
    elif invalid == "unknown_schema":
        rules["schema_version"] = 999
    with Session(financial_pg_engine) as db, db.begin():
        db.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=seed["user"],
                approved_at=seed["now"],
                effective_from=seed["now"],
                refund_window_seconds=3600
                if invalid == "window_mismatch"
                else 604800,
                rules={
                    "allowed_clients": [str(seed["user"])],
                    "terms_reference": "terms:test",
                    "refund_rules": rules,
                },
            )
        )
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    container = Container(cfg)
    try:
        service = container.build_bot_services()["order_service"]
        capture = SqlAlchemyFinancialCaptureRepository(
            service.paid_item_service.policy_service
        )
        from types import SimpleNamespace

        async with factory.begin() as session:
            with pytest.raises(ValueError, match="invalid_policy_document"):
                await SqlAlchemyFinancialPolicyRepository().load(
                    version, session=session
                )
            with pytest.raises(
                OrderCreationError, match="invalid_policy_document"
            ):
                await capture._policy(
                    session,
                    SimpleNamespace(financial_version=version),
                    [],
                    seed["now"],
                    issuing=False,
                )
    finally:
        await engine.dispose()
        await container.dispose()

"""Upgrade retains money and hashes while installing tariff guards."""

import os
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.helpers.financial_environment import (
    isolated_financial_database,
    upgrade_financial_schema,
)
from tests.postgres_financial.test_financial_items_schema import seed
from ugc_bot.infrastructure.db.models import (
    FinancialPolicyVersionModel,
    OrderItemModel,
    OrderModel,
)
from ugc_bot.infrastructure.db.order_intake_models import INTAKE_RECEIPTS


def test_upgrade_keeps_old_receipt_hash_and_rejects_forged_item_price():
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Explicit isolated PostgreSQL required")
    with isolated_financial_database(
        url, target_revision="0119_accompaniment_prior"
    ) as engine:
        data = seed.__wrapped__(engine, SimpleNamespace())
        due = data["now"] + timedelta(days=2)
        request_id = uuid4()
        with Session(engine) as db, db.begin():
            order = db.get(OrderModel, data["order"])
            order.bloggers_needed = 30
            order.financial_version = data["version"]
            order.created_at = data["now"]
            first = db.get(OrderItemModel, data["item"])
            first.selection_due_at = due
            first.quote_payload = {"terms_reference": "terms:retained"}
            for ordinal in range(2, 31):
                db.add(
                    OrderItemModel(
                        paid_item_id=uuid4(),
                        order_id=data["order"],
                        ordinal=ordinal,
                        currency="RUB",
                        selection_minor=50000,
                        accompaniment_minor=0,
                        policy_version=data["version"],
                        selection_due_at=due,
                        quote_key="retained",
                        quote_payload={"terms_reference": "terms:retained"},
                    )
                )
            db.flush()
            items = list(
                db.scalars(
                    select(OrderItemModel)
                    .where(OrderItemModel.order_id == data["order"])
                    .order_by(OrderItemModel.ordinal)
                )
            )
            payload = dict(
                request_id=str(request_id),
                order_id=str(data["order"]),
                honorarium_payment="paid_direct",
                currency="RUB",
                policy_version=data["version"],
                selection_due_at=due.isoformat(),
                terms_reference="terms:retained",
                items=[
                    dict(
                        paid_item_id=str(i.paid_item_id),
                        ordinal=i.ordinal,
                        selection_minor=i.selection_minor,
                        accompaniment_minor=i.accompaniment_minor,
                    )
                    for i in items
                ],
            )
            db.execute(
                insert(INTAKE_RECEIPTS).values(
                    request_id=request_id,
                    order_id=data["order"],
                    client_id=data["user"],
                    operation_key="legacy-retained",
                    payload_hash="c" * 64,
                    requested_at=data["now"],
                    result=payload,
                )
            )
        import importlib

        from sqlalchemy import text

        migration = importlib.import_module(
            "ugc_bot.infrastructure.db.migrations.versions.0120_variable_tariff"
        )
        # Recreate the actually deployed pre-0120 application function. Older
        # migration builders import source helpers, so fresh schemas alone
        # cannot prove that upgrade replaces an already installed old guard.
        historical_guard = migration.DOWNGRADE_SQL.split(
            "ALTER TABLE financial_refund_liability_assessments", 1
        )[0]
        with engine.begin() as db:
            db.execute(text(historical_guard))
            assert "covered_zero" not in db.scalar(
                text(
                    "SELECT pg_get_functiondef("
                    "'correction_check_application()'::regprocedure)"
                )
            )
        upgrade_financial_schema(engine, target_revision="0120_variable_tariff")
        with engine.connect() as db:
            assert "covered_zero" in db.scalar(
                text(
                    "SELECT pg_get_functiondef("
                    "'correction_check_application()'::regprocedure)"
                )
            )
        with Session(engine) as db:
            receipt = db.execute(select(INTAKE_RECEIPTS)).mappings().one()
            assert receipt["payload_hash"] == "c" * 64
            assert receipt["result"] == payload
            assert (
                db.get(FinancialPolicyVersionModel, data["version"]).rules == {}
            )
            assert (
                list(db.scalars(select(OrderItemModel.selection_minor)))
                == [50000] * 30
            )
        with (
            pytest.raises(DBAPIError, match="item_policy_tariff_mismatch"),
            Session(engine) as db,
            db.begin(),
        ):
            db.execute(
                update(OrderItemModel)
                .where(OrderItemModel.paid_item_id == data["item"])
                .values(selection_minor=79000)
            )

        # A historical-only database is still reversible without repricing it.
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        with engine.begin() as db:
            with Operations.context(MigrationContext.configure(db)):
                migration.downgrade()
            assert "actual_count <> 30" in db.scalar(
                text(
                    "SELECT pg_get_functiondef("
                    "'intake_validate_source()'::regprocedure)"
                )
            )
            assert db.scalar(
                text(
                    "SELECT to_regprocedure("
                    "'financial_policy_tariff_guard()') IS NULL"
                )
            )
        with Session(engine) as db:
            receipt = db.execute(select(INTAKE_RECEIPTS)).mappings().one()
            assert receipt["result"] == payload
            assert receipt["payload_hash"] == "c" * 64

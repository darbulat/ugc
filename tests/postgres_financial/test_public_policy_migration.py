"""Public admission extends correction guards without rewriting history."""

import importlib
import os

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from tests.helpers.financial_environment import isolated_financial_database


def test_migration_installs_and_restores_scope_guard():
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Explicit isolated PostgreSQL required")
    module = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0127_public_policy_scope"
    )
    with isolated_financial_database(  # noqa: SIM117
        url, target_revision="0126_followup_new_orders"
    ) as engine:
        with (
            engine.begin() as db,
            Operations.context(MigrationContext.configure(db)),
        ):
            before = db.scalar(
                text(
                    "SELECT pg_get_functiondef("
                    "'correction_validate_authority(jsonb)'::regprocedure)"
                )
            )
            assert "all_clients" not in before
            module.upgrade()
            after = db.scalar(
                text(
                    "SELECT pg_get_functiondef("
                    "'correction_validate_authority(jsonb)'::regprocedure)"
                )
            )
            assert "all_clients" in after
            assert "'true'::jsonb" in after
            assert "allowed_clients" in after
            module.downgrade()
            assert (
                db.scalar(
                    text(
                        "SELECT pg_get_functiondef("
                        "'correction_validate_authority(jsonb)'::regprocedure)"
                    )
                )
                == before
            )


def test_public_policy_prevents_downgrade(financial_pg_engine):
    from datetime import datetime, timezone
    from uuid import uuid4

    from sqlalchemy.orm import Session

    from ugc_bot.domain.enums import MessengerType, UserStatus
    from ugc_bot.infrastructure.db.models import (
        FinancialPolicyVersionModel,
        UserModel,
    )

    module = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0127_public_policy_scope"
    )
    now = datetime.now(timezone.utc)
    user = uuid4()
    with Session(financial_pg_engine) as db, db.begin():
        db.add(
            UserModel(
                user_id=user,
                messenger_type=MessengerType.TELEGRAM,
                username="public-policy-admin",
                status=UserStatus.ACTIVE,
            )
        )
        db.flush()
        db.add(
            FinancialPolicyVersionModel(
                version="public-policy-test",
                approved_by=user,
                approved_at=now,
                effective_from=now,
                refund_window_seconds=604800,
                rules={
                    "selection_minor": 50000,
                    "accompaniment_minor": 120000,
                    "allowed_clients": [],
                    "all_clients": True,
                    "terms_reference": "https://example.test/terms",
                },
            )
        )
    with (
        financial_pg_engine.begin() as db,
        Operations.context(MigrationContext.configure(db)),
        pytest.raises(
            RuntimeError, match="Cannot downgrade while public policies exist"
        ),
    ):
        module.downgrade()


@pytest.mark.parametrize(
    ("flag", "clients", "allowed"),
    [
        ("absent", ["client"], True),
        (False, ["client"], True),
        (False, [], False),
        (True, [], True),
        (True, ["client"], False),
        ("true", ["client"], False),
        (1, ["client"], False),
        ("absent", [], False),
        (None, ["client"], False),
    ],
)
def test_sql_policy_scope_fails_closed(
    financial_pg_engine, flag, clients, allowed
):
    import json
    from uuid import uuid4

    module = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0127_public_policy_scope"
    )
    client = uuid4()
    rules = {
        "allowed_clients": [
            str(client) if c == "client" else c for c in clients
        ]
    }
    if flag != "absent":
        rules["all_clients"] = flag
    with financial_pg_engine.connect() as db:
        result = db.scalar(
            text(
                "SELECT "
                + module.POLICY_ALLOWED_SQL
                + " FROM (SELECT CAST(:rules AS jsonb) AS rules) policy "
                "CROSS JOIN (SELECT CAST(:client AS uuid) AS client_id) "
                "request"
            ),
            {"rules": json.dumps(rules), "client": str(client)},
        )
    assert result is allowed

"""Upgrade the deployed followup schema without losing delivery history."""

import os
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from tests.helpers.financial_environment import (
    isolated_financial_database,
    upgrade_financial_schema,
)


def downgrade(engine):
    env = dict(os.environ)
    env.pop("MIGRATION_SCHEMA", None)
    env["DATABASE_URL"] = engine.url.render_as_string(hide_password=False)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from alembic import command; from alembic.config import Config; "
            "command.downgrade(Config('alembic.ini'), "
            "'0125_order_notice_leases')",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_upgrade_preserves_stopped_history_and_enforces_one_active_series():
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Explicit isolated PostgreSQL required")
    with isolated_financial_database(
        url, target_revision="0125_order_notice_leases"
    ) as engine:
        old, user, job, new = (uuid4() for _ in range(4))
        with engine.begin() as db:
            # Revision 0121 imports current metadata. Restore the actual
            # pre-0126 structure before exercising the new migration.
            db.execute(text("DROP TABLE IF EXISTS client_followup_intents"))
            db.execute(
                text("DROP INDEX IF EXISTS uq_client_followup_active_user")
            )
            db.execute(
                text(
                    "ALTER TABLE client_followup_series "
                    "DROP COLUMN IF EXISTS stopped_at"
                )
            )
            db.execute(
                text(
                    "ALTER TABLE client_followup_series "
                    "ADD CONSTRAINT followup_user_old_key UNIQUE(user_id)"
                )
            )
            db.execute(
                text(
                    "INSERT INTO client_followup_series "
                    "(series_id,user_id,generation,created_at,last_activity_at,"
                    "opted_out,stop_reason) "
                    "VALUES (:series,:user,1,now(),now(),false,'paid')"
                ),
                {"series": old, "user": user},
            )
            db.execute(
                text(
                    "INSERT INTO customer_workflow_deliveries "
                    "(job_id,series_id,recipient_id,stage,generation,"
                    "due_at,state) "
                    "VALUES (:job,:series,:user,1,1,now(),'unknown')"
                ),
                {"job": job, "series": old, "user": user},
            )
        upgrade_financial_schema(
            engine, target_revision="0126_followup_new_orders"
        )
        with engine.begin() as db:
            stopped_at = db.scalar(
                text(
                    "SELECT stopped_at FROM client_followup_series "
                    "WHERE series_id=:id"
                ),
                {"id": old},
            )
            assert stopped_at is not None
            assert (
                db.scalar(
                    text(
                        "SELECT state FROM customer_workflow_deliveries "
                        "WHERE job_id=:id"
                    ),
                    {"id": job},
                )
                == "unknown"
            )
            db.execute(
                text(
                    "INSERT INTO client_followup_series "
                    "(series_id,user_id,generation,created_at,last_activity_at,"
                    "opted_out) VALUES (:series,:user,1,now(),now(),false)"
                ),
                {"series": new, "user": user},
            )
        with pytest.raises(IntegrityError), engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO client_followup_series "
                    "(series_id,user_id,generation,created_at,last_activity_at,"
                    "opted_out) VALUES (:series,:user,1,now(),now(),false)"
                ),
                {"series": uuid4(), "user": user},
            )
        refused = downgrade(engine)
        assert refused.returncode != 0
        assert "without losing history" in refused.stderr
        with engine.begin() as db:
            assert (
                db.scalar(
                    text(
                        "SELECT count(*) FROM client_followup_series "
                        "WHERE user_id=:user"
                    ),
                    {"user": user},
                )
                == 2
            )
            db.execute(
                text("DELETE FROM client_followup_series WHERE series_id=:id"),
                {"id": new},
            )
            db.execute(
                text(
                    "INSERT INTO client_followup_intents "
                    "(user_id,intent_id,series_id,recorded_at) "
                    "VALUES (:user,:intent,:series,now())"
                ),
                {"user": user, "intent": uuid4(), "series": old},
            )
        refused = downgrade(engine)
        assert refused.returncode != 0
        assert "without losing intent history" in refused.stderr
        with engine.begin() as db:
            assert (
                db.scalar(text("SELECT count(*) FROM client_followup_intents"))
                == 1
            )
            db.execute(text("DELETE FROM client_followup_intents"))
        restored = downgrade(engine)
        assert restored.returncode == 0, restored.stderr
        assert "stopped_at" not in {
            column["name"]
            for column in inspect(engine).get_columns("client_followup_series")
        }
        upgrade_financial_schema(
            engine, target_revision="0126_followup_new_orders"
        )
        with engine.connect() as db:
            assert (
                db.scalar(
                    text(
                        "SELECT state FROM customer_workflow_deliveries "
                        "WHERE job_id=:id"
                    ),
                    {"id": job},
                )
                == "unknown"
            )

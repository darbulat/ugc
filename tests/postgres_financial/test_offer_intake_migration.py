"""Migration expires old full intakes without reopening closed orders."""

import os
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import text

from tests.helpers.financial_environment import isolated_financial_database


def test_reserve_migration_preserves_old_orders_and_refuses_deadline_loss(
    financial_pg_engine,
):
    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="0147_instagram_discovery",
    ) as engine:
        client, full, partial, closed = [uuid4() for _ in range(4)]
        with engine.begin() as db:
            db.execute(
                text("""INSERT INTO users
                (user_id, messenger_type, username, status)
                VALUES (:id, 'telegram', 'migration-test', 'active')"""),
                {"id": client},
            )
            for order_id, count, status in (
                (full, 1, "active"),
                (partial, 2, "active"),
                (closed, 1, "closed"),
            ):
                db.execute(
                    text("""INSERT INTO orders
                    (order_id, advertiser_id, product_link, offer_text,
                     price, bloggers_needed, status)
                    VALUES (:id, :client, 'test', 'Migration', 500, :count,
                            CAST(:status AS order_status))"""),
                    {
                        "id": order_id,
                        "client": client,
                        "count": count,
                        "status": status,
                    },
                )
                db.execute(
                    text("""INSERT INTO offer_dispatches
                    (order_id, blogger_id, accepted, in_offer)
                    VALUES (:id, :creator, true, true)"""),
                    {"id": order_id, "creator": client},
                )
        env = dict(
            os.environ,
            DATABASE_URL=engine.url.render_as_string(hide_password=False),
        )
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            env=env,
            text=True,
            capture_output=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        with engine.connect() as db:
            values = {
                row.order_id: row
                for row in db.execute(
                    text("""
                SELECT order_id, status, offer_reserve_until,
                       offer_reserve_until <= CURRENT_TIMESTAMP AS expired
                FROM orders
            """)
                )
            }
        assert values[full].expired
        assert values[partial].offer_reserve_until is None
        assert values[closed].offer_reserve_until is None
        assert values[full].status == "active"
        assert values[closed].status == "closed"
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "-1"],
            env=env,
            text=True,
            capture_output=True,
            timeout=60,
        )
        assert result.returncode != 0
        assert "reserve_deadlines_require_retention_decision" in result.stderr

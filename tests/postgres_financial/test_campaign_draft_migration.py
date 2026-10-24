"""Actual parent setup state, lossless roundtrip and populated retention."""

import os
import subprocess
import sys

import pytest
from sqlalchemy import text

from tests.helpers.financial_environment import isolated_financial_database


def retained_command(db):
    user_id = db.scalar(
        text(
            "INSERT INTO users "
            "(telegram_id,username,messenger_type,status,admin) VALUES "
            "('901001','synthetic-migration','telegram','active',false) "
            "RETURNING user_id"
        )
    )
    db.execute(
        text(
            "INSERT INTO campaign_draft_commands "
            "(actor_id,operation_key,payload_hash,recorded_at,result) VALUES "
            "(:actor,'synthetic-migration',:hash,now(),'{}'::jsonb)"
        ),
        {"actor": user_id, "hash": "a" * 64},
    )


def migrate(engine, action, target):
    env = os.environ.copy()
    env["DATABASE_URL"] = engine.url.render_as_string(hide_password=False)
    return subprocess.run(
        [sys.executable, "-m", "alembic", action, target],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_actual_parent_schema_roundtrip_and_retained_history_refusal(
    financial_pg_engine,
):
    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="messenger_linking_v1",
    ) as engine:
        with engine.connect() as db:
            assert (
                db.scalar(text("SELECT to_regclass('campaign_drafts')")) is None
            )
        up = migrate(engine, "upgrade", "campaign_drafts_v1")
        assert up.returncode == 0, up.stderr
        down = migrate(engine, "downgrade", "messenger_linking_v1")
        assert down.returncode == 0, down.stderr
        up = migrate(engine, "upgrade", "campaign_drafts_v1")
        assert up.returncode == 0, up.stderr
        with engine.begin() as db:
            # A command receipt is retained history even before any revision.
            retained_command(db)
        refused = migrate(engine, "downgrade", "messenger_linking_v1")
        assert (
            refused.returncode != 0
            and "Cannot discard immutable campaign draft history"
            in refused.stderr
        )


def test_actual_migration_operations_retain_populated_command_history(
    financial_pg_engine,
):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from ugc_bot.infrastructure.db.migrations.versions import campaign_drafts_v1

    with (
        isolated_financial_database(
            os.environ["FINANCIAL_TEST_DATABASE_URL"],
            target_revision="messenger_linking_v1",
        ) as engine,
        engine.begin() as db,
    ):
        with Operations.context(MigrationContext.configure(db)):
            campaign_drafts_v1.upgrade()
            campaign_drafts_v1.downgrade()
            campaign_drafts_v1.upgrade()
            retained_command(db)
            with pytest.raises(RuntimeError, match="immutable campaign"):
                campaign_drafts_v1.downgrade()
        assert (
            db.scalar(text("SELECT count(*) FROM campaign_draft_commands")) == 1
        )


@pytest.mark.asyncio
async def test_real_parent_schema_draft_adapter_is_unavailable(
    financial_pg_engine,
):
    from ugc_bot.config import AppConfig
    from ugc_bot.container import Container

    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="messenger_linking_v1",
    ) as engine:
        config = AppConfig.model_validate(
            {
                "BOT_TOKEN": "test-token",
                "DATABASE_URL": engine.url.render_as_string(
                    hide_password=False
                ),
                "KAFKA_ENABLED": False,
                "USE_REDIS_STORAGE": False,
                "REDIS_URL": "",
            }
        )
        container = Container(config)
        try:
            repo = container.build_bot_services()[
                "campaign_review_service"
            ].repository
            async with container.transaction_manager.transaction() as db:
                with pytest.raises(ValueError, match="drafts_unavailable"):
                    await repo.command(None, "synthetic-parent", session=db)
        finally:
            await container.session_factory.kw["bind"].dispose()

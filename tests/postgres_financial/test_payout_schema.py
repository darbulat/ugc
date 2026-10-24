"""Separate migrated payout authority preserves legacy request identity."""

from sqlalchemy import inspect


def test_payout_authority_and_protocol_are_migrated(financial_pg_engine):
    schema = inspect(financial_pg_engine)
    assert {
        "financial_payout_requirements",
        "financial_payout_requisites",
        "financial_payout_requests",
        "financial_payout_allocations",
        "financial_payout_events",
        "financial_payout_states",
        "financial_payout_intents",
        "financial_payout_outcomes",
        "financial_payout_settlements",
        "financial_payout_movement_links",
        "financial_payout_commands",
    } <= set(schema.get_table_names())
    assert "payout_protocol" in {
        c["name"] for c in schema.get_columns("payout_requests")
    }


def test_both_legacy_daily_indexes_keep_legacy_only_semantics(
    financial_pg_engine,
):
    from sqlalchemy import text

    with financial_pg_engine.connect() as db:
        definitions = dict(
            db.execute(
                text(
                    "SELECT indexname,indexdef FROM pg_indexes "
                    "WHERE schemaname=current_schema() "
                    "AND tablename='payout_requests'"
                )
            ).all()
        )
    assert (
        "payout_protocol IS NULL"
        in definitions["uq_payout_requests_user_id_request_date"]
    )
    assert (
        "payout_protocol IS NULL"
        in definitions["uq_payout_request_user_currency_day"]
    )
    assert "cancelled" in definitions["uq_payout_request_user_currency_day"]


def test_empty_payout_revision_can_round_trip_without_descendant_teardown():
    import os

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from tests.helpers.financial_environment import isolated_financial_database
    from ugc_bot.infrastructure.db.migrations.versions import (
        financial_payout_v1,
    )

    with (
        isolated_financial_database(
            os.environ["FINANCIAL_TEST_DATABASE_URL"],
            target_revision="financial_payout_v1",
        ) as engine,
        engine.begin() as db,
        Operations.context(MigrationContext.configure(db)),
    ):
        financial_payout_v1.downgrade()
        assert "financial_payout_requests" not in inspect(db).get_table_names()
        financial_payout_v1.upgrade()
        assert "financial_payout_requests" in inspect(db).get_table_names()

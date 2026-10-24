"""SQLite setup for legacy UI tests, separate from real PostgreSQL coverage."""

from sqlalchemy import MetaData, Table


def legacy_sqlite_tables(metadata: MetaData) -> list[Table]:
    # These legacy fixtures do not exercise PostgreSQL financial protocols.
    # Their immutable DDL and money rules are tested by actual Alembic upgrades
    # in tests/postgres_financial, without weakening constraints for SQLite.
    excluded = {
        "outbox_events",
        "blogger_profiles",
        "instagram_stats",
        "payout_requests",
    }
    return [
        table
        for table in metadata.tables.values()
        if table.name not in excluded
        and not table.name.startswith(
            (
                "financial_payout_",
                "campaign_digest_",
                "messenger_link_",
                "financial_correction_",
                "financial_refund_",
                "financial_physical_proof_",
            )
        )
    ]

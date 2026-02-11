-- Create publication for logical replication to Beget cloud DB.
-- Run once on the publisher (local db) after enabling wal_level=logical.
-- Example: docker compose exec db psql -U ugc -d ugc -f - < scripts/setup_replication_publication.sql
-- Or from inside app container: psql $DATABASE_URL -f scripts/setup_replication_publication.sql

CREATE PUBLICATION ugc_pub FOR ALL TABLES;

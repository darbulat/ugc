#!/bin/sh
# Print PITR recovery steps and optionally the latest base backup key.
# Does not replace the data volume; only outputs commands and instructions.
# Usage: run from db_backup container or with same env (S3_*, POSTGRES_*).

set -e

echo "=== PITR recovery: list base backups in S3 ==="
python3 /app/scripts/base_backup_db.py --list-s3 || true

echo ""
echo "=== Recovery steps (see docs/BACKUP.md for full procedure) ==="
echo "1. Stop app and db: docker compose stop app app_2 admin ... db pgbouncer db_backup"
echo "2. Download latest base backup from S3 (key: base_backup/ugc_base_YYYYMMDD_HHMMSS.tar.gz):"
echo "   aws --endpoint-url \$S3_ENDPOINT_URL s3 cp s3://\$S3_BUCKET/<KEY> - | tar -xzf - -C /path/to/pgdata"
echo "3. In PGDATA create postgresql.auto.conf with:"
echo "   restore_command = 'aws --endpoint-url \$S3_ENDPOINT_URL s3 cp s3://\$S3_BUCKET/wal_archive/%f %p'"
echo "   recovery_target_time = 'YYYY-MM-DD HH:MM:SS'  # optional"
echo "4. touch /path/to/pgdata/recovery.signal"
echo "5. Point db volume to PGDATA and: docker compose up -d db"
echo ""

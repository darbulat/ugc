#!/bin/sh
# Cron script for automatic database backups

set -e

# Default values (can be overridden by environment variables)
POSTGRES_HOST="${POSTGRES_HOST:-db}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-ugc}"
POSTGRES_USER="${POSTGRES_USER:-ugc}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"
BACKUP_SCHEDULE="${BACKUP_SCHEDULE:-0 2 * * *}"  # Default: daily at 2 AM

if [ -z "$POSTGRES_PASSWORD" ]; then
    echo "Error: POSTGRES_PASSWORD is not set" >&2
    exit 1
fi

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Run backup script
python3 /app/scripts/backup_db.py \
    --host "$POSTGRES_HOST" \
    --port "$POSTGRES_PORT" \
    --database "$POSTGRES_DB" \
    --user "$POSTGRES_USER" \
    --password "$POSTGRES_PASSWORD" \
    --output-dir "$BACKUP_DIR" \
    --cleanup-days "$BACKUP_KEEP_DAYS"

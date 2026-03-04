#!/bin/sh
# Loop script for automatic database backups (pg_dump + optional PITR base backup).

set -e

# Default values (can be overridden by environment variables)
POSTGRES_HOST="${POSTGRES_HOST:-db}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-ugc}"
POSTGRES_USER="${POSTGRES_USER:-ugc}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"
BACKUP_INTERVAL_HOURS="${BACKUP_INTERVAL_HOURS:-24}"
BASE_BACKUP_INTERVAL_HOURS="${BASE_BACKUP_INTERVAL_HOURS:-24}"
LAST_BASE_BACKUP_MARKER="${BACKUP_DIR}/.last_base_backup"

if [ -z "$POSTGRES_PASSWORD" ]; then
    echo "Error: POSTGRES_PASSWORD is not set" >&2
    exit 1
fi

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Convert hours to seconds
BACKUP_INTERVAL_SECONDS=$((BACKUP_INTERVAL_HOURS * 3600))
BASE_BACKUP_INTERVAL_SECONDS=$((BASE_BACKUP_INTERVAL_HOURS * 3600))

echo "Starting backup service..."
echo "Backup interval: ${BACKUP_INTERVAL_HOURS} hours"
echo "Base backup interval: ${BASE_BACKUP_INTERVAL_HOURS} hours (PITR)"
echo "Backup directory: ${BACKUP_DIR}"
echo "Keep backups for: ${BACKUP_KEEP_DAYS} days"

_run_base_backup_if_due() {
    if [ -z "${S3_ACCESS_KEY_ID}" ]; then
        return 0
    fi
    need_run=1
    if [ -f "$LAST_BASE_BACKUP_MARKER" ]; then
        now=$(date +%s)
        last=$(stat -c %Y "$LAST_BASE_BACKUP_MARKER" 2>/dev/null) || last=0
        [ -n "$last" ] && [ $((now - last)) -lt "$BASE_BACKUP_INTERVAL_SECONDS" ] && need_run=0
    fi
    [ "$need_run" -eq 0 ] && return 0
    if python3 /app/scripts/base_backup_db.py \
        --host "$POSTGRES_HOST" \
        --port "$POSTGRES_PORT" \
        --user "$POSTGRES_USER" \
        --password "$POSTGRES_PASSWORD" \
        --output-dir "$BACKUP_DIR"; then
        touch "$LAST_BASE_BACKUP_MARKER"
    fi
}

# Run logical backup and optionally base backup (PITR) on start
python3 /app/scripts/backup_db.py \
    --host "$POSTGRES_HOST" \
    --port "$POSTGRES_PORT" \
    --database "$POSTGRES_DB" \
    --user "$POSTGRES_USER" \
    --password "$POSTGRES_PASSWORD" \
    --output-dir "$BACKUP_DIR" \
    --cleanup-days "$BACKUP_KEEP_DAYS"
_run_base_backup_if_due

# Then run backups in a loop
while true; do
    sleep "$BACKUP_INTERVAL_SECONDS"
    python3 /app/scripts/backup_db.py \
        --host "$POSTGRES_HOST" \
        --port "$POSTGRES_PORT" \
        --database "$POSTGRES_DB" \
        --user "$POSTGRES_USER" \
        --password "$POSTGRES_PASSWORD" \
        --output-dir "$BACKUP_DIR" \
        --cleanup-days "$BACKUP_KEEP_DAYS"
    _run_base_backup_if_due
done

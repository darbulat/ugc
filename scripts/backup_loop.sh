#!/bin/sh
# Loop script for automatic database backups (logical + PITR)

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
PITR_ENABLED="${PITR_ENABLED:-true}"
BASE_BACKUP_DIR="${BASE_BACKUP_DIR:-/backups/base}"
WAL_ARCHIVE_DIR="${WAL_ARCHIVE_DIR:-/wal_archive}"
# WAL upload interval in seconds (default: 5 minutes)
WAL_UPLOAD_INTERVAL="${WAL_UPLOAD_INTERVAL:-300}"

if [ -z "$POSTGRES_PASSWORD" ]; then
    echo "Error: POSTGRES_PASSWORD is not set" >&2
    exit 1
fi

# Create backup directories
mkdir -p "$BACKUP_DIR"
mkdir -p "$BASE_BACKUP_DIR"

# Convert hours to seconds
BACKUP_INTERVAL_SECONDS=$((BACKUP_INTERVAL_HOURS * 3600))

echo "Starting backup service..."
echo "Backup interval: ${BACKUP_INTERVAL_HOURS} hours"
echo "Backup directory: ${BACKUP_DIR}"
echo "Keep backups for: ${BACKUP_KEEP_DAYS} days"
echo "PITR enabled: ${PITR_ENABLED}"

# --- Helper: run logical pg_dump backup ---
run_logical_backup() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') Running logical backup (pg_dump)..."
    python3 /app/scripts/backup_db.py \
        --host "$POSTGRES_HOST" \
        --port "$POSTGRES_PORT" \
        --database "$POSTGRES_DB" \
        --user "$POSTGRES_USER" \
        --password "$POSTGRES_PASSWORD" \
        --output-dir "$BACKUP_DIR" \
        --cleanup-days "$BACKUP_KEEP_DAYS"
}

# --- Helper: run base backup for PITR ---
run_base_backup() {
    if [ "$PITR_ENABLED" != "true" ]; then
        return
    fi
    echo "$(date '+%Y-%m-%d %H:%M:%S') Running base backup (pg_basebackup)..."
    python3 /app/scripts/base_backup.py \
        --host "$POSTGRES_HOST" \
        --port "$POSTGRES_PORT" \
        --user "$POSTGRES_USER" \
        --password "$POSTGRES_PASSWORD" \
        --output-dir "$BASE_BACKUP_DIR" \
        --cleanup-days "$BACKUP_KEEP_DAYS" || \
    echo "Warning: base backup failed, continuing..."
}

# --- Helper: upload WAL files to S3 ---
upload_wal_files() {
    if [ "$PITR_ENABLED" != "true" ]; then
        return
    fi
    python3 /app/scripts/wal_uploader.py 2>&1 || \
    echo "Warning: WAL upload failed, continuing..."
}

# --- WAL upload background loop ---
wal_upload_loop() {
    while true; do
        sleep "$WAL_UPLOAD_INTERVAL"
        upload_wal_files
    done
}

# Start WAL upload loop in background (if PITR enabled)
if [ "$PITR_ENABLED" = "true" ]; then
    echo "Starting WAL upload loop (interval: ${WAL_UPLOAD_INTERVAL}s)..."
    wal_upload_loop &
    WAL_PID=$!
fi

# Run backups immediately on start
run_logical_backup
run_base_backup
upload_wal_files

# Then run backups in a loop
while true; do
    sleep "$BACKUP_INTERVAL_SECONDS"
    run_logical_backup
    run_base_backup
    upload_wal_files
done

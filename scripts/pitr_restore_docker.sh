#!/bin/bash
# PITR restore orchestrator for Docker Compose.
#
# Runs entirely through Docker — no host root access required.
# Stops all services, clears PGDATA, restores from S3 base backup + WAL,
# fixes permissions, then restarts everything.
#
# Usage:
#   bash scripts/pitr_restore_docker.sh                              # restore to latest
#   bash scripts/pitr_restore_docker.sh --target-time "2026-03-13 10:00:00"
#   bash scripts/pitr_restore_docker.sh --list                       # list available backups

set -euo pipefail

cd "$(dirname "$0")/.."

TARGET_TIME=""
LIST_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --target-time|-t) TARGET_TIME="$2"; shift 2 ;;
        --list|-l)        LIST_ONLY=true; shift ;;
        *) echo "Usage: $0 [--list] [--target-time 'YYYY-MM-DD HH:MM:SS']"; exit 1 ;;
    esac
done

# Volume names follow Docker Compose convention: <project>_<volume>
PROJECT=$(basename "$(pwd)")
PGDATA_VOLUME="${PROJECT}_postgres_data"
WAL_VOLUME="${PROJECT}_wal_archive"
IMAGE="${PROJECT}-db_backup:latest"

_run_pitr() {
    docker run --rm \
        -v "${PGDATA_VOLUME}:/var/lib/postgresql/data" \
        -v "${WAL_VOLUME}:/wal_archive" \
        --env-file .env \
        "${IMAGE}" \
        python3 /app/scripts/pitr_restore.py "$@"
}

if $LIST_ONLY; then
    _run_pitr --list
    exit 0
fi

echo "=== PITR Restore ==="
[[ -n "$TARGET_TIME" ]] && echo "Target time : $TARGET_TIME" || echo "Target time : latest (full restore)"
echo ""
read -rp "WARNING: This will stop ALL services and overwrite the database. Continue? (yes/no): " answer
[[ "$answer" == "yes" ]] || { echo "Cancelled."; exit 0; }

APP_SERVICES="app app_2 admin kafka_consumer outbox_processor feedback_scheduler \
    role_reminder_scheduler instagram_stats_scheduler \
    instagram_stats_collector_scheduler instagram_webhook db_backup"

echo ""
echo ">>> Stopping application services..."
# shellcheck disable=SC2086
docker compose stop $APP_SERVICES 2>/dev/null || true

echo ">>> Stopping pgbouncer and PostgreSQL..."
docker compose stop pgbouncer db

echo ">>> Clearing PGDATA..."
docker run --rm -v "${PGDATA_VOLUME}:/pgdata" alpine:3.20 \
    sh -c "find /pgdata -mindepth 1 -delete 2>/dev/null; echo 'PGDATA cleared'"

echo ">>> Downloading backup from S3 and configuring recovery..."
RESTORE_ARGS=(--pgdata /var/lib/postgresql/data --wal-dir /wal_archive --confirm)
[[ -n "$TARGET_TIME" ]] && RESTORE_ARGS+=(--target-time "$TARGET_TIME")
_run_pitr "${RESTORE_ARGS[@]}"

echo ">>> Fixing PGDATA permissions..."
docker run --rm -v "${PGDATA_VOLUME}:/pgdata" alpine:3.20 \
    chown -R 999:999 /pgdata

echo ">>> Starting PostgreSQL (recovery mode)..."
docker compose start db

echo ">>> Waiting for PostgreSQL to become ready..."
for i in $(seq 1 60); do
    if docker compose exec -T db pg_isready -U "${POSTGRES_USER:-ugc}" -q 2>/dev/null; then
        break
    fi
    [[ $i -eq 60 ]] && { echo "ERROR: PostgreSQL did not become ready in time"; exit 1; }
    sleep 2
done

echo ">>> Starting remaining services..."
docker compose start pgbouncer
sleep 2
# shellcheck disable=SC2086
docker compose start $APP_SERVICES

echo ""
echo "=== Restore complete ==="
docker compose exec -T db psql -U "${POSTGRES_USER:-ugc}" -d "${POSTGRES_DB:-ugc}" \
    -c "SELECT pg_is_in_recovery() AS in_recovery, now() AS restored_at;"

#!/bin/sh
# Entrypoint for PostgreSQL with optional PITR WAL archiving.
# When PITR_ENABLED=true, sets archive_mode and archive_command (wrapper and script live in /scripts/).
# $@ is the command from docker-compose (e.g. postgres -c wal_level=...).

set -e

if [ "$PITR_ENABLED" = "true" ] || [ "$PITR_ENABLED" = "1" ]; then
    shift
    exec postgres \
        -c "archive_mode=on" \
        -c "archive_command='/scripts/archive_wal_wrapper.sh %p %f'" \
        "$@"
else
    exec "$@"
fi

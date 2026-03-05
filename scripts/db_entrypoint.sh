#!/bin/sh
# Entrypoint for PostgreSQL with optional PITR WAL archiving.
# When PITR_ENABLED=true, appends archive_mode=on and archive_command so that
# WAL segments are uploaded to S3 via scripts/archive_wal.py.
# $@ is the command from docker-compose (e.g. postgres -c wal_level=...).

set -e

if [ "$PITR_ENABLED" = "true" ] || [ "$PITR_ENABLED" = "1" ]; then
    shift
    exec postgres \
        -c "archive_mode=on" \
        -c "archive_command='/usr/bin/python3 /scripts/archive_wal.py %p %f'" \
        "$@"
else
    exec "$@"
fi

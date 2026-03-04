#!/bin/sh
# Entrypoint for PostgreSQL with optional PITR WAL archiving.
# When PITR_ENABLED=true, appends archive_mode=on and archive_command so that
# WAL segments are uploaded to S3 via scripts/archive_wal.py.

set -e

if [ "$PITR_ENABLED" = "true" ] || [ "$PITR_ENABLED" = "1" ]; then
    exec postgres "$@" \
        -c "archive_mode=on" \
        -c "archive_command='python3 /scripts/archive_wal.py %p %f'"
else
    exec postgres "$@"
fi

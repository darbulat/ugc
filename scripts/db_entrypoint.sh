#!/bin/sh
# Entrypoint for PostgreSQL with optional PITR WAL archiving.
# When PITR_ENABLED=true, copies archive scripts into PGDATA/scripts (so archive_command
# finds them if the archiver runs in a chroot), then sets archive_mode and archive_command.
# $@ is the command from docker-compose (e.g. postgres -c wal_level=...).

set -e

if [ "$PITR_ENABLED" = "true" ] || [ "$PITR_ENABLED" = "1" ]; then
    PGDATA="${PGDATA:-/var/lib/postgresql/data}"
    mkdir -p "$PGDATA/scripts"
    cp -f /usr/local/bin/archive_wal_wrapper.sh /scripts/archive_wal.py "$PGDATA/scripts/"
    chmod 755 "$PGDATA/scripts/archive_wal_wrapper.sh" "$PGDATA/scripts/archive_wal.py"
    shift
    exec postgres \
        -c "archive_mode=on" \
        -c "archive_command='/scripts/archive_wal_wrapper.sh %p %f'" \
        "$@"
else
    exec "$@"
fi

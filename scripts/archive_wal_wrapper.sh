#!/bin/sh
# Wrapper for archive_wal.py so archive_command has a single path and a safe PATH.
# PostgreSQL may run archive_command with an empty or minimal PATH.
export PATH=/usr/local/bin:/usr/bin:/bin
exec python3 /scripts/archive_wal.py "$@"

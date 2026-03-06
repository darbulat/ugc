#!/bin/sh
# Wrapper for archive_wal.py; run from PGDATA/scripts so archive_command finds it (possible chroot).
export PATH=/usr/local/bin:/usr/bin:/bin
SCRIPT_DIR=$(dirname "$0")
exec python3 "$SCRIPT_DIR/archive_wal.py" "$@"

#!/bin/bash
# Runs only inside the private recovery RootDirectory.
set -euo pipefail
export PATH=/usr/bin:/bin
name="$1"
destination="$2"
[[ "$name" =~ ^[0-9A-F]{24}$ ]] || exit 1
expected=$(awk -v f="$name.age" '$2 == f {print $1}' /restore/wal-checksums)
[[ "$expected" =~ ^[0-9a-f]{64}$ ]] || exit 1
printf '%s  %s\n' "$expected" "/archive/wal/$name.age" | sha256sum --check --status
pending="${destination}.pitr-pending"
trap 'rm -f -- "$pending"' EXIT
/tools/age --decrypt --identity "$CREDENTIALS_DIRECTORY/identity" \
  "/archive/wal/$name.age" | gzip --decompress | head -c 16777217 > "$pending"
[[ $(stat -c '%s' "$pending") == 16777216 ]] || exit 1
mv -- "$pending" "$destination"

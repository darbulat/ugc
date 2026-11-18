#!/usr/bin/env bash
set -euo pipefail
image="$1"
archive="$2"
docker run --rm --network none --read-only --memory 256m --memory-swap 256m \
  --pids-limit 64 --tmpfs /tmp:exec,size=64m -v "$PWD:/repo:ro" \
  -v "$archive:/age.tar.gz:ro" "$image" \
  python /repo/tests/monitoring/pitr_installer_check.py /age.tar.gz

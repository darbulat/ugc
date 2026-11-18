#!/usr/bin/env bash
set -euo pipefail
image="$1"
root=$(pwd)
fixture=$(mktemp -d)
name="ugc-pitr-runtime-${RANDOM}-$$"
pg_image="postgis/postgis@sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5"
cleanup() {
    docker rm -f -v "${name}-export" "${name}-client" >/dev/null 2>&1 || true
    docker volume rm "${name}-files" >/dev/null 2>&1 || true
    rm -rf "$fixture"
}
trap cleanup EXIT
docker create --name "${name}-export" --network none "$pg_image" >/dev/null
docker export --output "$fixture/public-image.tar" "${name}-export"
docker volume create "${name}-files" >/dev/null
docker run --rm --name "${name}-client" --network none --read-only \
  --memory 512m --memory-swap 512m --pids-limit 64 --tmpfs /tmp:size=32m \
  -e TMPDIR=/work -v "${name}-files:/work" -v "$root:/repo:ro" \
  -v "$fixture/public-image.tar:/image.tar:ro" "$image" \
  python /repo/tests/monitoring/pitr_runtime_check.py /image.tar

#!/usr/bin/env bash
# Run Python and PostgreSQL under the same clock in an isolated project.
set -euo pipefail

cd "$(dirname "$0")/.."
project="ugc-local-tests-$(date +%s)-$$"
compose=(docker compose -p "$project" --env-file /dev/null
    -f docker-compose.financial-test.yml)

cleanup() {
    "${compose[@]}" down --volumes --remove-orphans
}
trap cleanup EXIT

"${compose[@]}" run --build --rm -T test "$@"

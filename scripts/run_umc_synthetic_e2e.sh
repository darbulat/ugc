#!/usr/bin/env bash
# Create and clean up a uniquely named synthetic-only Compose project.
set -euo pipefail

cd "$(dirname "$0")/.."
project="umc-synthetic-e2e-$(date +%s)-$$"
compose=(docker compose -p "$project" -f docker-compose.test.yml -f docker-compose.synthetic-e2e.yml)

cleanup() {
    "${compose[@]}" down --volumes --remove-orphans
}
trap cleanup EXIT

"${compose[@]}" run --build --rm e2e "$@"

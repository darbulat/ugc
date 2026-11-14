#!/usr/bin/env bash
# Verify that the built image can import and configure the admin app offline.
set -euo pipefail

if [[ $# -ne 1 || -z "$1" ]]; then
    echo "Usage: $0 ADMIN_IMAGE" >&2
    exit 2
fi

# Use the driver shipped in the image. Import builds the engine lazily,
# and the isolated container has no connection to a database.
docker run --rm --pull=never --network=none \
    --label ugc.log_scope=release_check \
    --env BOT_TOKEN=test-token \
    --env ADMIN_PASSWORD=test_pass \
    --env ADMIN_SECRET=test_secret \
    --env DATABASE_URL=postgresql+psycopg://test:test@127.0.0.1:5432/test \
    --env KAFKA_ENABLED=false \
    --env USE_REDIS_STORAGE=false \
    --entrypoint python \
    -- "$1" -c 'from ugc_bot.admin.app import app; print("Admin Python import OK")'

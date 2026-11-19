#!/usr/bin/env bash
set -euo pipefail

# Immutable digest of the Prometheus 3.9.1 image used in production.
image="${1:-prom/prometheus@sha256:1f0f50f06acaceb0f5670d2c8a658a599affe7b0d8e78b898c1035653849a702}"
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --memory 128m --pids-limit 64 \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --label ugc_log_scope=release_check \
  --mount "type=bind,src=$PWD/config/monitoring,dst=/rules,readonly" \
  --mount "type=bind,src=$PWD/tests/monitoring,dst=/tests,readonly" \
  --entrypoint /bin/promtool "$image" \
  test rules /tests/telegram_webhook_alerts.test.yml

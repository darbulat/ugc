#!/usr/bin/env bash
# Run from the repository root, with an image built from the release Dockerfile.
set -euo pipefail

image="${1:?Usage: check_admin_image_import.sh ADMIN_IMAGE}"
root="$PWD"
tmp="$(mktemp -d)"
chmod 755 "$tmp"
stack="admin-import-${tmp##*.}"
network="$stack-net"
failing_image="$stack:failure"
cleanup() {
    if [[ "$1" != 0 ]]; then
        docker logs --tail 30 "$stack-promtail" >&2 || true
        docker logs --tail 30 "$stack-loki" >&2 || true
    fi
    docker rm -f -v "$stack-promtail" "$stack-loki" "$stack-app" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
    docker image rm "$failing_image" >/dev/null 2>&1 || true
    rm -rf "$tmp"
}
trap 'cleanup "$?"' EXIT

bash scripts/check_admin_image_import.sh "$image" | tee "$tmp/import.log"
grep -Fxq 'Admin Python import OK' "$tmp/import.log"

# Use the real relabeling rules and discover only containers from this test.
sed "/refresh_interval: 5s/a\\
        filters:\\
          - name: label\\
            values: ['ugc.ci.import_smoke=$stack']
" config/monitoring/promtail.yml > "$tmp/promtail.yml"
docker network create "$network" >/dev/null
docker run -d --name "$stack-loki" --network "$network" --network-alias loki \
    -p 127.0.0.1::3100 \
    -v "$root/config/monitoring/loki.yml:/etc/loki/loki.yml:ro" \
    -v "$root/config/monitoring/loki-alerts:/loki/rules:ro" \
    --tmpfs /loki:uid=10001,gid=10001,mode=0755 grafana/loki:3.6.0 -config.file=/etc/loki/loki.yml >/dev/null
docker run -d --name "$stack-promtail" --network "$network" \
    -v "$tmp/promtail.yml:/etc/promtail/promtail.yml:ro" \
    -v /var/run/docker.sock:/var/run/docker.sock:ro \
    grafana/promtail:3.6.0 -config.file=/etc/promtail/promtail.yml >/dev/null
port="$(docker port "$stack-loki" 3100/tcp)"
loki="http://$port"
curl -fsS --retry 30 --retry-delay 1 --retry-all-errors "$loki/ready" >/dev/null 2>&1

# Exercise a failing invocation of the same smoke script. Keep it alive long
# enough for Docker discovery and make it resemble a Compose admin service.
cat > "$tmp/fail-import" <<'FIXTURE'
#!/bin/sh
[ "$(ls /sys/class/net)" = lo ] || exit 43
printf 'Traceback (most recent call last): CI release-check probe\n' >&2
sleep 15
exit 42
FIXTURE
chmod +x "$tmp/fail-import"
docker build -q -t "$failing_image" -f - "$tmp" >/dev/null <<DOCKERFILE
FROM $image
LABEL ugc.ci.import_smoke=$stack com.docker.compose.project=$stack com.docker.compose.service=admin com.docker.compose.oneoff=False
COPY fail-import /usr/local/bin/python
DOCKERFILE

status=0
bash scripts/check_admin_image_import.sh "$failing_image" > "$tmp/failure.log" 2>&1 || status=$?
if [[ "$status" != 42 ]]; then
    cat "$tmp/failure.log"
    exit 1
fi

# Positive control in the same stack and evaluation window.
docker run -d --name "$stack-app" --network none \
    --label "ugc.ci.import_smoke=$stack" \
    --label "com.docker.compose.project=$stack" \
    --label com.docker.compose.service=app --label com.docker.compose.oneoff=False \
    --entrypoint sh "$image" -c \
    'echo "Traceback (most recent call last): CI service probe" >&2; sleep 20' >/dev/null

python3 - "$loki" <<'PYTEST'
import json
import sys
import time
import urllib.parse
import urllib.request

loki = sys.argv[1]


def fetch(path, **params):
    with urllib.request.urlopen(
        loki + path + "?" + urllib.parse.urlencode(params), timeout=5
    ) as response:
        return json.load(response)["data"]


def wait_for(check, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(2)
    raise SystemExit(f"Timed out waiting for {check.__name__}")


def logs(label, value, marker):
    data = fetch(
        "/loki/api/v1/query_range",
        query=f'{{{label}="{value}"}} |= "{marker}"',
        limit=10,
    )
    return [entry["stream"] for entry in data["result"]]


def release_probe_ingested():
    streams = logs("service", "release_check", "CI release-check probe")
    assert all(stream["log_scope"] == "release_check" for stream in streams)
    return streams


def service_probe_ingested():
    streams = logs("service", "app", "CI service probe")
    assert all(stream["log_scope"] == "compose_service" for stream in streams)
    return streams


def alert_firing_only_for_service():
    data = fetch("/prometheus/api/v1/rules", type="alert")
    rule = next(
        (rule for group in data["groups"] for rule in group["rules"]
         if rule["name"] == "UnhandledErrorInService"),
        None,
    )
    if not rule:
        return False
    assert rule["health"] == "ok", rule.get("lastError")
    alerts = rule["alerts"] or []
    assert all(alert["labels"].get("service") == "app" for alert in alerts), alerts
    return any(alert["state"] == "firing" for alert in alerts)


wait_for(release_probe_ingested, 45)
wait_for(service_probe_ingested, 45)
wait_for(alert_firing_only_for_service, 160)
print("Release-check traceback excluded; working-service traceback fired")
PYTEST

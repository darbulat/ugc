#!/bin/sh
# Zero-downtime deploy for app and app_2: update one instance at a time so
# nginx always has at least one healthy backend. Run from repository root.
# Usage: ./scripts/deploy_apps_zero_downtime.sh [compose args, e.g. -f docker-compose.yml -f docker-compose.prod.yml]
# Example: ./scripts/deploy_apps_zero_downtime.sh
# Example: ./scripts/deploy_apps_zero_downtime.sh -f docker-compose.yml -f docker-compose.prod.yml

set -e

if [ $# -eq 0 ]; then
    COMPOSE_ARGS="-f docker-compose.yml"
else
    COMPOSE_ARGS="$*"
fi

wait_healthy() {
    local service="$1"
    local max_attempts="${2:-40}"
    local attempt=1

    echo "Waiting for $service to become healthy (max ${max_attempts} attempts)..."
    while [ "$attempt" -le "$max_attempts" ]; do
        container_id=$(docker compose $COMPOSE_ARGS ps -q "$service" 2>/dev/null || true)
        if [ -n "$container_id" ]; then
            status=$(docker inspect -f '{{.State.Health.Status}}' "$container_id" 2>/dev/null || echo "no-health")
            if [ "$status" = "healthy" ]; then
                echo "$service is healthy."
                return 0
            fi
        fi
        printf "  attempt %d/%d\r" "$attempt" "$max_attempts"
        sleep 3
        attempt=$((attempt + 1))
    done

    echo "Error: $service did not become healthy in time." >&2
    return 1
}

echo "Building app image..."
docker compose $COMPOSE_ARGS build app

echo "Updating app (first instance)..."
docker compose $COMPOSE_ARGS up -d app
wait_healthy app

echo "Updating app_2 (second instance)..."
docker compose $COMPOSE_ARGS up -d app_2
wait_healthy app_2

echo "Zero-downtime deploy completed: both app and app_2 are running the new version."

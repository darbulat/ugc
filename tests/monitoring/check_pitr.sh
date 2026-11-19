#!/usr/bin/env bash
set -euo pipefail
image="$1"
age_dir="$2"
root=$(pwd)
fixture=$(mktemp -d)
name="ugc-pitr-check-${RANDOM}-$$"
pg_image="postgis/postgis@sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5"
cleanup() {
    docker exec "${name}-client" sh -c 'chmod -R a+rwX /work' >/dev/null 2>&1 || true
    docker rm -f -v "${name}-restore" "${name}-client" "${name}-db" >/dev/null 2>&1 || true
    docker volume rm "${name}-socket" >/dev/null 2>&1 || true
    rm -rf "$fixture"
}
trap cleanup EXIT
docker volume create "${name}-socket" >/dev/null
# Every database, volume and credential below is synthetic and task-scoped.
docker run -d --name "${name}-db" --network bridge --memory 512m --memory-swap 512m \
  -e POSTGRES_PASSWORD=fixture -e POSTGRES_DB=fixture "$pg_image" \
  -c wal_level=replica -c max_wal_senders=4 -c max_replication_slots=4 \
  -c max_slot_wal_keep_size=64MB -c archive_mode=off >/dev/null
for attempt in $(seq 1 60); do
  if docker exec "${name}-db" pg_isready -h 127.0.0.1 -U postgres -d fixture >/dev/null 2>&1; then break; fi
  [[ "$attempt" -lt 60 ]] || exit 1
  sleep 1
done
docker exec "${name}-db" sh -c 'printf "\nhost replication ugc_pitr_v1 0.0.0.0/0 scram-sha-256\n" >> "$PGDATA/pg_hba.conf"'
# Reproduce the audited host: file says 20, live command line remains 4.
docker exec "${name}-db" sh -c 'printf "\nmax_replication_slots = 20\n" >> "$PGDATA/postgresql.conf"'
docker exec "${name}-db" psql -U postgres -d fixture -c 'SELECT pg_reload_conf()' >/dev/null
mkdir "$fixture/tmp"
docker run -d --name "${name}-client" --network "container:${name}-db" \
  --read-only --memory 256m --memory-swap 256m --cpus 0.5 --pids-limit 64 \
  -e TMPDIR=/work/tmp -v "$fixture:/work" -v "$root/scripts:/pitr:ro" \
  -v "${name}-socket:/socket" \
  -v "$root/tests/monitoring/pitr_roundtrip.py:/pitr-test.py:ro" \
  -v "$age_dir/age:/tools/age:ro" -v "$age_dir/age-keygen:/tools/age-keygen:ro" \
  "$image" python -c 'import time;time.sleep(900)' >/dev/null
docker exec "${name}-client" python /pitr-test.py setup
prepared=$(docker exec "${name}-client" cat /work/prepared-name)
[[ "$prepared" =~ ^restore-work-[a-zA-Z0-9_]+$ ]] || exit 1
docker exec "${name}-client" chown -R 999:999 /work/restore /work/archive /work/keys
docker exec "${name}-client" chown 999:999 /socket
docker run -d --name "${name}-restore" --network none --memory 512m --memory-swap 512m \
  -e PGDATA=/restore/pgdata -e CREDENTIALS_DIRECTORY=/keys \
  -v "$fixture/restore/$prepared:/restore" -v "$fixture/archive:/archive:ro" \
  -v "$fixture/keys:/keys:ro" -v "$age_dir/age:/tools/age:ro" \
  -v "${name}-socket:/socket" \
  -v "$root/scripts/pitr_fetch_wal.sh:/tools/fetch-wal:ro" "$pg_image" \
  -c listen_addresses= -c port=16544 -c unix_socket_directories=/socket \
  -c hba_file=/restore/hba.conf -c shared_buffers=64MB >/dev/null
for attempt in $(seq 1 60); do
  if docker exec "${name}-restore" psql -h /socket -p 16544 -U postgres -d postgres \
    -Atc "SELECT pg_get_wal_replay_pause_state()" 2>/dev/null | grep -qx paused; then break; fi
  [[ "$attempt" -lt 60 ]] || { docker logs "${name}-restore"; exit 1; }
  sleep 1
done
docker exec "${name}-client" python /pitr-test.py proof
docker inspect "${name}-client" --format 'Client OOM={{.State.OOMKilled}} MemoryLimit={{.HostConfig.Memory}}'

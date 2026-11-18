#!/usr/bin/env bash
set -euo pipefail

image="$1"
project="ugc-release-check-${RANDOM}-$$"
fixture=$(mktemp -d)
cleanup() {
    docker compose -p "$project" --project-directory "$fixture" -f "$fixture/compose.json" down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$fixture"
}
trap cleanup EXIT

export RELEASE_FIXTURE="$fixture" RELEASE_PROJECT="$project" RELEASE_IMAGE="$image"
python3 - <<'PY'
import json
import os
from pathlib import Path

directory = Path(os.environ['RELEASE_FIXTURE'])
settings = {
    'services': {'app': {
        'image': os.environ['RELEASE_IMAGE'],
        'environment': {'SYNTHETIC_TOKEN': 'literal$$value$${HOME}$$$$'},
        'command': ['python', '-c', 'import time; time.sleep(300)'],
        'volumes': ['data:/data'],
        'deploy': {'placement': {}},
        'networks': {'default': {'aliases': ['app-durable-alias']}},
        'healthcheck': {
            'test': ['CMD', 'python', '-c', 'print("ready")'],
            'interval': '1s', 'timeout': '2s', 'retries': 5,
        },
    }},
    'volumes': {'data': {}},
    'networks': {'default': {
        'name': os.environ['RELEASE_PROJECT'] + '_default',
        'driver': 'bridge',
    }},
}
(directory / 'compose.json').write_text(json.dumps(settings))
external = {
    'services': {'app_2': {
        'image': os.environ['RELEASE_IMAGE'],
        'command': ['python', '-c', 'import time; time.sleep(300)'],
        'networks': {'default': {'aliases': ['preserved-alias']}},
    }},
    'networks': {'default': {
        'name': os.environ['RELEASE_PROJECT'] + '_default',
        'external': True,
    }},
}
(directory / 'external.json').write_text(json.dumps(external))
PY
docker compose -p "$project" --project-directory "$fixture" -f "$fixture/compose.json" up -d --no-build --pull never >/dev/null
docker compose -p "$project" --project-directory "$fixture" -f "$fixture/external.json" up -d --no-deps --no-build --pull never app_2 >/dev/null
python3 - <<'PY'
import json
import hashlib
import os
from pathlib import Path
import runpy
import subprocess
import sys

namespace = runpy.run_path('scripts/production_release.py')
snapshot = namespace['live_snapshot']
snapshot.__globals__['PROJECT'] = os.environ['RELEASE_PROJECT']
snapshot.__globals__['PROJECT_DIRECTORY'] = os.environ['RELEASE_FIXTURE']
names = subprocess.check_output([
    'docker', 'ps', '-aq', '--filter',
    'label=com.docker.compose.project=' + os.environ['RELEASE_PROJECT'],
], text=True).split()
initial = json.loads(subprocess.check_output(['docker', 'inspect', *names]))
by_service = {row['Config']['Labels']['com.docker.compose.service']: row for row in initial}
original = by_service['app']
peer_id = by_service['app_2']['Id']
network_name = os.environ['RELEASE_PROJECT'] + '_default'
network_id = original['NetworkSettings']['Networks'][network_name]['NetworkID']
# Limits changed through the daemon must survive stale Compose labels.
subprocess.run([
    'docker', 'update', '--memory', '64m', '--memory-swap', '64m',
    '--cpus', '0.5', '--pids-limit', '64', original['Id'],
], check=True, capture_output=True)
containers = json.loads(subprocess.check_output(['docker', 'inspect', *names]))
config = snapshot(containers)
assert config['networks'] == {'default': {'name': network_name, 'external': True}}
assert config['services']['app_2']['networks']['default']['aliases'] == ['preserved-alias']
assert config['services']['app']['mem_limit'] == str(64 * 1024**2)
assert config['services']['app']['cpus'] == 0.5
assert config['services']['app']['pids_limit'] == 64
assert config['services']['app']['environment']['SYNTHETIC_TOKEN'] == 'literal$value${HOME}$$'
destination = Path(os.environ['RELEASE_FIXTURE']) / 'durable.json'
try:
    namespace['write_snapshot'](destination, config)
except RuntimeError:
    command = namespace['compose_base']() + ['-f', '-', 'config', '--format', 'json']
    resolved = json.loads(namespace['checked'](
        command, stdin=json.dumps(namespace['escape_interpolation'](config)),
    ))
    print('Synthetic token expected', repr(config['services']['app']['environment']['SYNTHETIC_TOKEN']))
    print('Synthetic token resolved', repr(resolved['services']['app']['environment']['SYNTHETIC_TOKEN']))
    raise
assert destination.stat().st_mode & 0o777 == 0o600
before = namespace['runtime_signature'](next(row for row in containers if row['Id'] == original['Id']))
subprocess.run([
    'docker', 'compose', '-p', os.environ['RELEASE_PROJECT'],
    '--project-directory', os.environ['RELEASE_FIXTURE'], '-f', str(destination),
    'up', '-d', '--force-recreate', '--no-build', '--pull', 'never', 'app',
], check=True, capture_output=True)
current_name = os.environ['RELEASE_PROJECT'] + '-app-1'
current = json.loads(subprocess.check_output(['docker', 'inspect', current_name]))[0]
assert namespace['runtime_signature'](current) == before
assert current['NetworkSettings']['Networks'][network_name]['NetworkID'] == network_id
assert 'app-durable-alias' in current['NetworkSettings']['Networks'][network_name]['Aliases']
peer = json.loads(subprocess.check_output(['docker', 'inspect', os.environ['RELEASE_PROJECT'] + '-app_2-1']))[0]
assert peer['Id'] == peer_id
assert peer['NetworkSettings']['Networks'][network_name]['NetworkID'] == network_id
print('Durable Compose snapshot preserved runtime settings and literal secrets')
print('Bridge and external network snapshots reused the same existing network without replacing the peer')

# Exercise the actual recovery command, including formerly unlimited memory.
sys.path.insert(0, 'scripts')
import apply_resource_policy as policy
info = json.loads(subprocess.check_output(['docker', 'info', '--format', 'json']))
restored = policy.rollback_limits(original, info['MemTotal'], info['NCPU'])
policy.update(current['Id'], restored)
after = json.loads(subprocess.check_output(['docker', 'inspect', current_name]))[0]
assert after['Id'] == current['Id']
assert after['State']['StartedAt'] == current['State']['StartedAt']
assert after['RestartCount'] == current['RestartCount']
assert not after['State']['OOMKilled']
for field in ('Memory', 'MemorySwap', 'NanoCpus'):
    assert after['HostConfig'][field] == restored[field]
assert after['HostConfig']['PidsLimit'] in (-1, 0, None)
print('Real Docker rollback restored full host capacity without restarting')

# The normal CLI must validate the same snapshots without replacing anything.
directory = Path(os.environ['RELEASE_FIXTURE'])
archive = directory / 'image.tar.gz'
archive.write_bytes(b'synthetic checksum fixture; never loaded by check-only')
(directory / 'manifest.json').write_text(json.dumps({
    'revision': 'a' * 40,
    'image_id': current['Image'],
    'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
}))
parameters = directory / 'parameters.json'
parameters.write_text(json.dumps({'META_TOKEN_MONITOR_IMAGE': 'synthetic:image'}))
parameters.chmod(0o600)
sys.argv = ['production_release.py', str(directory), 'app', '--check-only',
            '--snapshot-environment', str(parameters)]
namespace['main']()
final = json.loads(subprocess.check_output(['docker', 'inspect', current_name]))[0]
assert final['Id'] == current['Id']
assert namespace['runtime_signature'](final) == namespace['runtime_signature'](after)
assert json.loads(subprocess.check_output(['docker', 'inspect', peer_id]))[0]['Id'] == peer_id
print('Check-only CLI validated the live snapshot without replacing containers')
PY

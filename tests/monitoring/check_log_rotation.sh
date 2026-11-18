#!/usr/bin/env bash
set -euo pipefail
image="$1"
name="ugc-log-check-${RANDOM}-$$"
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT
# Synthetic logs in a dedicated container. Never edit Docker-owned log files.
docker run -d --name "$name" --network none --read-only \
    --memory 64m --memory-swap 64m --cpus 0.5 --pids-limit 64 \
    --log-driver json-file --log-opt max-size=10k --log-opt max-file=2 \
    "$image" python -u -c 'import time; [print("x"*900) for _ in range(200)]; time.sleep(300)' >/dev/null
export LOG_CHECK_NAME="$name" LOG_CHECK_IMAGE="$image"
python3 - <<'PY'
import json
import os
import subprocess
import time

name = os.environ['LOG_CHECK_NAME']
for _ in range(30):
    logs = subprocess.check_output(['docker', 'logs', name], text=True)
    if logs:
        break
    time.sleep(1)
else:
    raise AssertionError('No synthetic logs written')
time.sleep(1)
current = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
assert current['HostConfig']['LogConfig'] == {
    'Type': 'json-file', 'Config': {'max-size': '10k', 'max-file': '2'},
}
# Inspect only file counts and sizes, with a read-only mount, even on DinD.
result = subprocess.check_output([
    'docker', 'run', '--rm', '--network', 'none', '--read-only',
    '--cap-drop', 'ALL', '--cap-add', 'DAC_READ_SEARCH',
    '--user', '0', '--entrypoint', 'python',
    '--mount', 'type=bind,src=' + os.path.dirname(current['LogPath'])
    + ',dst=/logs,readonly', os.environ['LOG_CHECK_IMAGE'], '-c',
    'import json,pathlib; print(json.dumps({p.name:p.stat().st_size '
    'for p in pathlib.Path("/logs").glob("*-json.log*")}))',
], text=True)
sizes = json.loads(result)
assert len(sizes) == 2, sizes
# Docker rotates between complete records, so one record may exceed max-size.
assert all(0 < size <= 10240 + 1100 for size in sizes.values()), sizes
print('Docker rotated synthetic JSON logs and retained exactly two bounded files')
PY

#!/usr/bin/env python3
"""Read-only production health snapshot for a forced-command SSH key.

No input is interpreted and no app/worker code is imported. S3 credentials
stay in the backup container. Only allowlisted status fields leave the host.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

SERVICES = ("app", "app_2", "admin", "db")

# Executed in the existing backup image, which already contains boto3.
S3_QUERY = r"""
import datetime, hashlib, json, os, re
from pathlib import Path
import boto3
from botocore.config import Config

root = Path(os.environ.get("UMC_MONITOR_BACKUP_ROOT", "/backups"))
cache_file = root / ".umc-monitor-fingerprints.json"
try:
    fingerprints = json.loads(cache_file.read_text())
    if not isinstance(fingerprints, dict):
        fingerprints = {}
except (ValueError, OSError):
    fingerprints = {}


def fingerprint(path):
    before = path.stat()
    identity = [before.st_size, before.st_mtime_ns, before.st_ino]
    cached = fingerprints.get(str(path), {})
    if cached.get("identity") == identity:
        return cached
    sha, md5, parts = hashlib.sha256(), hashlib.md5(), []
    with path.open("rb") as stream:
        while True:
            block = stream.read(8 * 1024 * 1024)
            if not block:
                break
            sha.update(block)
            md5.update(block)
            parts.append(hashlib.md5(block).digest())
    after = path.stat()
    if identity != [after.st_size, after.st_mtime_ns, after.st_ino]:
        raise ValueError("backup_changed_during_verification")
    result = {
        "identity": identity,
        "sha256": sha.hexdigest(),
        "single": md5.hexdigest(),
        "multipart": hashlib.md5(b"".join(parts)).hexdigest()
        + "-"
        + str(len(parts)),
    }
    fingerprints[str(path)] = result
    return result


s = boto3.client(
    "s3",
    endpoint_url=os.environ["S3_ENDPOINT_URL"],
    region_name=os.environ.get("AWS_DEFAULT_REGION"),
    aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
    config=Config(
        connect_timeout=3,
        read_timeout=3,
        retries={"total_max_attempts": 1},
        s3={"addressing_style": "path"},
    ),
)
result = {"ok": True, "logical": None, "physical": None}
now = datetime.datetime.now(datetime.timezone.utc).timestamp()
for kind, prefix, pattern in [
    ("logical", "backups/", r"backups/ugc_backup_(\d{8}_\d{6})\.sql\.gz"),
    (
        "physical",
        "base_backups/",
        r"base_backups/ugc_basebackup_(\d{8}_\d{6})\.tar\.gz",
    ),
]:
    items = []
    for page in s.get_paginator("list_objects_v2").paginate(
        Bucket=os.environ["S3_BUCKET"],
        Prefix=prefix,
        PaginationConfig={"MaxItems": 1000},
    ):
        items.extend(page.get("Contents", []))
    for item in sorted(items, key=lambda item: item["Key"], reverse=True):
        match = re.fullmatch(pattern, item["Key"])
        if not match or item["Size"] <= 0:
            continue
        stamp = (
            datetime.datetime.strptime(match[1], "%Y%m%d_%H%M%S")
            .replace(tzinfo=datetime.timezone.utc)
            .timestamp()
        )
        if stamp > now or (result[kind] is not None and stamp <= result[kind]):
            continue
        head = s.head_object(Bucket=os.environ["S3_BUCKET"], Key=item["Key"])
        local = (root if kind == "logical" else root / "base") / Path(
            item["Key"]
        ).name
        if not local.is_file():
            continue
        digest = fingerprint(local)
        if (
            head["ContentLength"] == item["Size"] == digest["identity"][0]
            and head.get("Metadata", {}).get("sha256") == digest["sha256"]
            and head.get("ETag", "").strip('"')
            in (digest["single"], digest["multipart"])
        ):
            result[kind] = stamp
            break
temporary = cache_file.with_suffix("." + str(os.getpid()) + ".tmp")
fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as stream:
    json.dump(dict(list(fingerprints.items())[-10:]), stream)
os.replace(temporary, cache_file)
print(json.dumps(result))
"""

DATABASE_QUERY = r"""
import json, urllib.request

try:
    with urllib.request.urlopen(
        "http://127.0.0.1:8001/health", timeout=3
    ) as response:
        body = json.loads(response.read(1024))
        print(
            json.dumps(
                {
                    "ready": response.status == 200
                    and body.get("status") == "ok"
                    and body.get("db") is True
                }
            )
        )
except Exception:
    print(json.dumps({"ready": False}))
"""


def command(arguments: list[str], timeout: int = 4) -> str:
    result = subprocess.run(
        arguments, capture_output=True, timeout=timeout, check=True
    )
    if len(result.stdout) > 32768:
        raise ValueError("oversized_response")
    return result.stdout.decode()


def docker_services() -> dict[str, str]:
    services = {name: "missing" for name in SERVICES}
    template = (
        "{{.Name}} {{.State.Status}} "
        "{{if .State.Health}}{{.State.Health.Status}}{{end}}"
    )
    response = subprocess.run(
        ["docker", "inspect", "--format", template]
        + ["ugc-" + name + "-1" for name in SERVICES],
        capture_output=True,
        timeout=4,
    )
    for line in response.stdout.decode().splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        name = fields[0].removeprefix("/ugc-").removesuffix("-1")
        if name in services:
            services[name] = (
                "healthy"
                if fields[1:] == ["running", "healthy"]
                else "unhealthy"
            )
    return services


def backup_status(cache_path: Path, now: float) -> dict[str, Any]:
    cached: dict[str, Any] = {}
    if cache_path.exists():
        with suppress(ValueError, OSError):
            data = json.loads(cache_path.read_text())
            if isinstance(data, dict):
                cached = data
    if not isinstance(cached.get("checked_at", 0), (int, float)):
        cached = {}
    age = now - cached.get("checked_at", 0)
    ttl = 600 if cached.get("ok") else 60
    if 0 <= age < ttl:
        return cached
    try:
        result = json.loads(
            command(
                [
                    "docker",
                    "exec",
                    "ugc-db_backup-1",
                    "python3",
                    "-c",
                    S3_QUERY,
                ],
                timeout=12,
            )
        )
        result = {key: result.get(key) for key in ("ok", "logical", "physical")}
        result["failures"] = 0
    except Exception:
        previous = cached.get("failures", 0)
        previous = previous if isinstance(previous, int) else 0
        result = {
            "ok": False,
            "logical": cached.get("logical"),
            "physical": cached.get("physical"),
            "failures": min(previous + 1, 3),
        }
    result["checked_at"] = now
    cache_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = cache_path.with_suffix(f".{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(result, stream)
    os.replace(temporary, cache_path)
    return result


def snapshot(cache_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"version": 1, "docker": False}
    try:
        command(["docker", "info", "--format", "{{.ServerVersion}}"])
    except Exception:
        result["generated_at"] = time.time()
        return result
    result["docker"] = True
    try:
        result["services"] = docker_services()
    except Exception:
        result["services"] = {name: "unknown" for name in SERVICES}
    try:
        data = json.loads(
            command(
                [
                    "docker",
                    "exec",
                    "ugc-admin-1",
                    "python",
                    "-c",
                    DATABASE_QUERY,
                ],
                timeout=5,
            )
        )
        result["database_ready"] = data.get("ready") is True
    except Exception:
        result["database_ready"] = False
    result["backup"] = backup_status(cache_path, time.time())
    result["generated_at"] = time.time()
    return result


if __name__ == "__main__":
    try:
        print(json.dumps(snapshot(Path.home() / ".cache/umc-monitor/s3.json")))
    except Exception:
        # No stderr/tracebacks: errors must not expose credentials or app data.
        print(
            json.dumps(
                {
                    "version": 1,
                    "generated_at": time.time(),
                    "error": "snapshot_failed",
                }
            )
        )
        raise SystemExit(1) from None
